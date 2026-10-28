"""Native llama.cpp inference via owned local sessions or files/stdout; no LM Studio."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from .core import Project, atomic_text, translation_key, uid
from .process_control import ChildJob
from .storage import check_space, offline_env


def strict_object(pairs):
    value = {}
    for key,item in pairs:
        if key in value:
            raise ValueError('Powtórzone ID w odpowiedzi modelu.')
        value[key] = item
    return value


def validate_batch(content: str, ids: list[str]) -> dict[str,str]:
    text = content.strip()
    # llama-completion appends this transport marker after an EOS token.
    if text.endswith('[end of text]'):
        text = text[:-len('[end of text]')].rstrip()
    value = json.loads(text,object_pairs_hook=strict_object)
    if not isinstance(value,dict) or set(value) != set(ids):
        raise ValueError('Nieprawidłowy zestaw ID w tłumaczeniu partii.')
    for key,translated in value.items():
        if not isinstance(translated,str) or not translated.strip() or len(translated)>4000:
            raise ValueError('Puste lub zbyt długie tłumaczenie.')
        if '<think>' in translated.lower() or '</think>' in translated.lower():
            raise ValueError('Rozumowanie w polu tłumaczenia.')
        value[key] = translated.strip()
    return value


def model_identity(spec):
    model,executable = Path(spec['model_path']).resolve(),Path(spec['executable']).resolve()
    if not model.is_file() or model.suffix.lower()!='.gguf':
        raise ValueError('Nie znaleziono lokalnego modelu GGUF.')
    with model.open('rb') as stream:
        if stream.read(4)!=b'GGUF':
            raise ValueError('Wybrany plik nie jest modelem GGUF.')
    if not executable.is_file():
        raise ValueError('Nie znaleziono wbudowanego silnika llama.cpp. Wskaż go w ustawieniach folderów.')
    name = model.name.lower()
    if 'qwen3' not in name or 'instruct' not in name or 'qwen3.5' in name:
        raise ValueError('Wbudowany profil obsługuje obecnie Qwen3 Instruct. Wybierz Qwen3-4B-Instruct-2507.')
    payload = {'model':str(model),'size':model.stat().st_size,'mtime':model.stat().st_mtime_ns,
               'runtime':str(executable),'runtime_size':executable.stat().st_size,
               'runtime_mtime':executable.stat().st_mtime_ns,'context':spec.get('context_length',4096),
               'profile':'qwen3-instruct-chatml-v2-source-guard','temperature':0.1,'seed':42,
               'batch_size':spec.get('batch_size',6),'device':spec.get('device','vulkan')}
    if spec.get('film_context'): payload['film_context']=spec['film_context']
    if spec.get('keep_loaded'):
        server=executable.with_name('llama-server.exe')
        payload['transport']='owned-native-session-v1'
        payload['server_size']=server.stat().st_size
        payload['server_mtime']=server.stat().st_mtime_ns
    return 'embedded:'+hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def prompt_and_schema(track, indices, instruction,film_context=''):
    targets = [track.segments[i] for i in indices]
    context_indices = sorted({j for i in indices for j in range(max(0,i-2),min(len(track.segments),i+3)) if j not in indices})
    payload = {'context':[{'id':track.segments[j].id,'text':track.segments[j].text} for j in context_indices],
               'targets':[{'id':s.id,'text':s.text} for s in targets]}
    if film_context: payload['tentative_film_context_for_interpretation_only']=film_context[:900]
    request = json.dumps(payload,ensure_ascii=False).replace('<|','\\u003c|')
    instruction += ('\nTranslate every target, using the surrounding targets and context for interpretation only. '
                    'Preserve who is speaking to whom; do not add I/my to a question addressed to someone else. '
                    'Preserve uncertainty, negation and question versus statement. '
                    'For names use a well-supported established spelling; if uncertain keep the exact Japanese name, never guess a reading. '
                    'A tentative English synopsis may contain incorrect names or claims; it must never override Japanese evidence. '
                    'Return one JSON object: each key is an exact target ID and each value is its English translation. '
                    'Include every target ID exactly once; do not output context as dialogue.')
    prompt = ('<|im_start|>system\n'+instruction+'<|im_end|>\n<|im_start|>user\n'+request+
              '<|im_end|>\n<|im_start|>assistant\n')
    schema = {'type':'object','properties':{s.id:{'type':'string','minLength':1,'maxLength':4000} for s in targets},
              'required':[s.id for s in targets],'additionalProperties':False}
    return prompt,schema


def infer_batch(spec,track,indices,folder,emit):
    prompt,schema = prompt_and_schema(track,indices,spec['prompt'],spec.get('film_context',''))
    value = infer_json(spec,prompt,schema,folder,emit)
    return validate_batch(json.dumps(value,ensure_ascii=False),[track.segments[i].id for i in indices])


def infer_json(spec,prompt,schema,folder,emit):
    check_space(folder,4*1024**2,float(spec.get('reserve_gib',2)))
    from .native_session import ACTIVE
    if ACTIVE.get() is not None and spec.get('keep_loaded'):
        return ACTIVE.get().infer(spec,prompt,schema,folder,emit)
    run_folder = folder/uid()
    run_folder.mkdir()
    prompt_file,schema_file = run_folder/'prompt.txt',run_folder/'schema.json'
    atomic_text(prompt_file,prompt)
    atomic_text(schema_file,json.dumps(schema))
    ctx = int(spec.get('context_length',4096))
    if not 2048<=ctx<=8192:
        raise ValueError('Kontekst tłumacza musi wynosić 2048–8192 tokenów.')
    device = spec.get('device','vulkan')
    if device not in {'vulkan','cuda','cpu'}:
        raise ValueError('Nieobsługiwane urządzenie tłumacza.')
    native_device={'vulkan':'Vulkan0','cuda':'CUDA0','cpu':'none'}[device]
    args = [str(Path(spec['executable']).resolve()),'--model',str(Path(spec['model_path']).resolve()),
            '--ctx-size',str(ctx),'--fit','off','--n-gpu-layers','0' if device=='cpu' else '99',
            '--device',native_device,
            '--batch-size','256','--ubatch-size','128','--n-predict','2048',
            '--temp','0.1','--seed','42','--no-conversation','--no-display-prompt','--simple-io',
            '--no-perf','--file',str(prompt_file),'--json-schema-file',str(schema_file)]
    if spec.get('diagnostic_logging'):
        args += ['--verbosity','3']
    atomic_text(run_folder/'command.json',json.dumps(args,ensure_ascii=False,indent=2))
    env = {**os.environ,**offline_env(),'TEMP':str(run_folder),'TMP':str(run_folder)}
    started = time.monotonic()
    emit('phase',message='Ładowanie modelu i przetwarzanie partii…')
    with (run_folder/'output.txt').open('wb') as output,(run_folder/'engine.log').open('wb') as log:
        process = subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=output,stderr=log,
                                   env=env,cwd=run_folder,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            with ChildJob(process):
                try:
                    code = process.wait(timeout=int(spec.get('timeout',240)))
                except subprocess.TimeoutExpired as exc:
                    process.kill()
                    process.wait(timeout=10)
                    raise RuntimeError('Model przekroczył limit czasu. Zapisane wyniki zachowano; zmniejsz partię lub sprawdź log.') from exc
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    if code:
        detail = (run_folder/'engine.log').read_text('utf8',errors='replace')[-2000:]
        raise RuntimeError(f'Błąd wbudowanego silnika ({code}). Sprawdź model i pamięć GPU.\n{detail}')
    content = (run_folder/'output.txt').read_text('utf8',errors='strict')
    content = content.strip()
    if content.endswith('[end of text]'):
        content = content[:-len('[end of text]')].rstrip()
    value = json.loads(content,object_pairs_hook=strict_object)
    emit('phase',message=f'Partia zakończona w {time.monotonic()-started:.1f} s • pamięć modelu zwolniona')
    return value


def translate(spec,emit):
    project = Project.from_dict(spec['project'])
    track = project.active
    if not track or not track.segments:
        raise ValueError('Brak ścieżki z napisami do tłumaczenia.')
    identity = model_identity(spec)
    folder = Path(spec['cache_dir'])/'embedded-translation'/str(spec.get('job_id',uid()))
    check_space(folder,4*1024**2,float(spec.get('reserve_gib',2)))
    folder.mkdir(parents=True,exist_ok=True)
    batch_size = int(spec.get('batch_size',6))
    if not 1<=batch_size<=12:
        raise ValueError('Partia tłumaczenia musi zawierać 1–12 napisów.')
    keys,pending = {},[]
    total,done,errors = len(track.segments),0,0
    for i,s in enumerate(track.segments):
        context = track.segments[max(0,i-2):i]+track.segments[i+1:i+3]
        keys[s.id] = translation_key(s,context,identity,spec['prompt'])
        if s.translation and (s.translation_key==keys[s.id] or s.status=='manual'):
            done+=1
        else:
            pending.append(i)
    emit('progress',done=done,total=total)
    for offset in range(0,len(pending),batch_size):
        indices = pending[offset:offset+batch_size]
        try:
            translations = infer_batch(spec,track,indices,folder,emit)
        except (ValueError,UnicodeError) as exc:
            if len(indices)==1:
                translations = {}
            else:
                emit('phase',message='Nieprawidłowa partia — ponawiam pojedyncze napisy.')
                translations = {}
                for i in indices:
                    try:
                        translations.update(infer_batch(spec,track,[i],folder,emit))
                    except (ValueError,UnicodeError) as error:
                        emit('segment_error',id=track.segments[i].id,message=str(error))
                        errors+=1
            if len(indices)==1:
                emit('segment_error',id=track.segments[indices[0]].id,message=str(exc))
                errors+=1
        for i in indices:
            s = track.segments[i]
            if s.id in translations:
                emit('translation',id=s.id,translation=translations[s.id],key=keys[s.id])
            done+=1
            emit('progress',done=done,total=total)
    emit('done',errors=errors)

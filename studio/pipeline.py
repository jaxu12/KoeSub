"""Pipeline plans and provenance. No GPU work or UI dependencies."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import asdict
from pathlib import Path

from .core import Segment, Track, atomic_text, normalize, now, read_json_file, split_segment, uid
from .review import ReviewSettings, metrics, reflow_english, reflow_japanese, split_proposal

VARIANTS = [
    ('Naturalny', 'Use natural idiomatic English while preserving every meaning and speaker.'),
    ('Wierny', 'Use a close faithful translation. Pay particular attention to negation, names, tense and ambiguity.'),
    ('Zwięzły', 'Prefer concise subtitle English, preserving all meaningful dialogue and characterization.'),
    ('Kontekstowy', 'Resolve pronouns and terminology consistently using context. Never invent missing facts.')]

REVIEW_CODES = {'ok': '', 'meaning': 'AI: możliwa zmiana znaczenia', 'omission': 'AI: możliwe pominięcie',
                'addition': 'AI: możliwy dodatek', 'name': 'AI: nazwy / spójność',
                'uncertain': 'AI: niepewny przekład — sprawdź odsłuch'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def file_identity(path):
    item = Path(path).resolve()
    if not item.is_file():
        raise ValueError(f'Nie znaleziono pliku: {item}')
    stat = item.stat()
    return {'path':str(item),'size':stat.st_size,'mtime':stat.st_mtime_ns}


def repairs_enabled(config):
    # Missing field preserves the exact plan of older resumable manifests.
    return config.get('review_action','repair' if config['review']=='deep' else 'check')=='repair'


def source_surface_conflicts(japanese,english):
    # This is a narrow, deterministic check, not an attempt to infer omitted JP subjects.
    if re.search(r'[?？]["”’』」]*\s*$',japanese) and not re.search(r'[?？]',english):
        return ['AI: jawne pytanie JP utraciło formę pytania w EN']
    return []


def plan(config):
    if config.get('transcription_only'):
        stages=[('audio','Przygotowanie audio'),('asr-0','Baza JP • Large V3 + VAD')]
        if config.get('retry_asr',{}).get('enabled'):
            if config['retry_asr'].get('scan_first') and config['retry_asr'].get('auxiliary'):
                stages.append(('asr-scan','Auxiliary ASR scan • detect disagreements'))
            stages.append(('asr-retry','Podejrzane wycinki • ponowienie Large V3 i model pomocniczy'))
        if config.get('source_review_version'):
            stages.append(('jp-review','Review oryginału JP • porównanie i składanie fraz'))
        if config.get('jp_context_review'):
            stages.append(('jp-context','Japanese scene context • words, names and ASR recommendations'))
        if config.get('adaptive_retry',{}).get('enabled'):
            stages.append(('jp-adaptive','Adaptive audio • short/wide context and quiet boundaries'))
        if config.get('jp_alignment',{}).get('enabled'):
            stages.append(('jp-align','Final text • forced audio alignment and phrase splitting'))
        stages.extend([('jp-layout','Układ napisów JP'),('jp-export','Eksport JP i raport wycinków')])
        return [{'id':key,'label':label,'status':'pending'} for key,label in stages]
    stages = [('audio','Przygotowanie audio')]
    for i, item in enumerate(config['asr']):
        stages.append((f'asr-{i}',f'Transkrypcja {i+1}: {item["name"]}'))
    for i in range(1,len(config['asr'])):
        stages.append((f'merge-{i}',f'Porównanie i wybór JP {i+1}'))
    if config.get('source_review_version'):
        stages.append(('jp-review','Review oryginału JP • rozbieżności przed tłumaczeniem'))
    if config.get('film_context'):
        stages.append(('context','Kontekst całego filmu • temat i terminy'))
    for i, item in enumerate(config['translations']):
        stages.append((f'en-{i}',f'Tłumaczenie {i+1}: {VARIANTS[item["variant"]][0]}'))
    stages.append(('choose-en','Porównanie i wybór EN'))
    if config.get('film_context') and config['review'] in {'balanced','deep'}:
        stages.append(('coherence','Spójność całych napisów i kontekstu'))
    if config['review'] in {'balanced','deep'}:
        stages.append(('semantic','Review AI: ' + ('podejrzane miejsca' if config['review']=='balanced' else 'wszystkie napisy')))
    if config['review'] in {'balanced','deep'} and repairs_enabled(config):
        stages += [('repair','Próba poprawy i porównanie'),('verify','Ponowna ocena AI')]
    stages += [('layout','Formatowanie i końcowe review'),('export','Raport i eksport SRT')]
    return [{'id':key,'label':label,'status':'pending'} for key,label in stages]


def validate_config(config):
    if config.get('source_review_version') not in (None,1,2,3):
        raise ValueError('Nieobsługiwana wersja review oryginału JP.')
    jp_only=config.get('transcription_only',False)
    if jp_only:
        if len(config['asr'])!=1 or config['asr'][0]['engine']!=2 or 'kotoba' in config['asr'][0]['model'].lower() or not config['asr'][0]['vad']:
            raise ValueError('Tryb JP wymaga jednej bazy Whisper Large V3 GGML z VAD.')
        if config['translations']: raise ValueError('Tryb JP nie uruchamia tłumaczenia.')
        options=config.get('retry_asr',{})
        if type(options.get('scan_first',False)) is not bool: raise ValueError('Invalid auxiliary scan option')
        if type(options.get('batch_retries',False)) is not bool: raise ValueError('Invalid grouped retry option')
        if (options.get('third') or options.get('batch_retries')) and config.get('source_review_version')!=3:
            raise ValueError('Third ASR and grouped retries require source review v3')
        if options.get('third'):
            models=[config['asr'][0],options.get('auxiliary'),options['third']]
            if any(not m or m['engine'] not in (1,2,3) for m in models): raise ValueError('Three distinct local CrispASR models are required')
            identities=[str(Path(m['model']).resolve()).casefold() for m in models]
            if len(set(identities))!=3: raise ValueError('Third ASR must use distinct model weights')
        value=options.get('third_max_targets',6)
        if type(value) is not int or not 1<=value<=30: raise ValueError('Invalid third ASR window limit')
        for key,low,high,default in [('padding_ms',1000,10000,3000),('max_window_ms',5000,60000,30000),('max_targets',1,30,12)]:
            value=options.get(key,default)
            if type(value) is not int or not low<=value<=high: raise ValueError('Nieprawidłowy limit ponowień: '+key)
    if type(config.get('jp_context_review',False)) is not bool: raise ValueError('Invalid JP context review option')
    if config.get('jp_context_review') and (not jp_only or not config.get('source_review_version') or not config.get('judge_model')):
        raise ValueError('JP context review requires source review and a local review model')
    if config.get('source_review_version')==3 and not jp_only: raise ValueError('Source review v3 is a transcription-only workflow')
    adaptive=config.get('adaptive_retry',{});alignment=config.get('jp_alignment',{})
    for options in (adaptive,alignment):
        if not isinstance(options,dict) or type(options.get('enabled',False)) is not bool:raise ValueError('Invalid audio refinement option')
        if options.get('enabled') and not jp_only:raise ValueError('Audio refinement requires Japanese-only mode')
    if adaptive.get('enabled'):
        aux=config.get('retry_asr',{}).get('auxiliary')
        if config.get('source_review_version')!=3 or not config.get('retry_asr',{}).get('enabled') or not aux:
            raise ValueError('Adaptive context requires source review v3 and auxiliary audio retries')
        if aux['engine'] not in (1,2,3) or Path(aux['model']).resolve()==Path(config['asr'][0]['model']).resolve():
            raise ValueError('Adaptive context requires distinct model weights')
        value=adaptive.get('max_targets',4)
        if type(value) is not int or not 1<=value<=12:raise ValueError('Invalid adaptive context budget')
    if alignment.get('enabled'):
        value=alignment.get('max_shift_ms',1500)
        if type(value) is not int or not 100<=value<=3000 or type(alignment.get('split',True)) is not bool:
            raise ValueError('Invalid final alignment limits')
    if config.get('asr_failure_policy','stop') not in {'stop','continue'}:
        raise ValueError('Nieprawidłowa polityka błędów ASR.')
    if type(config.get('decision_batch_size',1)) is not int or not 1<=config.get('decision_batch_size',1)<=6:
        raise ValueError('Partia decyzji musi zawierać 1–6 elementów.')
    if not 1 <= len(config['asr']) <= 4 or not jp_only and not 1 <= len(config['translations']) <= 4:
        raise ValueError('Wybierz od 1 do 4 transkrypcji i tłumaczeń.')
    if config['review'] not in {'rules','balanced','deep'}:
        raise ValueError('Nieznany poziom review.')
    if config.get('review_action','check') not in {'check','repair'}:
        raise ValueError('Nieznane działanie review.')
    if config.get('export_format','srt') not in {'srt','ass','ssa','txt'}:
        raise ValueError('Nieobsługiwany format eksportu.')
    if config['duration'] <= 0 or config['start'] < 0:
        raise ValueError('Nieprawidłowy zakres materiału.')
    if config['start'] + config['duration'] > config['media_duration']:
        raise ValueError('Zakres pipeline wykracza poza film.')
    signatures = [(s['engine'],s['model'],s['vad']) for s in config['asr']]
    if len(set(signatures)) != len(signatures):
        raise ValueError('Powielono identyczną transkrypcję. Wybierz inny model lub wariant VAD.')
    signatures = [(s['model'],s['variant']) for s in config['translations']]
    if len(set(signatures)) != len(signatures):
        raise ValueError('Wybierz różne profile lub modele dla wariantów tłumaczenia.')
    if any(s['variant'] not in range(len(VARIANTS)) for s in config['translations']):
        raise ValueError('Nieznany profil tłumaczenia.')
    ReviewSettings.load(config['review_settings'])


def asset_identities(config):
    settings = config['settings']
    paths = [config['media'],settings['ffmpeg']]
    for item in config['asr']:
        paths += [item['model'],settings['whisper_exe'] if item['engine']==0 else settings['crisp_exe']]
        if item['engine'] in (1,2,3) and item['vad']:
            paths.append(settings['crisp_vad'])
        if (item['engine']==1 or config.get('source_guard') and any(tag in Path(item['model']).name.lower() for tag in ('kotoba','anime-whisper'))) and settings['crisp_aligner']:
            paths.append(settings['crisp_aligner'])
    if config.get('transcription_only'):
        if config.get('jp_alignment',{}).get('enabled'):paths.append(settings['crisp_aligner'])
        auxiliary=config.get('retry_asr',{}).get('auxiliary')
        if config.get('retry_asr',{}).get('enabled'):
            for item in (auxiliary,config.get('retry_asr',{}).get('third')):
                if item:
                    paths.append(item['model'])
                    if item['engine'] in (1,2):paths.append(settings['crisp_aligner'])
        if config.get('jp_context_review') and config['backend']=='embedded':
            paths += [settings['llm_exe'],config['judge_model']]
            if config.get('llm_keep_loaded'): paths.append(str(Path(settings['llm_exe']).with_name('llama-server.exe')))
        return [file_identity(path) for path in sorted(set(paths))]
    if config['backend']=='embedded':
        paths += [settings['llm_exe'],config['judge_model']]
        if config.get('llm_keep_loaded'):
            paths.append(str(Path(settings['llm_exe']).with_name('llama-server.exe')))
        paths += [item['model'] for item in config['translations']]
    return [file_identity(path) for path in sorted(set(paths))]


def create_run(config, folder):
    validate_config(config)
    assets = asset_identities(config)
    folder = Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    state = {'version':1,'id':folder.name,'created':now(),'status':'pending','config':config,
             'assets':assets,'fingerprint':digest({'config':config,'assets':assets}),
             'stages':plan(config),'final_track':None,'warnings':0}
    atomic_text(folder/'manifest.json',json.dumps(state,ensure_ascii=False,indent=2))
    return state


def load_run(path):
    state = read_json_file(path)
    if state.get('version') != 1:
        raise ValueError('Nieobsługiwana wersja przebiegu pipeline.')
    validate_config(state['config'])
    if digest({'config':state['config'],'assets':state['assets']}) != state['fingerprint']:
        raise ValueError('Zmieniono konfigurację przebiegu. Utwórz nowy przebieg.')
    if asset_identities(state['config']) != state['assets']:
        raise ValueError('Film, model lub silnik zmienił się od rozpoczęcia. Utwórz nowy przebieg.')
    return state


def track_from(value):
    return Track(**{**value,'segments':[Segment(**s) for s in value['segments']]})


def clone_track(track, name, keep_translation=True):
    result = copy.deepcopy(track)
    result.id, result.name = uid(), name
    result.origin = {'pipeline_source':track.id,'created':now()}
    for old, new in zip(track.segments,result.segments):
        new.id,new.parents = uid(),[old.id]
        new.translation_key = ''
        if not keep_translation:
            new.translation,new.status = '','unchecked'
            new.review_status='unreviewed'
    return result


def choice_schema(ids, options):
    return {'type':'object','properties':{key:{'type':'string','enum':options} for key in ids},
            'required':list(ids),'additionalProperties':False}


def validate_choices(value, ids, options):
    if not isinstance(value,dict) or set(value) != set(ids) or any(v not in options for v in value.values()):
        raise ValueError('Model zmienił ID lub zwrócił nieprawidłowy wybór.')
    return value


def group_key(group):
    return digest([[s.id for s in group['a']],[s.id for s in group['b']]])[:24]


def normalize_asr_times(track,start,duration,media_duration):
    limit = min(media_duration,start+duration)
    for segment in track.segments:
        segment.start += start
        segment.end += start
        if segment.start < start and start-segment.start <= 100:
            segment.start = start
            segment.notes.append('Pipeline: początek przycięty do granicy fragmentu (≤100 ms)')
        if segment.end > limit and segment.end-limit <= 100:
            segment.end = limit
            segment.notes.append('Pipeline: koniec przycięty do granicy fragmentu (≤100 ms)')
        if segment.end<=segment.start or segment.start<start or segment.end>limit:
            raise ValueError('Nieprawidłowe czasy ASR; sprawdź log przed wznowieniem.')


def select_asr(groups, decisions, name):
    validate_choices(decisions,[group_key(g) for g in groups],['a','b','a?','b?'])
    segments = []
    for group in groups:
        key = group_key(group)
        decision = decisions[key]
        side = decision[0]
        if not group[side]:
            raise ValueError('Nie można wybrać pustego wariantu ASR.')
        disagreement = not group['a'] or not group['b'] or normalize(''.join(s.text for s in group['a'])) != normalize(''.join(s.text for s in group['b']))
        for source in group[side]:
            selected = copy.deepcopy(source)
            selected.id,selected.parents,selected.source = uid(),[source.id],'pipeline-asr-selection'
            if disagreement:
                selected.notes.append('Pipeline: rozbieżne ASR — wybór tekstowy, sprawdź odsłuch')
            if decision.endswith('?'):
                selected.notes.append('Pipeline: niepewny wybór ASR')
            selected.notes = list(dict.fromkeys(selected.notes))
            segments.append(selected)
    return Track(name,sorted(segments,key=lambda s:(s.start,s.end)),
                 origin={'type':'pipeline-asr-selection','decisions':decisions})


def compatible_asr_choices(groups,decisions):
    """Keep whole source cues; minimize changed decisions subject to no overlaps.

    Two states per temporal group suffice because each option fixes its end time.
    Return None when no complete path exists, rather than inventing timestamps.
    """
    states=[(0,-1,{})]
    for group in groups:
        key=group_key(group);following=[]
        for side in ('a','b'):
            cues=sorted(group[side],key=lambda s:(s.start,s.end))
            if not cues or any(a.end>b.start for a,b in zip(cues,cues[1:])): continue
            candidates=[(cost+(side!=decisions[key][0]),cues[-1].end,
                {**path,key:decisions[key] if side==decisions[key][0] else side+'?'})
                for cost,end,path in states if end<=cues[0].start]
            if candidates: following.append(min(candidates,key=lambda value:value[0]))
        if not following: return None
        states=following
    return min(states,key=lambda value:value[0])[2]


def variant_map(base, variant):
    result = {}
    for s in variant.segments:
        if len(s.parents)!=1 or s.parents[0] in result:
            raise ValueError('Nieprawidłowe pochodzenie wariantu EN.')
        result[s.parents[0]] = s
    if set(result) != {s.id for s in base.segments}:
        raise ValueError('Wariant EN nie odpowiada wszystkim napisom JP.')
    for source in base.segments:
        candidate = result[source.id]
        if (candidate.text,candidate.start,candidate.end) != (source.text,source.start,source.end):
            raise ValueError('Wariant tłumaczenia zmienił tekst JP lub czasy.')
    return result


def choose_english(base, variants, decisions):
    options = [chr(97+i) for i in range(len(variants))]
    validate_choices(decisions,[s.id for s in base.segments],options+[v+'?' for v in options])
    maps = [variant_map(base,t) for t in variants]
    result = clone_track(base,'Pipeline • wybrane EN',False)
    for source, target in zip(base.segments,result.segments):
        choice = decisions[source.id]
        candidate = maps[ord(choice[0])-ord('a')][source.id]
        if not candidate.translation.strip():
            raise ValueError('Wybrane tłumaczenie jest puste.')
        target.translation,target.status = candidate.translation,'machine'
        target.parents.append(candidate.id)
        if choice.endswith('?'):
            target.notes.append('Pipeline: niepewny wybór EN')
    result.origin['decisions'] = decisions
    return result


def format_final(track, settings, autosplit=False, repair_readability=False, media_duration=0):
    result = clone_track(track,'Pipeline • wynik końcowy')
    output = []
    for segment in result.segments:
        if repair_readability:
            segment.text=reflow_japanese(segment.text,settings.jp_line,settings.max_lines)
        proposed = reflow_english(segment.translation,settings.en_line)
        before, after = metrics(segment.translation,segment.end-segment.start),metrics(proposed,segment.end-segment.start)
        if after['lines'] <= settings.max_lines and after['line'] <= settings.en_line:
            segment.translation = proposed
        # Optional conservative sentence split, always marked as estimated timing.
        if autosplit and (segment.end-segment.start > settings.max_ms or before['chars'] > settings.en_line*settings.max_lines):
            jp_parts = re.findall(r'[^。！？!?]+[。！？!?]+\s*',segment.text)
            en_parts = re.findall(r'[^.!?]+[.!?]+\s*',segment.translation)
            proposal = split_proposal(segment,settings)
            if (len(jp_parts)==len(en_parts)==2 and ''.join(jp_parts)==segment.text and
                    ''.join(en_parts)==segment.translation and proposal):
                jp,en = len(jp_parts[0]),len(en_parts[0])
                # Allocate existing total time by both language workloads; never extend it.
                left = max(len(jp_parts[0])/settings.jp_cps,len(en_parts[0])/settings.en_cps)
                right = max(len(jp_parts[1])/settings.jp_cps,len(en_parts[1])/settings.en_cps)
                at = segment.start+round((segment.end-segment.start)*left/(left+right))
                if min(at-segment.start,segment.end-at) >= settings.min_ms:
                    parts = split_segment(segment,jp,at,en)
                    for part in parts:
                        part.parents = list(segment.parents)
                        part.notes = list(segment.notes)+['Pipeline: czas podziału szacowany — sprawdź odsłuch']
                    output.extend(parts)
                    continue
        output.append(segment)
    result.segments = output
    if repair_readability:
        ordered=sorted(result.segments,key=lambda s:(s.start,s.end))
        for i,segment in enumerate(ordered):
            if segment.status=='manual' or segment.review_status=='reviewed': continue
            needed=math.ceil(max(metrics(segment.text,1)['chars']/settings.jp_cps,
                                 metrics(segment.translation,1)['chars']/settings.en_cps)*1000)
            target=segment.start+min(settings.max_ms,max(settings.min_ms,needed))
            limit=segment.end+250
            if i+1<len(ordered): limit=min(limit,ordered[i+1].start-settings.gap_ms)
            if media_duration: limit=min(limit,media_duration)
            end=min(target,limit)
            if end>segment.end:
                delta=end-segment.end
                segment.end=end
                segment.translation_key='';segment.review_status='unreviewed'
                segment.notes.append(f'Pipeline: ekspozycja +{delta} ms w wolnej przerwie; nie jest to ponowne wyrównanie mowy')
    return result

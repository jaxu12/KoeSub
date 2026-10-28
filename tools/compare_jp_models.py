"""CUDA comparison on identical reference audio: baseline cached, auxiliaries decoded independently."""
from dataclasses import asdict
import json
from pathlib import Path
import time

from studio.core import atomic_text,uid
from studio.pipeline import create_run,load_run,track_from
from studio.pipeline_worker import PipelineRunner,pipeline_lock,read_json
from studio.storage import Settings
from tools.compare_reference import score_text


def main():
    root=Path('D:/models/datasets/subtitle-studio-references-v1')
    bank=read_json(root/'index.json')
    samples=[s for s in bank['samples'] if s['id'] in bank.get('evaluation_core',[v['id'] for v in bank['samples'][:5]])]
    settings=Settings.load()
    assert settings.crisp_gpu_backend=='cuda'
    output=root/'model-comparison';output.mkdir(exist_ok=True)
    models=[('kotoba',2,'Whisper / GGML','D:/models/whisper/ggml-kotoba-whisper-v2.0.bin'),
            ('anime',2,'Whisper / GGML','D:/models/whisper/ggml-anime-whisper.bin'),
            ('reazon',3,'ReazonSpeech / GGUF','D:/models/asr/reazonspeech-nemo-v2-f16.gguf')]
    results=[]
    for name,engine,kind,path in models:
        for sample in samples:
            print('CUDA',name,sample['id'],flush=True)
            pointer=output/f'{name}-{sample["id"]}.json'
            if pointer.exists():manifest=Path(read_json(pointer)['manifest'])
            else:
                duration=sample['source_range_ms'][1]-sample['source_range_ms'][0]
                config={'media':sample['audio'],'media_duration':duration,'start':0,'duration':duration,'audio_track':0,
                    'asr':[{'engine':engine,'kind':kind,'name':name,'model':path,'vad':True}],
                    'translations':[{'model':settings.llm_model,'variant':0}],'judge_model':settings.llm_model,
                    'backend':'embedded','review':'rules','review_settings':{},'settings':asdict(settings),
                    'prompt':'unused','export_srt':False,'autosplit':False,'source_guard':True,
                    'benchmark_scope':'asr-only','output_dir':str(output)}
                folder=Path(settings.cache_dir)/'pipeline'/uid();state=create_run(config,folder)
                state['stages']=[s for s in state['stages'] if s['id'] in ('audio','asr-0')]
                atomic_text(folder/'manifest.json',json.dumps(state,ensure_ascii=False,indent=2))
                manifest=folder/'manifest.json';atomic_text(pointer,json.dumps({'manifest':str(manifest)}))
            runner=PipelineRunner(manifest,lambda *a,**kw:None)
            try:
                with pipeline_lock(manifest.parent):
                    audio=runner.stage('audio',runner.audio)['audio']
                    decoded=runner.stage('asr-0',lambda f:runner.asr(f,runner.config['asr'][0],audio))
                    runner.state['status']='completed';runner.save()
                hypothesis='\n'.join(s.text for s in track_from(decoded['track']).segments)
                # Gold text is evaluated only after ASR. No prompt/hotwords are supplied.
                score=score_text(sample['reference_jp'],hypothesis)
                results.append({'model':name,'id':sample['id'],'split':sample['split'],'manifest':str(manifest),
                    'seconds':runner.state['stages'][1]['seconds'],'hypothesis_jp':hypothesis,**score})
            except (ValueError,RuntimeError) as exc:
                runner.state.update(status='failed',error=str(exc));runner.save()
                results.append({'model':name,'id':sample['id'],'split':sample['split'],'manifest':str(manifest),'error':str(exc)})
            atomic_text(output/'results.json',json.dumps({'scope':'Same five community-SRT clips, CUDA only. No new training.',
                'results':results},ensure_ascii=False,indent=2))
    for name,_,_,_ in models:
        values=[x for x in results if x['model']==name and 'cer' in x]
        chars=sum(x['reference_characters'] for x in values);edits=sum(x['edit_distance'] for x in values)
        print(name,'clips',len(values),'CER',edits/chars if chars else None,'seconds',sum(x['seconds'] for x in values),flush=True)


if __name__=='__main__':main()

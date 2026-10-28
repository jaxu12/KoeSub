"""Generate real ASR/review examples and score a local reference bank. Never pass gold text to ASR."""
from dataclasses import asdict
import json
from pathlib import Path

from studio.core import atomic_text,uid
from studio.pipeline import create_run,track_from,load_run
from studio.pipeline_worker import run_pipeline,read_json
from studio.storage import Settings
from tools.compare_reference import score_text


def main():
    root=Path('D:/models/datasets/subtitle-studio-references-v1')
    index=read_json(root/'index.json');settings=Settings.load()
    assert settings.crisp_gpu_backend=='cuda'
    model=Path('D:/models/whisper/ggml-large-v3.bin')
    output=root/'evaluation';output.mkdir(exist_ok=True)
    evaluations=[];real_examples=[]
    for sample in [s for s in index['samples'] if s['id'] in index.get('evaluation_core',[v['id'] for v in index['samples'][:5]])]:
        pointer=output/(sample['id']+'.json')
        if pointer.exists():manifest=Path(read_json(pointer)['manifest'])
        else:
            duration=sample['source_range_ms'][1]-sample['source_range_ms'][0]
            config={'transcription_only':True,'media':sample['audio'],'media_duration':duration,'audio_track':0,
                'start':0,'duration':duration,'asr':[{'engine':2,'model':str(model),'name':model.name,'kind':'Whisper / GGML','vad':True}],
                'translations':[],'judge_model':'','backend':'embedded','review':'rules','review_settings':{},
                'settings':asdict(settings),'prompt':'unused','autosplit':False,'readability_repair':False,
                'source_guard':True,'retry_asr':{'enabled':False},'export_srt':True,
                'output_dir':str(output/sample['id'])}
            folder=Path(settings.cache_dir)/'pipeline'/uid();create_run(config,folder)
            manifest=folder/'manifest.json';atomic_text(pointer,json.dumps({'manifest':str(manifest)}))
        print('ASR reference:',sample['id'],sample['split'],flush=True)
        run_pipeline(manifest,lambda *a,**kw:None)
        state=load_run(manifest)
        track=track_from(read_json(manifest.parent/'asr-0/result.json')['track'])
        hypothesis='\n'.join(s.text for s in track.segments)
        # Reference text is used only after decoding has finished.
        score=score_text(sample['reference_jp'],hypothesis)
        evaluations.append({'id':sample['id'],'split':sample['split'],'manifest':str(manifest),
                            'hypothesis_jp':hypothesis,**score})
        real_examples.append({'id':sample['id']+'-real-asr','split':sample['split'],'audio':sample['audio'],
            'hypothesis_jp':hypothesis,'reference_jp':sample['reference_jp'],'kind':'real-large-v3-output',
            'expected_action':'keep' if score['edit_distance']==0 else 'label-audit-required',
            'human_audio_verified':False,'training_ready':False,
            'note':'Text mismatch can include orthography, not only recognition errors. Review the label before training.'})
    totals={}
    for split in ('development','control'):
        values=[r for r in evaluations if r['split']==split]
        edits=sum(r['edit_distance'] for r in values);chars=sum(r['reference_characters'] for r in values)
        totals[split]={'clips':len(values),'edit_distance':edits,'reference_characters':chars,'cer':edits/chars}
    atomic_text(output/'scores.json',json.dumps({'model':str(model),'device':'cuda','splits':totals,'samples':evaluations,
        'scope':'Differences from existing community SRT; not a human-audio-verified gold standard. No fine-tuning performed.'},ensure_ascii=False,indent=2))
    atomic_text(root/'review_real_asr_examples.jsonl','\n'.join(json.dumps(r,ensure_ascii=False) for r in real_examples)+'\n')
    from tools.prepare_jp_references import write_review_views
    write_review_views(root)
    print(json.dumps(totals),flush=True)


if __name__=='__main__':main()

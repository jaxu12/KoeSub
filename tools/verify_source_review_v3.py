"""Fresh CUDA movie integration and matched single-clip/grouped-CLI timing checks.

No reference transcript is ever passed to the production pipeline. Movie output
has no complete reference, so successful integration is not a quality score.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
from pathlib import Path
import time
import sys

from studio.core import Project,ProjectStore,now
from studio.pipeline import create_run,load_run,track_from,digest
from studio.pipeline_worker import PipelineRunner,read_json,write_json,run_pipeline
from studio.source_review_v3 import decode_batch
from studio.storage import Settings
from tools.benchmark_asr_fusion import MODELS,config_for,audio_input,cuda_evidence
from tools.gpu_telemetry import GpuTelemetry
from tools.verify_pipeline import audit_result
from tools.compare_reference import score_text,normalize_text


def event(kind,**data):
    if kind=='phase':print(data['message'],flush=True)


def movie(output,settings):
    config=deepcopy(load_run('D:/models/.cache/pipeline/841464cecf4343fa9f1217ed29d341fc/manifest.json')['config'])
    config.update(settings=asdict(settings),source_review_version=3,jp_context_review=True,backend='embedded',
        judge_model=settings.llm_model,llm_keep_loaded=True,output_dir=str(output/'exports'),
        retry_asr={'enabled':True,'scan_first':True,'auxiliary':{k:v for k,v in MODELS[1].items() if k!='key'},
            'third':{k:v for k,v in MODELS[2].items() if k!='key'},'third_max_targets':6,
            'max_targets':12,'padding_ms':3000,'max_window_ms':30000,'batch_retries':True})
    folder=output/'movie';manifest=folder/'manifest.json'
    fresh=not manifest.exists()
    if fresh:create_run(config,folder)
    elif load_run(manifest)['config']!=config:raise ValueError('Changed movie configuration')
    telemetry=GpuTelemetry(manifest,output/'gpu-telemetry.json');telemetry.start();started=time.monotonic()
    try:run_pipeline(manifest,event)
    finally:telemetry.close()
    wall=time.monotonic()-started;state=audit_result(manifest)
    base=read_json(folder/'asr-0/result.json')['track'];final=read_json(folder/'jp-layout/result.json')['track']
    assert [(s['start'],s['end']) for s in base['segments']]==[(s['start'],s['end']) for s in final['segments']]
    logs=list(folder.glob('asr-*/engine.log'))+list(folder.glob('asr-retry/batch-*/engine.log'))
    evidence={str(p):cuda_evidence(p.read_text('utf8',errors='replace')) for p in logs}
    if not all(evidence.values()) or not evidence:raise ValueError('Missing actual CUDA evidence')
    summary={'fresh_asr_and_review':fresh,'wall_seconds_this_invocation':round(wall,3),'stages':state['stages'],
        'third_windows':state.get('jp_third_windows',0),'changed_phrases':state.get('jp_review_changes',0),
        'changed_cues':state.get('jp_review_changed_cues',0),'context_flags':state.get('jp_context_flags',0),
        'cues':len(final['segments']),'cuda_logs':evidence,'asr_failures':state.get('asr_failures',[]),
        'batches':[read_json(p) for p in folder.glob('asr-retry/batch-*/batch.json')],
        'scope':'Fresh native inference unless resumed; audio preprocessing cache may be reused. No complete movie reference; no CER claim.'}
    write_json(output/'movie-summary.json',summary)
    save_ui(output,manifest)
    print('MOVIE', {k:summary[k] for k in ('wall_seconds_this_invocation','third_windows','changed_phrases','changed_cues','context_flags')},flush=True)


def save_ui(output,manifest):
    folder=manifest.parent;state=load_run(manifest);config=state['config']
    project=Project(name='KoeSub • source review v3',media=config['media'],duration=config['media_duration'],review_settings=config['review_settings'])
    stages={}
    for key in ('asr-0','asr-scan','asr-retry','jp-review','jp-context','jp-layout'):
        value=read_json(folder/key/'result.json');project.add_track(track_from(value['track']));stages[key]=project.active.id
    project.active_track=state['final_track'];project.jobs=[{'id':state['id'],'type':'pipeline','manifest':str(manifest),
        'status':state['status'],'created':now(),'stage_tracks':stages,'track_hashes':{}}]
    path=output/'ui/projects'/project.active.id/'project.sqlite'
    if not (output/'ui/last_project.json').exists():
        ProjectStore(path).save(project,'source review v3 benchmark');write_json(output/'ui/last_project.json',{'path':str(path)})


def context_replay(output,settings,source):
    previous=load_run(source);config=deepcopy(previous['config'])
    config.update(output_dir=str(output/'exports'),context_replay_source=str(source))
    folder=output/'movie';manifest=folder/'manifest.json'
    if manifest.exists():raise ValueError('Use a new directory for a context-only replay')
    state=create_run(config,folder)
    for stage in state['stages']:
        if stage['id']=='jp-context':break
        original=next(s for s in previous['stages'] if s['id']==stage['id'])
        if original['status']!='completed':raise ValueError('Incomplete source stage')
        value=read_json(original['artifact'])
        if digest(value)!=original['digest']:raise ValueError('Changed source stage')
        target=folder/stage['id']/'result.json';write_json(target,value)
        stage.update(status='completed',digest=digest(value),artifact=str(target),seconds=0,
                     replayed_from=original['artifact'],original_seconds=original.get('seconds',0))
    write_json(manifest,state);started=time.monotonic()
    telemetry=GpuTelemetry(manifest,output/'gpu-telemetry.json');telemetry.start()
    try:run_pipeline(manifest,event)
    finally:telemetry.close()
    state=audit_result(manifest);result=read_json(folder/'jp-context/result.json')
    summary={'wall_seconds':round(time.monotonic()-started,3),'flags':len(result['flags']),
        'statuses':{status:sum(v['status']==status for v in result['decisions'].values()) for status in ('ok','suspicious','name','uncertain')},
        'source_manifest':str(source),'manifest':str(manifest),'scope':'New CUDA context inference over verified saved ASR/review; not a fresh ASR/full-pipeline speed measurement'}
    write_json(output/'context-summary.json',summary);save_ui(output,manifest);print('CONTEXT REPLAY',summary,flush=True)


def batch_check(output,settings):
    samples=[audio_input(s) for s in read_json('D:/models/datasets/koesub-fleurs-ja-v1/index.json')['samples'][:3]]
    rows=[]
    for model in MODELS[:3]:
        directory=output/model['key'];folder=directory/'runner';manifest=folder/'manifest.json'
        if manifest.exists():raise ValueError('Use a fresh directory for native timing measurements')
        config=config_for(samples[0],model,settings,directory/'exports')
        config['duration']=config['media_duration']=max(s['source_range_ms'][1]-s['source_range_ms'][0] for s in samples)
        create_run(config,folder);runner=PipelineRunner(manifest,event);jobs=[]
        for sample in samples:
            jobs.append({'audio':Path(sample['audio']),'start':0,'end':sample['source_range_ms'][1]-sample['source_range_ms'][0],
                         'folder':directory/'grouped'/sample['id']})
        grouped=decode_batch(runner,directory/'batch',model,jobs)
        singles=[];started=time.monotonic()
        for sample,job in zip(samples,jobs):
            target=directory/'single'/sample['id'];target.mkdir(parents=True)
            singles.append(runner.retry_decode(target,model,job['audio'],0,job['end']))
        single_seconds=round(time.monotonic()-started,3)
        surface=lambda v:[(s['start'],s['end'],s['text']) for s in v['track']['segments']]
        confidence=lambda v:[v.get('confidence',{}).get(s['id']) for s in v['track']['segments']]
        identical=[surface(a)==surface(b) and confidence(a)==confidence(b) for a,b in zip(grouped,singles)]
        logs=[directory/'batch/engine.log',*list((directory/'single').glob('*/engine.log'))]
        evidence={str(p):cuda_evidence(p.read_text('utf8',errors='replace')) for p in logs}
        if not all(evidence.values()):raise ValueError('Missing CUDA evidence')
        row={'model':model['key'],'clips':len(samples),'grouped_seconds':read_json(directory/'batch/batch.json')['seconds'],
            'single_seconds':single_seconds,'exact_text_times_confidence_match':identical,'cuda_logs':evidence,
            'scope':'Fresh inference; one grouped pass then one single-clip pass, no randomized repeated speed claim; development clips'}
        write_json(directory/'results.json',{'summary':row,'grouped':grouped,'single':singles});rows.append(row)
        write_json(output/'batch-summary.json',rows);print('BATCH',row,flush=True)


def evaluate_batch(output,settings):
    samples=read_json('D:/models/datasets/koesub-fleurs-ja-v1/index.json')['samples'][:3];rows=[]
    for model in MODELS[:3]:
        values=read_json(output/model['key']/'results.json')
        for sample,grouped,single in zip(samples,values['grouped'],values['single']):
            text=lambda v:''.join(s['text'] for s in v['track']['segments'])
            rows.append({'id':sample['id'],'model':model['key'],
                'normalized_text_equal':normalize_text(text(grouped))==normalize_text(text(single)),
                'grouped':score_text(sample['reference_jp'],text(grouped)),
                'single':score_text(sample['reference_jp'],text(single))})
    write_json(output/'batch-reference-evaluation.json',{'rows':rows,
        'scope':'Post-inference evaluation of nine development cases; published read-speech references, not independently audio-audited; no movie-quality claim'})
    print('Normalized batch/single equality:',[r['normalized_text_equal'] for r in rows],flush=True)


def references(output,settings):
    index=read_json('D:/models/datasets/koesub-fleurs-ja-v3/index.json')
    inputs=[audio_input(s) for s in index['samples']]
    protocol={'inputs':inputs,'selection':'FLEURS Japanese validation rows 10–14, fixed before inference',
              'context':True,'third_limit':3,'retry_limit':6}
    path=output/'inputs.json'
    if path.exists() and read_json(path)!=protocol:raise ValueError('Changed reference experiment')
    write_json(path,protocol);records=[]
    for sample in inputs:
        folder=output/sample['id'];manifest=folder/'manifest.json'
        config=config_for(sample,MODELS[0],settings,folder/'exports',True)
        config.update(source_review_version=3,jp_context_review=True,backend='embedded',judge_model=settings.llm_model,
            llm_keep_loaded=True,retry_asr={'enabled':True,'scan_first':True,'batch_retries':True,
            'auxiliary':{k:v for k,v in MODELS[1].items() if k!='key'},'third':{k:v for k,v in MODELS[2].items() if k!='key'},
            'third_max_targets':3,'max_targets':6,'padding_ms':3000,'max_window_ms':30000})
        fresh=not manifest.exists()
        if fresh:create_run(config,folder)
        elif load_run(manifest)['config']!=config:raise ValueError('Changed reference configuration')
        print('REFERENCE INPUT',sample['id'],flush=True);started=time.monotonic()
        run_pipeline(manifest,event);state=audit_result(manifest)
        record={'id':sample['id'],'manifest':str(manifest),'fresh':fresh,'wall_seconds_this_invocation':round(time.monotonic()-started,3),
            'changes':state.get('jp_review_changes',0),'third_windows':state.get('jp_third_windows',0),
            'context_flags':state.get('jp_context_flags',0),'failures':state.get('asr_failures',[])}
        records.append(record);write_json(output/'collected.json',records)
    # Separate post-inference scoring. Production only received audio_input's
    # allowlisted paths/ranges/hashes and hypotheses generated from that audio.
    for record,sample in zip(records,index['samples']):
        folder=Path(record['manifest']).parent
        for variant,key in [('baseline','asr-0'),('review','jp-layout')]:
            value=read_json(folder/key/'result.json')['track']
            record[variant]=score_text(sample['reference_jp'],''.join(s['text'] for s in value['segments']))
    totals={}
    for variant in ('baseline','review'):
        errors=sum(r[variant]['edit_distance'] for r in records);chars=sum(r[variant]['reference_characters'] for r in records)
        totals[variant]={'edit_distance':errors,'characters':chars,'cer':errors/chars}
    write_json(output/'reference-summary.json',{'records':records,'totals':totals,'source':index['source'],
        'revision':index['revision'],'scope':'Five fixed additional read-speech clips; references not independently audio-audited. No movie or training-contamination claim.'})
    print('REFERENCE TOTALS',totals,flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=('movie','batch','batch-eval','references','context-replay'),required=True)
    parser.add_argument('--source-manifest',type=Path);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);settings=Settings.load()
    if settings.crisp_gpu_backend!='cuda' or settings.llm_device!='cuda':raise ValueError('Explicit CUDA required')
    policy={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path('studio')/n for n in
        ('source_review_v3.py','asr_review.py','jp_context_review.py','pipeline_worker.py','adapters.py'))}
    path=args.output/'policy.json'
    if args.mode!='batch-eval':
        if path.exists() and read_json(path)!=policy:raise ValueError('Changed frozen policy; use another directory')
        write_json(path,policy)
    if args.mode=='context-replay':
        if not args.source_manifest:parser.error('--source-manifest is required')
        context_replay(args.output,settings,args.source_manifest)
    else:{'movie':movie,'batch':batch_check,'batch-eval':evaluate_batch,'references':references}[args.mode](args.output,settings)


if __name__=='__main__':main()

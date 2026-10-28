"""CUDA verification of adaptive audio and final alignment; references score only afterward."""
import argparse
from copy import deepcopy
from pathlib import Path
import hashlib
import sys
import time

from studio.pipeline import create_run,load_run,track_from,digest
from studio.pipeline_worker import read_json,write_json,run_pipeline
from studio.review import metrics,ReviewSettings
from studio.core import Project,ProjectStore,now,Track,Segment
from dataclasses import asdict
from tools.gpu_telemetry import GpuTelemetry
from tools.benchmark_asr_fusion import cuda_evidence
from tools.compare_reference import score_text
from tools.verify_pipeline import audit_result


def event(kind,**data):
    if kind=='phase':print(data['message'],flush=True)


def merged_layout_probe(source,output):
    from studio.audio_alignment import align_final
    from studio.pipeline_worker import PipelineRunner
    source=Path(source);before=source.read_bytes();runner=PipelineRunner(source,event)
    runner.config=deepcopy(runner.config);runner.config['jp_alignment']={'enabled':True,'split':True,'max_shift_ms':1500}
    runner.current={'id':'jp-align'}
    original=track_from(read_json(source.parent/'jp-layout/result.json')['track'])
    cue=Segment(original.segments[0].start,original.segments[-1].end,''.join(s.text for s in original.segments),
        status='machine',source='verification-merged-ASR-layout',parents=[s.id for s in original.segments])
    base=Track('Merged real ASR layout regression',[cue]);output.mkdir(parents=True,exist_ok=True)
    audio=read_json(source.parent/'audio/result.json')['audio'];started=time.monotonic()
    result=align_final(runner,output,base,audio)
    assert ''.join(s['text'] for s in result['track']['segments'])==cue.text
    assert result['split_cues']>0
    assert source.read_bytes()==before
    write_json(output/'verification.json',{'source_manifest':str(source),'input':asdict(base),'result':result,
        'seconds':round(time.monotonic()-started,3),'scope':'Fresh CUDA alignment of a deliberately merged real ASR layout; not a transcription-quality or gold-timing test'})
    print('REAL LAYOUT SPLIT',len(result['track']['segments']),flush=True)


def verify(source,output,reuse):
    source=Path(source);original=load_run(source);config=deepcopy(original['config'])
    config.update(output_dir=str(output/'exports'),adaptive_retry={'enabled':True,'max_targets':4},
        jp_alignment={'enabled':True,'split':True,'max_shift_ms':1500},audio_refinement_source=str(source))
    if config['settings']['crisp_gpu_backend']!='cuda':raise ValueError('Explicit CUDA is required')
    folder=output/'run';manifest=folder/'manifest.json';fresh=not manifest.exists()
    if fresh:
        state=create_run(config,folder)
        if reuse:
            for stage in state['stages']:
                if stage['id'] in ('jp-adaptive','jp-align','jp-layout','jp-export'):continue
                prior=next(s for s in original['stages'] if s['id']==stage['id'])
                value=read_json(prior['artifact'])
                if prior['status']!='completed' or digest(value)!=prior['digest']:raise ValueError('Invalid cached upstream stage')
                target=folder/stage['id']/'result.json';write_json(target,value)
                stage.update(status='completed',artifact=str(target),digest=digest(value),seconds=0,
                    original_seconds=prior.get('seconds',0),replayed_from=prior['artifact'])
            write_json(manifest,state)
    elif load_run(manifest)['config']!=config:raise ValueError('Changed verification configuration')
    telemetry=GpuTelemetry(manifest,output/'gpu-telemetry.json',capture_processes=True);telemetry.start();started=time.monotonic()
    try:run_pipeline(manifest,event)
    finally:gpu=telemetry.close()
    wall=time.monotonic()-started;state=audit_result(manifest)
    aligned=read_json(folder/'jp-align/result.json');adapted=read_json(folder/'jp-adaptive/result.json')
    incoming=track_from(adapted['track']);final=track_from(read_json(folder/'jp-layout/result.json')['track'])
    assert ''.join(s.text for s in incoming.segments).replace('\n','')==''.join(s.text for s in final.segments).replace('\n','')
    assert all(a.end<=b.start for a,b in zip(final.segments,final.segments[1:]))
    for record in aligned['records']:
        before=record['before'];limit=max(ReviewSettings.load(config['review_settings']).jp_cps,
            metrics(before['text'],before['end']-before['start'])['cps'])
        assert all(metrics(c['text'],c['end']-c['start'])['cps']<=limit+.001 for c in record['after'])
    processes=[read_json(p)['pid'] for p in (folder/'jp-align').glob('block-*/engine-process.json')]
    proof=[p for p in gpu.get('compute_processes',[]) if p['pid'] in processes]
    if processes and not proof:raise ValueError('Final aligner PID not observed on NVIDIA compute device')
    logs=list((folder/'jp-adaptive').glob('batch-*/engine.log'))
    if not all(cuda_evidence(p.read_text('utf8',errors='replace')) for p in logs):raise ValueError('Missing adaptive ASR CUDA evidence')
    def technical(track):
        rules=ReviewSettings.load(config['review_settings'])
        return {'cues':len(track.segments),'overlong':sum(s.end-s.start>rules.max_ms for s in track.segments),
            'too_many_characters':sum(len(s.text.replace('\n',''))>rules.jp_line*rules.max_lines for s in track.segments),
            'fast_reading':sum(metrics(s.text,s.end-s.start)['cps']>rules.jp_cps for s in track.segments)}
    summary={'manifest':str(manifest),'wall_seconds_this_invocation':round(wall,3),'fresh_invocation':fresh,'upstream_replayed':reuse,
        'adaptive_targets':len(adapted['windows']),'adaptive_changes':len(adapted['changes']),
        'retimed_cues':aligned['retimed_cues'],'split_cues':aligned['split_cues'],'before':technical(incoming),'after':technical(final),
        'alignment_pids':processes,'nvidia_process_samples':len(proof),'stages':state['stages'],
        'scope':'Integration and technical timing metrics; no independent word-timing reference or semantic accuracy claim'}
    sessions=[read_json(p) for p in (folder/'native-sessions').glob('*/session.json')]
    engines=[read_json(p) for p in (folder/'jp-adaptive').glob('batch-*/engine-process.json')]
    if sessions and engines:
        assert max(s['closed'] for s in sessions)<=min(e['started'] for e in engines)
        summary['owned_llm_released_before_adaptive']=True
    write_json(output/'summary.json',summary)
    project=Project(name='KoeSub • adaptive audio and alignment',media=config['media'],duration=config['media_duration'],review_settings=config['review_settings'])
    stage_tracks={}
    for stage in state['stages']:
        value=read_json(stage['artifact'])
        if 'track' in value:
            track=track_from(value['track']);project.add_track(track);stage_tracks[stage['id']]=track.id
    project.active_track=state['final_track'];project.jobs=[{'type':'pipeline','id':state['id'],'created':now(),
        'manifest':str(manifest),'status':state['status'],'stage_tracks':stage_tracks,'track_hashes':{}}]
    pointer=output/'ui/last_project.json'
    if not pointer.exists():
        path=output/'ui/projects'/project.active.id/'project.sqlite';ProjectStore(path).save(project,'audio refinement verification')
        write_json(pointer,{'path':str(path)})
    print('REFINEMENT', {k:summary[k] for k in ('wall_seconds_this_invocation','adaptive_targets','adaptive_changes','retimed_cues','split_cues')},flush=True)
    return summary


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-manifest',type=Path);parser.add_argument('--reuse-upstream',action='store_true')
    parser.add_argument('--references',action='store_true');parser.add_argument('--merged-layout',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    policy={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path('studio')/name for name in
        ('adaptive_asr.py','audio_alignment.py','audio_boundaries.py','asr_review.py','source_review_v3.py','pipeline_worker.py'))}
    protocol=args.output/'policy.json'
    if protocol.exists() and read_json(protocol)!=policy:raise ValueError('Changed frozen policy; use a new output directory')
    write_json(protocol,policy)
    if args.merged_layout:
        if not args.source_manifest:parser.error('Choose a source manifest for the layout probe')
        merged_layout_probe(args.source_manifest,args.output);return
    if args.references:
        index=read_json('D:/models/datasets/koesub-fleurs-ja-v3/index.json');records=[]
        for sample in index['samples']:
            source=Path('D:/models/.cache/verification-source-v3-references')/sample['id']/'manifest.json'
            result=verify(source,args.output/sample['id'],True);result['id']=sample['id'];records.append(result)
        # Labels are accessed only after all production runs finish.
        for sample,result in zip(index['samples'],records):
            folder=Path(result['manifest']).parent
            for variant,key in [('baseline','asr-0'),('review','jp-layout')]:
                value=read_json(folder/key/'result.json')['track']
                result[variant]=score_text(sample['reference_jp'],''.join(s['text'] for s in value['segments']))
        totals={}
        for variant in ('baseline','review'):
            errors=sum(r[variant]['edit_distance'] for r in records);chars=sum(r[variant]['reference_characters'] for r in records)
            totals[variant]={'edit_distance':errors,'characters':chars,'cer':errors/chars}
        write_json(args.output/'reference-summary.json',{'records':records,'totals':totals})
        print('REFERENCE TOTALS',totals,flush=True)
    else:
        if not args.source_manifest:parser.error('Choose --source-manifest or --references')
        verify(args.source_manifest,args.output,args.reuse_upstream)


if __name__=='__main__':main()

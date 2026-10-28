"""Compare frozen source-review v1/v2 on inspected development and unseen clip sets."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path
import time

from studio.core import atomic_text, now
from studio.pipeline import create_run,digest,load_run,track_from
from studio.pipeline_worker import read_json,write_json,run_pipeline
from studio.storage import Settings
from studio.asr_retry import retry_windows,suspects
from studio.asr_disagreement import disagreement_targets
from tools.benchmark_asr_fusion import MODELS,audio_input,collect_asr,collect_review,config_for,edit_effects,cuda_evidence
from tools.compare_reference import score_text
from tools.gpu_telemetry import GpuTelemetry


def replay_aware_cost(attempts,folder,stage_seconds):
    """Restore reused native costs rather than presenting cache replay as speedup."""
    total=sum(a.get('seconds',0) for a in attempts)
    local=sum(a.get('seconds',0) for a in attempts if not a.get('reused_from') and Path(a['directory']).resolve().is_relative_to(Path(folder).resolve()))
    return total+max(0,stage_seconds-local)


def scan_cost(baseline,auxiliary,result):
    manifest=Path(result['manifest']);state=load_run(manifest)
    stage=next(s for s in state['stages'] if s['id']=='asr-retry');retry=read_json(stage['artifact'])
    if digest(retry)!=stage['digest']:raise ValueError('Changed timing source')
    attempts=[a for w in retry['windows'] for a in w['attempts']]
    elapsed=sum(s.get('seconds',0) for s in state['stages'])
    return baseline['original_seconds']+auxiliary['original_seconds']+replay_aware_cost(attempts,manifest.parent,elapsed)


def run_v2(sample,baseline,auxiliary,settings,output,reuse_manifest=None):
    if not baseline['usable']:return {'usable':False,'error':'No accepted baseline'}
    folder=output/'runs'/(sample['id']+'-scan-v2');manifest=folder/'manifest.json'
    if not manifest.exists():
        config=config_for(sample,MODELS[0],settings,output/'exports'/folder.name,True)
        config.update(source_review_version=2,asr_failure_policy='continue',retry_asr={'enabled':True,'scan_first':True,
            'padding_ms':3000,'max_window_ms':30000,'max_targets':12,
            'auxiliary':{k:v for k,v in MODELS[1].items() if k!='key'}})
        state=create_run(config,folder)
        old=load_run(baseline['manifest'])
        seeds={key:next(s for s in old['stages'] if s['id']==key) for key in ('audio','asr-0')}
        for stage in state['stages']:
            key=stage['id'];value=None;source=None
            if key in seeds:
                source=seeds[key];value=read_json(source['artifact'])
                if digest(value)!=source['digest']:raise ValueError('Changed baseline seed')
            elif key=='asr-scan':
                source=next(s for s in load_run(auxiliary['manifest'])['stages'] if s['id']=='asr-0')
                if auxiliary['usable']:
                    value=deepcopy(auxiliary['decoded']);value['native_directory']=str(Path(auxiliary['manifest']).parent/'asr-0')
                else:
                    value={'usable':False,'asr_failure':{'name':MODELS[1]['name'],'model':MODELS[1]['model'],
                        'stage':'asr-scan','reason':auxiliary['error'],'log':str(Path(auxiliary['manifest']).parent/'asr-0/engine.log')}}
            if value is not None:
                target=folder/key/'result.json';write_json(target,value)
                stage.update(status='completed',artifact=str(target),digest=digest(value),seconds=0,
                    reused_from=source.get('artifact',str(Path(auxiliary['manifest']).parent/'asr-0')),
                    reused_seconds=source.get('seconds',0))
        write_json(manifest,state)
        if reuse_manifest:
            previous=load_run(reuse_manifest)
            for key in ('media','start','duration','asr','retry_asr','settings'):
                if previous['config'][key]!=config[key]:raise ValueError('Window cache configuration mismatch')
            old_stage=next(s for s in previous['stages'] if s['id']=='asr-retry')
            cached=read_json(old_stage['artifact'])
            if digest(cached)!=old_stage['digest']:raise ValueError('Changed source retry cache')
            base=track_from(baseline['decoded']['track']);confidence=baseline['decoded'].get('confidence',{})
            scan=track_from(auxiliary['decoded']['track']) if auxiliary['usable'] else None
            targets=disagreement_targets(base,scan) if scan else []
            expected,_=retry_windows(base,confidence,0,config['duration'],additional_targets=targets)
            expected_ids={w['id'] for w in expected};primary={s['id'] for s in suspects(base,confidence)}
            for window in cached['windows']:
                if window['id'] not in expected_ids:continue
                for index,attempt in enumerate(window['attempts']):
                    if index==1 and attempt.get('reused_from')=='asr-scan' and primary.intersection(window['cue_ids']):continue
                    source=Path(reuse_manifest).parent/'asr-retry'/window['id']/f'attempt-{index}/result.json'
                    saved=read_json(source)
                    if saved['digest']!=digest(saved['result']) or saved['result']!=attempt:raise ValueError('Changed cached attempt')
                    write_json(folder/'asr-retry'/window['id']/f'attempt-{index}/result.json',saved)
    telemetry=GpuTelemetry(manifest,folder/'gpu-telemetry.json');telemetry.start()
    try:run_pipeline(manifest,lambda *a,**kw:None)
    finally:telemetry.close()
    state=load_run(manifest);review=read_json(folder/'jp-review/result.json')
    final=track_from(read_json(folder/'jp-layout/result.json')['track']);base=track_from(baseline['decoded']['track'])
    if [(s.start,s.end) for s in base.segments]!=[(s.start,s.end) for s in final.segments]:raise AssertionError('Retimed baseline')
    retry=read_json(folder/'asr-retry/result.json')
    for window in retry['windows']:
        for attempt in window['attempts']:
            log=(Path(attempt['directory'])/'engine.log').read_text(encoding='utf-8',errors='replace')
            if not cuda_evidence(log):raise ValueError('Missing CUDA retry evidence')
    result={'usable':True,'manifest':str(manifest),'hypothesis_jp':'\n'.join(s.text for s in final.segments),'review':review,
        'original_seconds':baseline['original_seconds']+auxiliary['original_seconds']+sum(s.get('seconds',0) for s in state['stages']),
        'retry_windows':len(retry['windows']),'disagreements':len(retry.get('disagreements',[])),
        'reused_auxiliary_attempts':sum(a.get('reused_from')=='asr-scan' for w in retry['windows'] for a in w['attempts'])}
    result['original_seconds']=scan_cost(baseline,auxiliary,result)
    return result


def evaluate(samples,records):
    rows=[]
    for sample,record in zip(samples,records):
        if sample['id']!=record['id']:raise ValueError('Changed case order')
        ref=sample['reference_jp'];row={'id':sample['id'],'cohort':record['cohort'],'corpus':sample.get('corpus','mcdc')}
        for variant in ('baseline','control','scan'):
            value=record[variant]
            if value['usable']:
                seconds=scan_cost(record['baseline'],record['auxiliary'],value) if variant=='scan' else value['original_seconds']
                row[variant]={**score_text(ref,value['hypothesis_jp']),
                    'seconds':seconds+(record['baseline']['original_seconds'] if variant=='control' else 0)}
                if variant=='scan':row['edit_effects']=edit_effects(ref,record['baseline'],value)
        row.update(retry_windows=record['scan'].get('retry_windows',0),disagreements=record['scan'].get('disagreements',0),
                   reused_auxiliary_attempts=record['scan'].get('reused_auxiliary_attempts',0))
        rows.append(row)
    summary={}
    for cohort in ('development','holdout'):
        group=[r for r in rows if r['cohort']==cohort]
        if not group:continue
        values={}
        for variant in ('baseline','control','scan'):
            scored=[r[variant] for r in group if variant in r]
            edits=sum(s['edit_distance'] for s in scored);chars=sum(s['reference_characters'] for s in scored)
            values[variant]={'cases':len(scored),'total_cases':len(group),'edits':edits,'characters':chars,
                'cer':edits/chars if chars and len(scored)==len(group) else None,'seconds':round(sum(s['seconds'] for s in scored),3)}
        effects=[e for row in group for e in row.get('edit_effects',[])]
        summary[cohort]={'scores':values,'phrase_effects':{kind:sum(e['effect']==kind for e in effects) for kind in ('helpful','harmful','neutral')},
            'disagreements':sum(r['disagreements'] for r in group),'retry_windows':sum(r['retry_windows'] for r in group),
            'reused_auxiliary_attempts':sum(r['reused_auxiliary_attempts'] for r in group),
            'improved_cases':sum(r['scan']['edit_distance']<r['baseline']['edit_distance'] for r in group if 'scan'in r and 'baseline'in r),
            'harmed_cases':sum(r['scan']['edit_distance']>r['baseline']['edit_distance'] for r in group if 'scan'in r and 'baseline'in r)}
    return rows,summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('D:/models/.cache/verification-asr-scan-v2'))
    parser.add_argument('--cohort',choices=('development','holdout','both'),default='both')
    parser.add_argument('--evaluate-only',action='store_true')
    parser.add_argument('--reuse-run',type=Path,help='Reuse verified native attempts from an earlier policy experiment')
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    settings=Settings.load()
    if settings.crisp_gpu_backend!='cuda':raise ValueError('CUDA required')
    bank=Path('D:/models/datasets/subtitle-studio-references-v1');index=read_json(bank/'index.json')
    fleurs=read_json(Path('D:/models/datasets/koesub-fleurs-ja-v1/index.json'))['samples']
    external=read_json(Path('D:/models/datasets/koesub-fleurs-ja-holdout-v1/index.json'))['samples']
    dev=[{**s,'cohort':'development','corpus':'mcdc'} for s in index['samples'][:5]]+[{**s,'cohort':'development'} for s in fleurs]
    held=[{**s,'cohort':'holdout','corpus':'mcdc'} for s in index['samples'][5:10]]+[{**s,'cohort':'holdout'} for s in external]
    samples=dev if args.cohort=='development' else held if args.cohort=='holdout' else dev+held
    inputs=[audio_input(s) for s in samples]
    protocol={'version':2,'inputs':inputs,'cohorts':{s['id']:s['cohort'] for s in samples},'models':MODELS[:2],
        'policy_sha256':{name:hashlib.sha256(Path('studio',name+'.py').read_bytes()).hexdigest()
                        for name in ('asr_disagreement','asr_retry','asr_review','pipeline_worker')},
        'labels_digest':digest([{s['id']:s['reference_jp']} for s in samples])}
    path=output/'protocol.json'
    if path.exists() and read_json(path)!=protocol:raise ValueError('Changed frozen protocol; use a separate run directory')
    write_json(path,protocol)
    old=read_json(Path('D:/models/.cache/benchmark-asr-fusion-v1/collected.json'))['records']
    old_by_id={r['id']:r for r in old}
    reuse={}
    if args.reuse_run:
        prior=read_json(args.reuse_run/'collected.json')
        if digest(prior['records'])!=prior['digest']:raise ValueError('Changed prior collection')
        for record in prior['records']:
            reuse[record['id']]=record['scan']['manifest']
            old_by_id[record['id']]={'production':record['control']}
            for model in (record['baseline'],record['auxiliary']):
                pointer=output/'globals/pointers'/f'{record["id"]}-{model["model"]}.json'
                if not pointer.exists():write_json(pointer,{'manifest':model['manifest']})
    for record in old:
        for model in record['models'][:2]:
            pointer=output/'globals/pointers'/f'{record["id"]}-{model["model"]}.json'
            if not pointer.exists():write_json(pointer,{'manifest':model['manifest']})
    started=time.perf_counter()
    if not args.evaluate_only:
        records=[]
        for sample,meta in zip(inputs,samples):
            if hashlib.sha256(Path(sample['audio']).read_bytes()).hexdigest()!=sample['audio_sha256']:raise ValueError('Changed audio')
            print('CASE',sample['id'],meta['cohort'],flush=True)
            baseline=collect_asr(sample,MODELS[0],settings,output/'globals',bank)
            auxiliary=collect_asr(sample,MODELS[1],settings,output/'globals',bank)
            control=old_by_id[sample['id']]['production'] if sample['id'] in old_by_id else collect_review(sample,baseline,settings,output/'control')
            scan=run_v2(sample,baseline,auxiliary,settings,output,reuse.get(sample['id']))
            records.append({'id':sample['id'],'cohort':meta['cohort'],'baseline':baseline,'auxiliary':auxiliary,'control':control,'scan':scan})
            write_json(output/'collected.json',{'records':records,'digest':digest(records)})
            print('scan targets',scan.get('disagreements'),'windows',scan.get('retry_windows'),'reused',scan.get('reused_auxiliary_attempts'),
                  'edits',len(scan.get('review',{}).get('changes',[])),flush=True)
        if not (output/'collection-timings.json').exists():write_json(output/'collection-timings.json',{'wall_seconds':round(time.perf_counter()-started,3)})
    frozen=read_json(output/'collected.json')
    if digest(frozen['records'])!=frozen['digest'] or len(frozen['records'])!=len(samples):raise ValueError('Incomplete/changed collection')
    rows,summary=evaluate(samples,frozen['records'])
    write_json(output/'results.json',{'created':now(),'protocol':protocol,'rows':rows,'summary':summary,'collection_digest':frozen['digest'],
        'collection_timing':read_json(output/'collection-timings.json')})
    lines=['# Auxiliary disagreement scan v2','',
        'Reference labels were not provided to ASR or production review. Development clips were inspected previously; holdout clips are new but not source/speaker independent. No training-contamination claim is made.','']
    for cohort,group in summary.items():
        lines += [f'## {cohort}','','| Variant | Cases | Edits | CER | Original stage seconds |','|---|---:|---:|---:|---:|']
        for name,row in group['scores'].items():
            cer=f'{row["cer"]:.2%}' if row['cer'] is not None else 'Incomplete coverage'
            lines.append(f'| {name} | {row["cases"]}/{row["total_cases"]} | {row["edits"]}/{row["characters"]} | {cer} | {row["seconds"]} |')
        lines += ['',f'Disagreements: {group["disagreements"]}; retry windows: {group["retry_windows"]}; reused auxiliary fragments: {group["reused_auxiliary_attempts"]}.',
            f'Applied phrase effects against references: {group["phrase_effects"]}; improved cases: {group["improved_cases"]}; harmed: {group["harmed_cases"]}.','']
    atomic_text(output/'report.md','\n'.join(lines))
    print(summary,flush=True);print('REPORT',output/'report.md',flush=True)


if __name__=='__main__':main()

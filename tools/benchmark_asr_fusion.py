"""CUDA-only ASR/fusion benchmark with separated inference inputs and reference labels."""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
from pathlib import Path
import re
import time

from studio.core import load_srt, now, atomic_text
from studio.pipeline import create_run, digest, load_run, track_from
from studio.pipeline_worker import AsrQualityError, PipelineRunner, pipeline_lock, read_json, write_json, run_pipeline
from studio.storage import Settings
from tools.asr_oracle import evaluate_oracle
from tools.compare_reference import normalize_text, score_text
from tools.gpu_telemetry import GpuTelemetry

MODELS = [
    {'key':'large-v3','engine':2,'kind':'Whisper / GGML','name':'Large V3','model':'D:/models/whisper/ggml-large-v3.bin','vad':True},
    {'key':'kotoba','engine':2,'kind':'Whisper / GGML','name':'Kotoba','model':'D:/models/whisper/ggml-kotoba-whisper-v2.0.bin','vad':True},
    {'key':'qwen','engine':1,'kind':'Qwen ASR','name':'Qwen JA Anime','model':'D:/models/asr/qwen3-asr-1.7b-ja-anime-q8_0.gguf','vad':True},
    {'key':'anime','engine':2,'kind':'Whisper / GGML','name':'Anime conversion','model':'D:/models/whisper/ggml-anime-whisper.bin','vad':True},
    {'key':'reazon','engine':3,'kind':'ReazonSpeech / GGUF','name':'Reazon conversion','model':'D:/models/asr/reazonspeech-nemo-v2-f16.gguf','vad':True},
]


def audio_input(sample):
    """Explicit allowlist: references and labels cannot enter inference payloads."""
    return {key:sample[key] for key in ('id','audio','audio_sha256','source_range_ms')}


def config_for(sample,model,settings,output,jp_only=False):
    duration=sample['source_range_ms'][1]-sample['source_range_ms'][0]
    item={k:v for k,v in model.items() if k!='key'}
    return {'media':sample['audio'],'media_duration':duration,'start':0,'duration':duration,'audio_track':0,
        'asr':[item],'translations':[] if jp_only else [{'model':'unused','variant':0}],
        'judge_model':'','backend':'lmstudio','review':'rules','review_settings':{},'settings':asdict(settings),
        'prompt':'','export_srt':True,'autosplit':False,'readability_repair':False,'source_guard':True,
        'transcription_only':jp_only,'benchmark_scope':'jp-fusion' if jp_only else 'asr-only',
        'benchmark_audio_sha256':sample['audio_sha256'],'output_dir':str(output)}


def cuda_evidence(log):
    return bool(re.search(r'(?:using|device|buffer|backend|size)[^\n]*CUDA0|CUDA0[^\n]*(?:buffer|backend|size)|backend\s*[:=]\s*cuda',log,re.I))


def valid_timing(track,duration):
    cues=track.segments
    return bool(cues) and all(0<=s.start<s.end<=duration for s in cues) and all(a.end<=b.start for a,b in zip(cues,cues[1:]))


def legacy_manifest(bank,sample,model):
    if not sample['id'].startswith('mcdc-'): return None
    path=bank/('evaluation/'+sample['id']+'.json' if model['key']=='large-v3'
               else 'model-comparison/'+model['key']+'-'+sample['id']+'.json')
    return Path(read_json(path)['manifest']) if path.is_file() else None


def inspect_asr(manifest,sample,model,cached):
    state=load_run(manifest);config=state['config']
    duration=sample['source_range_ms'][1]-sample['source_range_ms'][0]
    if (Path(config['media']).resolve()!=Path(sample['audio']).resolve() or config['start']!=0 or config['duration']!=duration
            or Path(config['asr'][0]['model']).resolve()!=Path(model['model']).resolve()
            or config['settings']['crisp_gpu_backend']!='cuda' or not config['asr'][0]['vad']):
        raise ValueError('Cached ASR does not match the benchmark input/configuration')
    stage=next(s for s in state['stages'] if s['id']=='asr-0')
    directory=Path(manifest).parent/'asr-0';decoded=None;track=None;error=state.get('error','')
    if stage['status']=='completed':
        decoded=read_json(stage['artifact'])
        if digest(decoded)!=stage['digest']: raise ValueError('Changed ASR result')
        track=track_from(decoded['track'])
    else:
        files=list(directory.glob('*.srt'))
        if len(files)==1:
            try: track=load_srt(files[0])
            except (UnicodeError,ValueError): pass  # never repair invalid bytes for scoring
    log=(directory/'engine.log').read_text(encoding='utf-8',errors='replace') if (directory/'engine.log').exists() else ''
    backend=cuda_evidence(log)
    usable=bool(decoded and track and valid_timing(track,duration))
    if decoded and not usable: error='Rejected for invalid or overlapping cue times'
    if usable and not backend: raise ValueError('Missing actual CUDA inference evidence')
    return {'model':model['key'],'manifest':str(manifest),'original_seconds':stage.get('seconds',0),
        'cached':cached,'cuda_confirmed':backend,'usable':usable,'readable_text':track is not None,
        'hypothesis_jp':'\n'.join(s.text for s in track.segments) if track else None,
        'decoded':decoded if usable else None,'error':error or None,
        'engine_log_sha256':hashlib.sha256(log.encode()).hexdigest(),
        'raw_srt_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.srt')}}


def collect_asr(sample,model,settings,output,bank):
    pointer=output/'pointers'/f'{sample["id"]}-{model["key"]}.json'
    manifest=Path(read_json(pointer)['manifest']) if pointer.exists() else legacy_manifest(bank,sample,model)
    cached=manifest is not None
    if manifest is None:
        folder=output/'runs'/f'{sample["id"]}-{model["key"]}'
        config=config_for(sample,model,settings,output/'exports'/folder.name)
        state=create_run(config,folder)
        state['stages']=[s for s in state['stages'] if s['id'] in ('audio','asr-0')]
        state['status']='running';manifest=folder/'manifest.json';write_json(manifest,state)
        write_json(pointer,{'manifest':str(manifest)})
    state=load_run(manifest)
    if state.get('failure_kind')=='operational':
        raise RuntimeError('Previous operational ASR failure must not be scored as a quality rejection: '+state.get('error',''))
    if any(s['id']=='asr-0' and s['status'] not in ('completed','failed') for s in state['stages']):
        cached=False;runner=PipelineRunner(manifest,lambda *a,**kw:None)
        telemetry=GpuTelemetry(manifest,manifest.parent/'gpu-telemetry.json');telemetry.start()
        try:
            with pipeline_lock(manifest.parent):
                try:
                    audio=runner.stage('audio',runner.audio)['audio']
                    runner.stage('asr-0',lambda f:runner.asr(f,runner.config['asr'][0],audio))
                    runner.state['status']='completed'
                except AsrQualityError as exc:
                    runner.state.update(status='failed',failure_kind='quality',error=str(exc))
                except Exception as exc:
                    runner.state.update(status='failed',failure_kind='operational',error=str(exc));runner.save()
                    raise
                runner.save()
        finally: telemetry.close()
    return inspect_asr(manifest,sample,model,cached)


def collect_review(sample,baseline,settings,output):
    if not baseline['usable']: return {'usable':False,'error':'No usable baseline; production fusion skipped'}
    folder=output/'runs'/f'{sample["id"]}-production';manifest=folder/'manifest.json'
    reused=manifest.exists()
    if not reused:
        config=config_for(sample,MODELS[0],settings,output/'exports'/folder.name,True)
        config.update(source_review_version=1,retry_asr={'enabled':True,'padding_ms':3000,'max_window_ms':30000,
            'max_targets':12,'auxiliary':{k:v for k,v in MODELS[1].items() if k!='key'}})
        state=create_run(config,folder)
        original=load_run(baseline['manifest'])
        for key in ('audio','asr-0'):
            stage=next(s for s in state['stages'] if s['id']==key)
            old=next(s for s in original['stages'] if s['id']==key)
            value=read_json(old['artifact'])
            if digest(value)!=old['digest']: raise ValueError('Changed baseline seed artifact')
            target=folder/key/'result.json';write_json(target,value)
            stage.update(status='completed',artifact=str(target),digest=digest(value),seconds=0,
                         reused_from=old['artifact'],reused_seconds=old.get('seconds',0))
        write_json(manifest,state)
    before=time.perf_counter()
    telemetry=GpuTelemetry(manifest,folder/('resume-gpu-telemetry.json' if reused else 'gpu-telemetry.json'));telemetry.start()
    try: run_pipeline(manifest,lambda *a,**kw:None)
    finally: telemetry.close()
    state=load_run(manifest);review=read_json(folder/'jp-review/result.json')
    final=track_from(read_json(folder/'jp-layout/result.json')['track'])
    base=track_from(baseline['decoded']['track'])
    if [(s.start,s.end) for s in final.segments]!=[(s.start,s.end) for s in base.segments]:
        raise AssertionError('Production fusion changed baseline timing')
    retry=read_json(folder/'asr-retry/result.json')
    attempts=[a for w in retry['windows'] for a in w['attempts']]
    evidence=[cuda_evidence((Path(a['directory'])/'engine.log').read_text(encoding='utf-8',errors='replace')) for a in attempts]
    if evidence and not all(evidence): raise ValueError('Missing CUDA evidence in production retry')
    return {'usable':True,'manifest':str(manifest),'cached':reused,
        'wall_seconds_this_session':round(time.perf_counter()-before,3),
        'original_seconds':sum(s.get('seconds',0) for s in state['stages']),
        'hypothesis_jp':'\n'.join(s.text for s in final.segments),'review':review,
        'retry_windows':len(retry['windows']),'cuda_confirmed':all(evidence) if evidence else None,
        'timings_unchanged':True}


def edit_effects(reference,baseline,review):
    """Score each applied phrase in isolation; effects need not be additive."""
    track=track_from(baseline['decoded']['track']);base_text='\n'.join(s.text for s in track.segments)
    base_score=score_text(reference,base_text)['edit_distance'];records=[]
    for change in review['review']['changes']:
        altered=[]
        for cue in track.segments:
            text=cue.text
            if cue.id==change['cue_id']:
                a,b=change['text_start'],change['text_end']
                if text[a:b]!=change['before']: raise ValueError('Stale production correction')
                text=text[:a]+change['after']+text[b:]
            altered.append(text)
        score=score_text(reference,'\n'.join(altered))['edit_distance'];delta=base_score-score
        records.append({'before':change['before'],'after':change['after'],'cue_id':change['cue_id'],
            'edit_distance_delta':delta,'effect':'helpful' if delta>0 else 'harmful' if delta<0 else 'neutral',
            'scope':'Single phrase applied to untouched baseline; reference spelling differences may affect this label'})
    return records


def retry_candidates(baseline,retry,duration):
    """Overlay one usable retry on the untouched outside baseline, for scoring only."""
    base=track_from(baseline['decoded']['track']);result={}
    for window in retry['windows']:
        ids=set(window['cue_ids'])
        for index,attempt in enumerate(window['attempts']):
            if not attempt.get('usable'): continue
            candidate=deepcopy(base)
            candidate.segments=[s for s in candidate.segments if s.id not in ids]+track_from(attempt['track']).segments
            candidate.segments.sort(key=lambda s:(s.start,s.end))
            if not valid_timing(candidate,duration): continue
            name=f'retry-{window["id"]}-{index}'
            result[name]={'hypothesis_jp':'\n'.join(s.text for s in candidate.segments),
                'source_model':attempt['model'],'source_directory':attempt['directory'],'window':window['id']}
    return result


def evaluate(samples,collected):
    labels={s['id']:s for s in samples};rows=[]
    for entry in collected:
        sample=labels[entry['id']];reference=sample['reference_jp'];models={a['model']:deepcopy(a) for a in entry['models']}
        for model in models.values():
            if model['readable_text']: model['score']=score_text(reference,model['hypothesis_jp'])
        usable={name:m['hypothesis_jp'] for name,m in models.items() if m['usable']}
        production=deepcopy(entry['production'])
        extra={}
        if production['usable']:
            # Seeded baseline stages have zero seconds in the retry manifest.
            # Include their original ASR cost when comparing production with a
            # standalone model, while retaining the incremental review cost.
            production['incremental_review_seconds']=production['original_seconds']
            production['original_seconds']+=models['large-v3']['original_seconds']
            production['score']=score_text(reference,production['hypothesis_jp'])
            production['edit_effects']=edit_effects(reference,models['large-v3'],production)
            if production.get('manifest'):
                state=load_run(production['manifest'])
                stage=next(s for s in state['stages'] if s['id']=='asr-retry')
                retry=read_json(stage['artifact'])
                if digest(retry)!=stage['digest']: raise ValueError('Changed production retry artifact')
                extra=retry_candidates(models['large-v3'],retry,state['config']['duration'])
        oracles={}
        if 'large-v3' in usable:
            retry_text={k:v['hypothesis_jp'] for k,v in extra.items()}
            for name,hypotheses in [('baseline-kotoba',{**{k:v for k,v in usable.items() if k in ('large-v3','kotoba')},**retry_text}),
                                    ('all-usable',{**usable,**retry_text})]:
                oracles[name]=evaluate_oracle(reference,hypotheses)
        rows.append({'id':entry['id'],'corpus':sample.get('corpus','mcdc'),'split':sample['split'],
            'reference_characters':len(normalize_text(reference)),'models':models,'production':production,
            'oracle_retry_inputs':extra,'oracles':oracles})
    return rows


def summarize(rows):
    result={}
    for corpus in sorted({r['corpus'] for r in rows}|{'all'}):
        subset=[r for r in rows if corpus=='all' or r['corpus']==corpus];scores={}
        for name in [m['key'] for m in MODELS]+['production','oracle-pair','oracle-all','oracle-whole-all']:
            selected=[];timing=0;seconds=0;cached=0
            for row in subset:
                if name in row['models']:
                    item=row['models'][name];timing+=item['usable'];seconds+=item['original_seconds'];cached+=item['cached']
                    if 'score' in item:selected.append(item['score'])
                elif name=='production':
                    item=row['production'];timing+=item['usable'];seconds+=item.get('original_seconds',0);cached+=item.get('cached',False)
                    if 'score' in item:selected.append(item['score'])
                else:
                    key='baseline-kotoba' if name=='oracle-pair' else 'all-usable'
                    if key in row['oracles']:
                        item=row['oracles'][key]
                        selected.append(item['best_whole_hypothesis']['score'] if name=='oracle-whole-all' else item['score'])
            chars=sum(s['reference_characters'] for s in selected);edits=sum(s['edit_distance'] for s in selected)
            scores[name]={'total_cases':len(subset),'scored_text_cases':len(selected),'usable_timing_cases':timing if not name.startswith('oracle') else None,
                'reference_characters':chars,'edit_distance':edits,'complete_text_cer':edits/chars if chars and len(selected)==len(subset) else None,
                'available_text_cer':edits/chars if chars else None,'original_seconds':round(seconds,3),'cached_cases':cached}
        effects=[e for r in subset for e in r['production'].get('edit_effects',[])]
        matched=[r for r in subset if 'score' in r['models']['large-v3'] and 'score' in r['production']]
        deltas=[r['models']['large-v3']['score']['edit_distance']-r['production']['score']['edit_distance'] for r in matched]
        opportunities={}
        for name in ('baseline-kotoba','all-usable'):
            eligible=[r for r in matched if name in r['oracles']]
            potential=sum(r['models']['large-v3']['score']['edit_distance']-r['oracles'][name]['score']['edit_distance'] for r in eligible)
            actual=sum(r['models']['large-v3']['score']['edit_distance']-r['production']['score']['edit_distance'] for r in eligible)
            opportunities[name]={'cases':len(eligible),'potential_edits_saved':potential,'actual_edits_saved':actual,
                'fraction_of_lattice_opportunity_closed':actual/potential if potential else None}
        result[corpus]={'scores':scores,'phrase_edits':{kind:sum(e['effect']==kind for e in effects) for kind in ('helpful','harmful','neutral')},
            'retry_windows':sum(r['production'].get('retry_windows',0) for r in subset),
            'production_cases':{'improved':sum(d>0 for d in deltas),'harmed':sum(d<0 for d in deltas),'equal':sum(d==0 for d in deltas)},
            'baseline_mismatch_without_retry':sum(r['models']['large-v3']['score']['edit_distance']>0 and r['production'].get('retry_windows',0)==0 for r in matched),
            'selection_opportunity':opportunities}
    return result


def markdown(summary):
    lines=['# KoeSub ASR fusion benchmark','',
        'Reference text is used only after inference and production review have completed. Oracle results use references and are not deployable subtitles.',
        'Invalid UTF-8 and invalid timing are reported separately. Partial text coverage is not ranked against complete coverage. Times are original stage durations, including reused inference, not current replay speed.']
    for corpus,group in summary.items():
        lines += ['',f'## {corpus}','','| Variant | Text cases | Accepted subtitle outputs | CER | Original seconds | Cached cases |',
                  '|---|---:|---:|---:|---:|---:|']
        for name,score in group['scores'].items():
            cer=f'{score["complete_text_cer"]:.2%}' if score['complete_text_cer'] is not None else 'Incomplete coverage'
            timing='evaluation only' if score['usable_timing_cases'] is None else str(score['usable_timing_cases'])
            lines.append(f'| {name} | {score["scored_text_cases"]}/{score["total_cases"]} | {timing} | {cer} | {score["original_seconds"]} | {score["cached_cases"]} |')
        effects=group['phrase_edits'];cases=group['production_cases']
        lines += ['',f'Applied phrases: {effects.get("helpful",0)} helpful, {effects.get("harmful",0)} harmful, {effects.get("neutral",0)} neutral against the reference. Retry windows: {group["retry_windows"]}.',
            f'Production versus baseline: {cases.get("improved",0)} improved cases, {cases.get("harmed",0)} harmed, {cases.get("equal",0)} unchanged. Baseline/reference mismatches with no retry window: {group["baseline_mismatch_without_retry"]}.',
            '', '| Oracle pool | Potential character edits saved | Actual edits saved | Opportunity used |', '|---|---:|---:|---:|']
        for pool,value in group['selection_opportunity'].items():
            fraction=value['fraction_of_lattice_opportunity_closed']
            fraction=f'{fraction:.1%}' if fraction is not None else 'N/A'
            lines.append(f'| {pool} | {value["potential_edits_saved"]} | {value["actual_edits_saved"]} | {fraction} |')
    lines += ['','## Limits','',
        'MCDC captions are community references without an independent audio audit. FLEURS is read speech from a separate corpus, not a second movie; its first five validation rows were fixed before ASR. No claim is made about model-training contamination or independent speaker identities.',
        'Oracle selection is constrained to a hypothesis-derived phrase lattice and whole-hypothesis paths from accepted models, including usable production audio retries overlaid on the baseline. It is an evaluation of available selection opportunity, not an unrestricted accuracy upper bound. No model settings were tuned using these results.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank',type=Path,default=Path('D:/models/datasets/subtitle-studio-references-v1'))
    parser.add_argument('--external',type=Path,default=Path('D:/models/datasets/koesub-fleurs-ja-v1/index.json'))
    parser.add_argument('--output',type=Path,default=Path('D:/models/.cache/benchmark-asr-fusion-v1'))
    parser.add_argument('--evaluate-only',action='store_true')
    args=parser.parse_args();settings=Settings.load()
    if settings.crisp_gpu_backend!='cuda': raise ValueError('Benchmark requires explicit CUDA')
    index=read_json(args.bank/'index.json');core=set(index['evaluation_core'])
    samples=[{**s,'corpus':'mcdc'} for s in index['samples'] if s['id'] in core]+read_json(args.external)['samples']
    inputs=[audio_input(s) for s in samples];output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    for sample in inputs:
        if hashlib.sha256(Path(sample['audio']).read_bytes()).hexdigest()!=sample['audio_sha256']: raise ValueError('Changed evaluation audio')
    protocol={'version':1,'models':MODELS,'inputs':inputs,'labels_digest':digest([{s['id']:s['reference_jp']} for s in samples]),
        'review_source_sha256':hashlib.sha256(Path('studio/asr_review.py').read_bytes()).hexdigest()}
    path=output/'protocol.json'
    if path.exists() and read_json(path)!=protocol: raise ValueError('Changed benchmark protocol; use a new output directory')
    write_json(path,protocol);write_json(output/'inputs.json',inputs)
    started=time.perf_counter()
    if not args.evaluate_only:
        collected=[]
        for sample in inputs:
            print('SAMPLE',sample['id'],flush=True);models=[]
            for model in MODELS:
                row=collect_asr(sample,model,settings,output,args.bank);models.append(row)
                print(model['key'],'usable=',row['usable'],'cached=',row['cached'],'seconds=',row['original_seconds'],'CUDA=',row['cuda_confirmed'],flush=True)
            production=collect_review(sample,models[0],settings,output)
            print('production','windows=',production.get('retry_windows'),'edits=',len(production.get('review',{}).get('changes',[])),flush=True)
            collected.append({'id':sample['id'],'models':models,'production':production})
            write_json(output/'collected.json',{'records':collected,'digest':digest(collected)})
        if not (output/'collection-timings.json').exists():
            write_json(output/'collection-timings.json',{'wall_seconds':round(time.perf_counter()-started,3),
                'scope':'Collection session, with cached and fresh inference distinguished per case',
                'cached_model_cases':sum(m['cached'] for r in collected for m in r['models']),
                'fresh_model_cases':sum(not m['cached'] for r in collected for m in r['models'])})
    frozen=read_json(output/'collected.json')
    if digest(frozen['records'])!=frozen['digest'] or [r['id'] for r in frozen['records']]!=[s['id'] for s in inputs]:
        raise ValueError('Incomplete or changed collection; scoring refused')
    rows=evaluate(samples,frozen['records']);summary=summarize(rows)
    result={'created':now(),'protocol':protocol,'collection_digest':frozen['digest'],'cases':rows,'summary':summary,
        'collection_timing':read_json(output/'collection-timings.json') if (output/'collection-timings.json').exists() else None,
        'wall_seconds_this_session':round(time.perf_counter()-started,3),'mode':'evaluation replay' if args.evaluate_only else 'collection and evaluation'}
    write_json(output/'results.json',result);atomic_text(output/'report.md',markdown(summary))
    print('REPORT',output/'report.md',flush=True)
    for corpus,data in summary.items():
        print(corpus,{name:s['complete_text_cer'] for name,s in data['scores'].items()},flush=True)


if __name__=='__main__': main()

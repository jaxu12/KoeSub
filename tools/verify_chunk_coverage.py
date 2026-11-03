"""Fresh short-chunk CUDA integration against an immutable previous ASR run.

Optionally mask one whole existing ASR cue as a controlled gap probe. That cue
is an ASR hypothesis, not independent truth. No reference subtitles enter ASR.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
import time
from types import MethodType, SimpleNamespace

from studio.asr_coverage import search_coverage
from studio.audio_boundaries import audio_digest
from studio.core import export_srt, normalize,load_srt
from studio.evaluation_text import normalize_text
from studio.pipeline import track_from
from studio.pipeline_worker import PipelineRunner, read_json, write_json
from studio.storage import Settings
from tools.benchmark_asr_fusion import cuda_evidence
from tools.gpu_telemetry import GpuTelemetry
from tools.compare_local_film import exact_distance


def reselect_verified(source,output):
    """Evaluate new selection using immutable native evidence; never fresh ASR."""
    from studio.asr_coverage import recover_gaps
    from studio.coverage_focus import POLICY
    if output.exists():raise ValueError('Use a new selection replay directory')
    frozen={name:audio_digest(source/name) for name in ('input.json','result.json','summary.json')}
    inputs=read_json(source/'input.json');previous=read_json(source/'result.json')
    if previous.get('version')!=2:raise ValueError('Only separated text/alignment evidence can be reselected')
    config=inputs['config'];base=track_from(inputs['baseline'])
    started=time.monotonic()
    selection=recover_gaps(base,previous['candidates'],previous['peers'],config['asr'][0]['model'],config['retry_asr']['auxiliary']['model'])
    result={**previous,**selection,'policy':POLICY}
    output.mkdir(parents=True);write_json(output/'input.json',inputs);write_json(output/'result.json',result)
    export_srt(track_from(result['track']),output/'Japanese.srt');audit=audit_coverage(output)
    summary={'scope':'Cached native text/alignment evidence; new selection only; not fresh GPU inference',
        'seconds':round(time.monotonic()-started,4),'added':len(result['changes']),'new_native_processes':0,
        'original_result':str(source/'result.json'),'original_hashes':frozen,'policy':POLICY,'audit':audit}
    assert frozen=={name:audio_digest(source/name) for name in frozen}
    write_json(output/'summary.json',summary)
    return summary


def audit_coverage(output):
    """Check final exports and unchanged source cues independently of selection."""
    inputs=read_json(output/'input.json');result=read_json(output/'result.json')
    before=inputs['baseline']['segments'];after=result['track']['segments']
    old_ids={cue['id'] for cue in before}
    assert [cue for cue in after if cue['id'] in old_ids]==before
    assert len(after)==len(before)+len(result['changes'])
    assert len({cue['id'] for cue in after})==len(after)
    assert all(cue['start']<cue['end'] for cue in after)
    assert all(a['end']<=b['start'] for a,b in zip(after,after[1:]))
    exported=load_srt(output/'Japanese.srt').segments
    assert [(s.start,s.end,s.text) for s in exported]==[(s['start'],s['end'],s['text']) for s in after]
    audit={'existing_cues_identical':True,'unique_ids':True,'zero_invalid_times':True,
           'zero_overlaps':True,'exact_srt_round_trip':True}
    write_json(output/'audit.json',audit)
    return audit


def compare_reference(output,reference):
    """Post-inference reference agreement; reference never enters decoding."""
    inputs=read_json(output/'input.json');result=read_json(output/'result.json')
    start=inputs['config']['start'];end=start+inputs['config']['duration']
    captions=load_srt(reference).segments
    text=normalize_text(''.join(s.text for s in captions if s.start<end and s.end>start))
    variants={}
    for name,cues in [('input',inputs['baseline']['segments']),('output',result['track']['segments'])]:
        hypothesis=normalize_text(''.join(s['text'] for s in cues))
        variants[name]={'cues':len(cues),'characters':len(hypothesis),'reference_characters':len(text),
                        'edits':exact_distance(text,hypothesis)}
    matches=[]
    for change in result['changes']:
        cue=change['after'];near=normalize_text(''.join(s.text for s in captions
            if s.start<cue['end']+5000 and s.end>cue['start']-5000))
        matches.append({'start':cue['start'],'end':cue['end'],'characters':len(normalize_text(cue['text'])),
                        'nearby_exact_reference_match':normalize_text(cue['text']) in near})
    report={'variants':variants,'insertions':matches,'reference_sha256':audio_digest(reference),
        'scope':'Post-inference agreement with a user-provided ASR reference; not independently verified audio accuracy',
        'reference_selection':'All captions overlapping the selected interval; insertion match within five seconds'}
    write_json(output/'reference-comparison.json',report)
    return report


def verify(source, output, start, end, hide_index=None,chunk_seconds=30,coverage_version=2):
    if output.exists():raise ValueError('Use a new output directory')
    original=read_json(source);config=deepcopy(original['config']);directory=source.parent
    if config['settings']['crisp_gpu_backend']!='cuda':raise ValueError('This hardware check requires CUDA')
    if not config['start']<=start<end<=config['start']+config['duration']:raise ValueError('Probe outside source range')
    raw=directory/'asr-timing-review/result.json'
    if not raw.is_file():raw=directory/'asr-0/result.json'
    document=read_json(raw);base=track_from(document['track'])
    hidden=asdict(base.segments[hide_index]) if hide_index is not None else None
    if hidden and not start<=hidden['start']<hidden['end']<=end:raise ValueError('Masked cue outside probe')
    base.segments=[cue for cue in base.segments if start<=cue.start<cue.end<=end and (not hidden or cue.id!=hidden['id'])]
    source_audio=Path(read_json(directory/'audio/result.json')['audio'])
    frozen={str(path):audio_digest(path) for path in (source,raw,source_audio)}
    pointer=Path('data/last_project.json');before_pointer=pointer.read_bytes() if pointer.exists() else None
    output.mkdir(parents=True)
    settings=Settings(**config['settings']);settings.cache_dir=str(output/'cache')
    config.update(start=start,duration=end-start,settings=asdict(settings),asr_coverage={'enabled':True,'version':coverage_version,'chunk_ms':chunk_seconds*1000,'padding_ms':3000})
    state={'status':'running','stages':[{'id':'asr-coverage','status':'running'}]}
    manifest=output/'probe.json';write_json(manifest,state)
    write_json(output/'input.json',{'config':config,'baseline':asdict(base),'source_hashes':frozen,
        'scope':'Fresh coverage inference; cached baseline; optional artificial masked cue; not independent accuracy'})
    write_json(output/'evaluation-only.json',{'hidden_asr_hypothesis':hidden,'not_independent_gold':True})
    runner=SimpleNamespace(config=config,settings=settings,folder=output,
                           event=lambda kind,**data:print(data.get('message',''),flush=True),progress=lambda *a:None)
    runner.call=MethodType(PipelineRunner.call,runner)
    runner.parse_asr=MethodType(PipelineRunner.parse_asr,runner)
    probe_audio=output/'input.wav'
    runner.call([settings.ffmpeg,'-hide_banner','-nostdin','-y','-ss',str((start-original['config']['start'])/1000),
        '-i',str(source_audio),'-t',str((end-start)/1000),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(probe_audio)],output,'crop',120)
    folder=output/'coverage';folder.mkdir()
    telemetry=GpuTelemetry(manifest,output/'gpu.json',capture_processes=True);telemetry.start();started=time.monotonic()
    try:result=search_coverage(runner,folder,base,probe_audio)
    except Exception as exc:
        state.update(status='failed',error=str(exc));state['stages'][0]['status']='failed';write_json(manifest,state)
        raise
    finally:gpu=telemetry.close()
    seconds=round(time.monotonic()-started,3);write_json(output/'result.json',result)
    export_srt(track_from(result['track']),output/'Japanese.srt')
    audit_coverage(output)
    processes={str(path):audio_digest(path) for path in folder.rglob('engine-process.json')}
    replay=search_coverage(runner,folder,base,probe_audio)
    unchanged=processes=={str(path):audio_digest(path) for path in folder.rglob('engine-process.json')}
    assert replay==result and unchanged
    assert all(audio_digest(Path(path))==value for path,value in frozen.items())
    assert (pointer.read_bytes() if pointer.exists() else None)==before_pointer
    logs={str(path.relative_to(output)):cuda_evidence(path.read_text('utf8',errors='replace')) for path in folder.rglob('engine.log') if path.parent.name!='alignment'}
    pids=[read_json(path)['pid'] for path in folder.rglob('engine-process.json')]
    aligners=[read_json(path)['pid'] for path in folder.glob('*/alignment/engine-process.json')]
    observed={row['pid'] for row in gpu.get('compute_processes',[])}
    summary={'scope':'Fresh coverage inference on real audio; cached baseline; no independent quality labels',
        'audio_seconds':(end-start)/1000,'wall_seconds':seconds,'chunk_seconds':chunk_seconds,'coverage_version':coverage_version,'windows':len(result['windows']),
        'candidates':len(result['candidates']),'added':len(result['changes']),'unresolved':result['unresolved'],
        'failed_outputs':len(result['failed_windows']),'masked_cue':bool(hidden),
        'masked_asr_text_recovered':any(normalize(change['after']['text'])==normalize(hidden['text'])
            and min(change['after']['end'],hidden['end'])>max(change['after']['start'],hidden['start']) for change in result['changes']) if hidden else None,
        'cuda_logs':logs,'native_pids':pids,'native_pids_observed_on_nvidia':[pid for pid in pids if pid in observed],
        'alignment_pids':aligners,'alignment_pids_observed_on_nvidia':[pid for pid in aligners if pid in observed],
        'whole_gpu_peak_mib':max((s['memory_used_mib'] for s in gpu['samples']),default=None),
        'gpu_errors':gpu['errors'],'replay_identical_no_new_processes':unchanged,
        'source_files_unchanged':True,'main_project_unchanged':True}
    write_json(output/'summary.json',summary)
    state.update(status='completed');state['stages'][0]['status']='completed';write_json(manifest,state)
    console={key:value for key,value in summary.items() if key not in
             ('cuda_logs','native_pids','native_pids_observed_on_nvidia','alignment_pids','alignment_pids_observed_on_nvidia')}
    console.update(cuda_asr_log_count=len(logs),all_asr_logs_cuda=bool(logs) and all(logs.values()),
                   native_processes=len(pids),native_processes_observed=len(summary['native_pids_observed_on_nvidia']),
                   alignment_processes=len(aligners),alignment_processes_observed=len(summary['alignment_pids_observed_on_nvidia']))
    print(__import__('json').dumps(console,ensure_ascii=True),flush=True)
    return summary


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start-ms',type=int,required=True);parser.add_argument('--end-ms',type=int,required=True)
    parser.add_argument('--hide-cue-index',type=int)
    parser.add_argument('--chunk-seconds',type=int,choices=range(15,121),default=30)
    parser.add_argument('--coverage-version',type=int,choices=(1,2),default=2)
    parser.add_argument('--reference',type=Path,help='Optional evaluation-only subtitles, read after inference')
    args=parser.parse_args();verify(args.source_manifest,args.output,args.start_ms,args.end_ms,args.hide_cue_index,args.chunk_seconds,args.coverage_version)
    if args.reference:print('REFERENCE AGREEMENT',compare_reference(args.output,args.reference)['variants'],flush=True)

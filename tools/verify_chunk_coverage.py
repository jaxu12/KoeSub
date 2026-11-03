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
from studio.core import export_srt, normalize
from studio.pipeline import track_from
from studio.pipeline_worker import PipelineRunner, read_json, write_json
from studio.storage import Settings
from tools.benchmark_asr_fusion import cuda_evidence
from tools.gpu_telemetry import GpuTelemetry


def verify(source, output, start, end, hide_index=None,chunk_seconds=30):
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
    config.update(start=start,duration=end-start,settings=asdict(settings),asr_coverage={'enabled':True,'chunk_ms':chunk_seconds*1000,'padding_ms':3000})
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
    processes={str(path):audio_digest(path) for path in folder.rglob('engine-process.json')}
    replay=search_coverage(runner,folder,base,probe_audio)
    unchanged=processes=={str(path):audio_digest(path) for path in folder.rglob('engine-process.json')}
    assert replay==result and unchanged
    assert all(audio_digest(Path(path))==value for path,value in frozen.items())
    assert (pointer.read_bytes() if pointer.exists() else None)==before_pointer
    logs={str(path.relative_to(output)):cuda_evidence(path.read_text('utf8',errors='replace')) for path in folder.rglob('engine.log')}
    pids=[read_json(path)['pid'] for path in folder.rglob('engine-process.json')]
    observed={row['pid'] for row in gpu.get('compute_processes',[])}
    summary={'scope':'Fresh coverage inference on real audio; cached baseline; no independent quality labels',
        'audio_seconds':(end-start)/1000,'wall_seconds':seconds,'chunk_seconds':chunk_seconds,'windows':len(result['windows']),
        'candidates':len(result['candidates']),'added':len(result['changes']),'unresolved':result['unresolved'],
        'failed_outputs':len(result['failed_windows']),'masked_cue':bool(hidden),
        'masked_asr_text_recovered':any(normalize(change['after']['text'])==normalize(hidden['text'])
            and min(change['after']['end'],hidden['end'])>max(change['after']['start'],hidden['start']) for change in result['changes']) if hidden else None,
        'cuda_logs':logs,'native_pids':pids,'native_pids_observed_on_nvidia':[pid for pid in pids if pid in observed],
        'whole_gpu_peak_mib':max((s['memory_used_mib'] for s in gpu['samples']),default=None),
        'gpu_errors':gpu['errors'],'replay_identical_no_new_processes':unchanged,
        'source_files_unchanged':True,'main_project_unchanged':True}
    write_json(output/'summary.json',summary)
    state.update(status='completed');state['stages'][0]['status']='completed';write_json(manifest,state)
    print(__import__('json').dumps(summary,ensure_ascii=True),flush=True)
    return summary


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start-ms',type=int,required=True);parser.add_argument('--end-ms',type=int,required=True)
    parser.add_argument('--hide-cue-index',type=int)
    parser.add_argument('--chunk-seconds',type=int,choices=range(15,121),default=30)
    args=parser.parse_args();verify(args.source_manifest,args.output,args.start_ms,args.end_ms,args.hide_cue_index,args.chunk_seconds)

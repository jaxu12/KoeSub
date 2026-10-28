"""Compare both real GPU ASRs against the same complete-cue span of an external Japanese recording."""
import argparse
import copy
import json
import sys
import time
from pathlib import Path

from studio.core import Project,ProjectStore,atomic_text,export_srt,load_srt,uid
from studio.pipeline import create_run,load_run,track_from
from studio.pipeline_worker import PipelineRunner,pipeline_lock,read_json,write_json
from tools.compare_reference import compare
from tools.gpu_telemetry import GpuTelemetry


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template',type=Path,required=True)
    parser.add_argument('--cuda',action='store_true')
    parser.add_argument('--kotoba',action='store_true',help='Compare Whisper Large V3 with Kotoba + aligner, both using VAD')
    args=parser.parse_args()
    root=Path('D:/models/test-media/mcdc-japanese')
    config=copy.deepcopy(load_run(args.template)['config'])
    if args.kotoba:
        whisper=next(a for a in config['asr'] if a['engine']==2 and 'kotoba' not in a['model'].lower())
        config['asr']=[{**whisper,'vad':True},{**whisper,'vad':True,'name':'Kotoba-Whisper v2.0 FP16',
                       'model':'D:/models/whisper/ggml-kotoba-whisper-v2.0.bin'}]
        config['source_guard']=True
    reference=load_srt(root/'reference.ja.srt')
    # Start at cue 9 and stop at cue 30, preserving complete reference sentences.
    start,end=69380,181680
    if args.cuda:
        runtimes=read_json('D:/models/.runtime/cuda-runtimes.json')
        config['settings'].update(crisp_exe=runtimes['crisp']['executable'],crisp_gpu_backend='cuda',
                                  llm_exe=runtimes['llama']['executable'],llm_device='cuda')
    output=Path('D:/models/.cache/benchmark-reference-'+config['settings']['crisp_gpu_backend']+('-kotoba' if args.kotoba else ''))
    output.mkdir(parents=True,exist_ok=True)
    config.update(media=str(root/'MCDC-Japanese-23m-240p.webm'),media_duration=1389930,
                  start=start,duration=end-start,benchmark_scope='asr-only',output_dir=str(output),diagnostic_logging=True)
    folder=Path(config['settings']['cache_dir'])/'pipeline'/uid()
    state=create_run(config,folder)
    state['stages']=[s for s in state['stages'] if s['id']=='audio' or s['id'].startswith('asr-')]
    state['status']='running'
    write_json(folder/'manifest.json',state)
    atomic_text(output/'run.json',json.dumps({'manifest':str(folder/'manifest.json')},indent=2))
    def emit(kind,**data):
        if kind=='phase': print(data['message'],flush=True)
    telemetry=GpuTelemetry(folder/'manifest.json',output/'gpu-telemetry.json')
    telemetry.start();started=time.monotonic()
    try:
        with pipeline_lock(folder):
            runner=PipelineRunner(folder/'manifest.json',emit)
            audio=runner.stage('audio',runner.audio)['audio']
            tracks=[]
            for i,item in enumerate(config['asr']):
                track=track_from(runner.stage(f'asr-{i}',lambda f,item=item:runner.asr(f,item,audio))['track'])
                tracks.append(track)
                export_srt(track,output/f'asr-{i}.srt')
            runner.state.update(status='completed',benchmark_scope='asr-only')
            runner.save()
    finally: telemetry.close()
    results=compare(folder/'manifest.json',root/'reference.ja.srt',output/'comparison.json')
    project=Project(name='MCDC • JP reference vs 2 ASR • '+config['settings']['crisp_gpu_backend'],
                    media=config['media'],duration=config['media_duration'])
    reference.name='Referencja JP • istniejące napisy Commons'
    reference.segments=[s for s in reference.segments if start<=s.start and s.end<=end]
    project.add_track(reference)
    export_srt(reference,output/'reference.ja.srt')
    for track in tracks: project.add_track(track)
    ProjectStore(output/'project.sqlite').save(project,'reference benchmark')
    timing={'manifest':str(folder/'manifest.json'),'scope':'2 ASR only; no translation/review pipeline',
            'range_ms':[start,end],'audio_seconds':(end-start)/1000,
            'wall_seconds':round(time.monotonic()-started,3),'backend':config['settings']['crisp_gpu_backend'],
            'stages':[{'id':s['id'],'seconds':s.get('seconds',0)} for s in runner.state['stages']]}
    atomic_text(output/'timings.json',json.dumps(timing,indent=2))
    print('Reference comparison project:',output/'project.sqlite',flush=True)


if __name__=='__main__': main()

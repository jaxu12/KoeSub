"""CUDA-only AB/BA timing comparison on the same complete video and decoding settings."""
import copy
import json
from pathlib import Path
import time

from studio.core import atomic_text, export_srt, uid
from studio.pipeline import create_run, load_run, track_from
from studio.pipeline_worker import PipelineRunner, pipeline_lock, write_json
from tools.gpu_telemetry import GpuTelemetry


def main():
    template=Path('D:/models/.cache/pipeline/c97c4289b82440f9a717f22735d5741d/manifest.json')
    base=load_run(template)['config']
    output=Path('D:/models/.cache/benchmark-kotoba-cuda');output.mkdir(parents=True,exist_ok=True)
    whisper=base['asr'][0]
    kotoba={**whisper,'model':'D:/models/whisper/ggml-kotoba-whisper-v2.0.bin','name':'Kotoba-Whisper v2.0 FP16'}
    results=[]
    for iteration,models in enumerate(([whisper,kotoba],[kotoba,whisper])):
        config=copy.deepcopy(base)
        config.update(asr=models,benchmark_scope='asr-only',output_dir=str(output),diagnostic_logging=True)
        assert config['settings']['crisp_gpu_backend']=='cuda'
        folder=Path(config['settings']['cache_dir'])/'pipeline'/uid()
        state=create_run(config,folder)
        state['stages']=[s for s in state['stages'] if s['id']=='audio' or s['id'].startswith('asr-')]
        write_json(folder/'manifest.json',state)
        monitor=GpuTelemetry(folder/'manifest.json',output/f'gpu-{iteration}.json');monitor.start()
        try:
            with pipeline_lock(folder):
                runner=PipelineRunner(folder/'manifest.json',lambda kind,**data:None)
                audio=runner.stage('audio',runner.audio)['audio']
                for i,item in enumerate(models):
                    print('CUDA:',iteration+1,item['name'],flush=True)
                    result=runner.stage(f'asr-{i}',lambda f,item=item:runner.asr(f,item,audio))
                    track=track_from(result['track'])
                    export_srt(track,output/f'{iteration}-{i}.srt')
                    step=runner.state['stages'][i+1]
                    results.append(dict(iteration=iteration,model=item['model'],seconds=step['seconds'],
                        cues=len(track.segments),manifest=str(folder/'manifest.json'),stage=step['id']))
                    print(results[-1],flush=True)
                runner.state.update(status='completed');runner.save()
        finally:
            monitor.close()
            atomic_text(output/'timings.json',json.dumps({'scope':'ASR-only CUDA AB/BA, same complete video, FP16 and VAD',
                'media':base['media'],'media_seconds':base['duration']/1000,'results':results},indent=2))
    means={name:sum(r['seconds'] for r in results if r['model']==name)/2 for name in (whisper['model'],kotoba['model'])}
    print('Mean seconds:',means, 'speedup:',means[whisper['model']]/means[kotoba['model']],flush=True)


if __name__=='__main__': main()

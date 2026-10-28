"""Verify scan/review v2 on the existing full street-interview recording."""
import hashlib
import argparse
from pathlib import Path
import time

from studio.core import Project,ProjectStore,now
from studio.pipeline import load_run,track_from
from studio.pipeline_worker import read_json,write_json
from studio.storage import Settings
from tools.benchmark_asr_fusion import MODELS,inspect_asr
from tools.compare_easy_frames import compare
from tools.verify_asr_scan import run_v2
from tools.verify_pipeline import audit_result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('D:/models/.cache/verification-asr-scan-v2-easy'))
    parser.add_argument('--reuse-manifest',type=Path)
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    baseline_manifest=Path('D:/models/.cache/pipeline/841464cecf4343fa9f1217ed29d341fc/manifest.json')
    auxiliary_manifest=Path('D:/models/.cache/pipeline/62971396a9344677ad9863ae0584dbc1/manifest.json')
    config=load_run(baseline_manifest)['config'];media=Path(config['media'])
    sample={'id':'easy-full','audio':str(media),'audio_sha256':hashlib.sha256(media.read_bytes()).hexdigest(),
            'source_range_ms':[0,config['duration']]}
    protocol={'input':sample,'baseline':str(baseline_manifest),'auxiliary':str(auxiliary_manifest),
        'policy_sha256':{name:hashlib.sha256(Path('studio',name+'.py').read_bytes()).hexdigest()
                        for name in ('asr_disagreement','asr_retry','asr_review','pipeline_worker')}}
    if (output/'protocol.json').exists() and read_json(output/'protocol.json')!=protocol:raise ValueError('Changed frozen movie experiment')
    write_json(output/'protocol.json',protocol)
    baseline=inspect_asr(baseline_manifest,sample,MODELS[0],True)
    auxiliary=inspect_asr(auxiliary_manifest,sample,MODELS[1],True)
    started=time.perf_counter();result=run_v2(sample,baseline,auxiliary,Settings.load(),output,args.reuse_manifest)
    manifest=Path(result['manifest']);state=audit_result(manifest)
    write_json(output/'comparison.json',{k:v for k,v in result.items() if k!='review'}|{
        'new_work_wall_seconds':round(time.perf_counter()-started,3),
        'baseline_seconds_reused':baseline['original_seconds'],'scan_seconds_reused':auxiliary['original_seconds'],
        'automatic_phrase_changes':len(result['review']['changes']),'changed_cues':result['review']['changed_cues'],
        'scope':'Full recording; cached baseline/auxiliary plus new retries. No complete independent reference SRT.'})
    write_json(output/'creator-frame-comparison.json',compare(manifest))
    project=Project(name='KoeSub • scan review v2',media=str(media),duration=config['media_duration'],
                    review_settings=config['review_settings'])
    for key in ('asr-0','asr-scan','asr-retry','jp-review','jp-layout'):
        value=read_json(manifest.parent/key/'result.json')
        if 'track' in value:project.add_track(track_from(value['track']))
    project.active_track=state['final_track']
    project.jobs=[{'id':state['id'],'type':'pipeline','manifest':str(manifest),'status':state['status'],'created':now()}]
    ui=output/'ui';path=ui/'projects'/project.active.id/'project.sqlite'
    if not path.exists():ProjectStore(path).save(project,'scan review v2 benchmark')
    write_json(ui/'last_project.json',{'path':str(path)})
    print('Movie result:',{k:v for k,v in read_json(output/'comparison.json').items() if k!='hypothesis_jp'},flush=True)


if __name__=='__main__':main()

"""Replay source review from verified completed CUDA ASR artifacts, without decoding.

Creates a separate pipeline/project. Original manifests, audio and models remain
in place. Reused ASR durations and their origins are recorded separately.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import time

from studio.core import Project, ProjectStore, uid, now
from studio.pipeline import create_run, digest, load_run, track_from
from studio.pipeline_worker import read_json, write_json, run_pipeline


def replay(source, data_dir):
    source=Path(source).resolve();data_dir=Path(data_dir).resolve()
    original=load_run(source)
    if not original['config'].get('transcription_only') or not original['config'].get('retry_asr',{}).get('enabled'):
        raise ValueError('Wymagany ukończony przebieg JP z ponowieniami audio.')
    if original['config']['settings']['crisp_gpu_backend']!='cuda':
        raise ValueError('Ten test porównuje wcześniej zapisane wyniki CUDA.')
    cached={}
    for key in ('audio','asr-0','asr-retry'):
        stage=next(s for s in original['stages'] if s['id']==key)
        if stage['status']!='completed': raise ValueError('Nieukończony etap: '+key)
        value=read_json(stage['artifact'])
        if digest(value)!=stage['digest']: raise ValueError('Zmieniono zapisany wynik: '+key)
        cached[key]=(stage,value)
    data_dir.mkdir(parents=True,exist_ok=True)
    run_id=uid();folder=data_dir/'runs'/run_id
    config=deepcopy(original['config'])
    config.update(source_review_version=1,output_dir=str(data_dir/'exports'/run_id))
    state=create_run(config,folder)
    state['replayed_from']=str(source)
    for stage in state['stages']:
        if stage['id'] not in cached: continue
        previous,value=cached[stage['id']]
        target=folder/stage['id']/'result.json';target.parent.mkdir()
        write_json(target,value)
        stage.update(status='completed',artifact=str(target),digest=digest(value),seconds=0,
            reused_from=previous['artifact'],reused_seconds=previous.get('seconds',0),started=now(),finished=now())
    write_json(folder/'manifest.json',state)
    started=time.perf_counter()
    run_pipeline(folder/'manifest.json',lambda kind,**data:print(data['message'],flush=True) if kind=='phase' else None)
    elapsed=time.perf_counter()-started
    final_state=load_run(folder/'manifest.json')
    base=track_from(cached['asr-0'][1]['track'])
    review=read_json(folder/'jp-review/result.json')
    final=track_from(read_json(folder/'jp-layout/result.json')['track'])
    if [(s.start,s.end) for s in base.segments]!=[(s.start,s.end) for s in final.segments]:
        raise AssertionError('Review zmieniło czasy.')
    project=Project(name='Easy Japanese • review fraz JP',media=config['media'],duration=config['media_duration'],
        audio_track=config['audio_track'],review_settings=config['review_settings'])
    for track in (base,track_from(review['track']),final): project.add_track(track)
    project.active_track=final.id
    project.jobs=[{'id':run_id,'type':'pipeline','manifest':str(folder/'manifest.json'),
                   'status':final_state['status'],'created':now()}]
    project_path=data_dir/'projects'/project.active.id/'project.sqlite'
    ProjectStore(project_path).save(project,'cached ASR source review comparison')
    write_json(data_dir/'last_project.json',{'path':str(project_path)})
    comparison={'source':str(source),'manifest':str(folder/'manifest.json'),'project':str(project_path),
        'mode':'Cached CUDA ASR replay; no new model or GPU calls','wall_seconds':round(elapsed,4),
        'review_seconds':next(s['seconds'] for s in final_state['stages'] if s['id']=='jp-review'),
        'fragments':len(review['fragments']),'changes':len(review['changes']),'changed_cues':review['changed_cues'],
        'timings_unchanged':True,'decisions':review['changes'],
        'reused_stages':[{k:s[k] for k in ('id','reused_from','reused_seconds')} for s in final_state['stages'] if 'reused_from' in s]}
    write_json(data_dir/'comparison.json',comparison)
    print(f'Frazy: {comparison["fragments"]}; zmiany: {comparison["changes"]}; napisy: {comparison["changed_cues"]}; review: {comparison["review_seconds"]} s',flush=True)
    print('Manifest:',folder/'manifest.json',flush=True)
    return comparison


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--data-dir',required=True,type=Path)
    args=parser.parse_args();replay(args.source,args.data_dir)


if __name__=='__main__': main()

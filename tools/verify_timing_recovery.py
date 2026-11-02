"""Replay a saved rejected ASR hypothesis through automatic timing review.

The original failed experiment remains immutable. Only timing review and export
are new work; local native retries, if required, are counted separately.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import sys
import time

from studio.audio_boundaries import audio_digest
from studio.core import load_srt
from studio.pipeline import create_run,digest,load_run,track_from
from studio.pipeline_worker import PipelineRunner,read_json,write_json,run_pipeline
from studio.timing_review import timing_issues
from tools.verify_pipeline import audit_result
from tools.verify_long_whisper import save_project


def recover(source,output):
    old=load_run(source);native=source.parent/'asr-0'
    files=list(native.glob('*.srt'))
    if len(files)!=1:raise ValueError('Choose an unambiguous saved native SRT')
    preserved=[source,native/'engine.log',files[0]]
    hashes={str(p):audio_digest(p) for p in preserved}
    config=deepcopy(old['config']);config.update(asr_timing_review={'enabled':True,'max_targets':8},output_dir=str(output/'exports'))
    manifest=output/'run/manifest.json'
    if manifest.exists():raise ValueError('Use a new recovery directory')
    state=create_run(config,manifest.parent);runner=PipelineRunner(manifest,lambda *a,**k:None)
    log=(native/'engine.log').read_text('utf8',errors='replace')
    raw=runner.parse_asr(native,config['asr'][0],log,config['start'],config['duration'])
    assert raw.get('timing_review_pending')
    for key,value in [('audio',read_json(source.parent/'audio/result.json')),('asr-0',raw)]:
        stage=next(s for s in state['stages'] if s['id']==key);target=manifest.parent/key/'result.json';write_json(target,value)
        prior=next(s for s in old['stages'] if s['id']==key)
        stage.update(status='completed',artifact=str(target),digest=digest(value),seconds=0,original_seconds=prior.get('seconds',0),
            replayed_from=str(files[0] if key=='asr-0' else source.parent/'audio/result.json'))
    write_json(manifest,state);started=time.monotonic()
    run_pipeline(manifest,lambda kind,**data:print(data['message'],flush=True) if kind=='phase' else None)
    state=audit_result(manifest)
    timing=read_json(manifest.parent/'asr-timing-review/result.json');final=track_from(read_json(manifest.parent/'jp-layout/result.json')['track'])
    assert not timing_issues(final,config['start'],config['start']+config['duration'])
    incoming=track_from(raw['track'])
    assert ''.join(c.text for c in incoming.segments).replace('\n','')==''.join(c.text for c in final.segments).replace('\n','')
    assert hashes=={str(p):audio_digest(p) for p in preserved}
    before=[(s['id'],s['digest'],s['seconds']) for s in state['stages']]
    run_pipeline(manifest,lambda *a,**k:None);resumed=read_json(manifest)
    assert before==[(s['id'],s['digest'],s['seconds']) for s in resumed['stages']]
    summary={'manifest':str(manifest),'seconds_new_work':round(time.monotonic()-started,3),'cached_source':str(source),
        'before_cues':len(incoming.segments),'after_cues':len(final.segments),'repairs':len(timing['changes']),
        'local_retry_receipts':len(timing['attempts']),'new_native_processes':len(list(manifest.parent.rglob('engine-process.json'))),
        'changes':timing['changes'],'raw_evidence_unchanged':True,'text_preserved':True,'resume_unchanged':True,
        'scope':'Cached long ASR replay with new automatic timing review/export; not fresh long transcription or independent audio quality'}
    write_json(output/'summary.json',summary);save_project(output,state,None)
    print('TIMING RECOVERY',summary['before_cues'],summary['after_cues'],summary['repairs'],summary['seconds_new_work'],flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source-manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();recover(args.source_manifest,args.output)


if __name__=='__main__':main()

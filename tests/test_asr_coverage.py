from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
import wave

import pytest

from studio.asr_coverage import chunk_windows, missing_candidates, recover_gaps, search_coverage
from studio.core import Segment, Track
from studio.pipeline import plan, validate_config
from studio.pipeline_worker import read_json, write_json
from studio.storage import Settings
from tests.test_pipeline import config


def example():
    base=Track('base',[Segment(10000,11000,'最初です。',status='manual'),Segment(17000,18000,'最後です。')])
    cue=Segment(13000,14500,'待ってください。')
    window={'id':'00000','start':10000,'end':20000}
    first={'usable':True,'track':asdict(Track('short',[cue])), 'confidence':{cue.id:{'mean':.92}}}
    peer={'usable':True,'track':asdict(Track('peer',[Segment(13100,14600,cue.text)]))}
    return base,window,first,peer


@pytest.mark.parametrize('duration',[1,15000,30000,30001,122000])
def test_chunks_cover_entire_nonzero_range_with_context_and_no_boundary_trimming(duration):
    windows=chunk_windows(10000,10000+duration)
    assert windows[0]['core_start']==10000 and windows[-1]['core_end']==10000+duration
    assert all(a['core_end']==b['core_start'] for a,b in zip(windows,windows[1:]))
    assert all(10000<=w['start']<=w['core_start']<w['core_end']<=w['end']<=10000+duration for w in windows)
    assert all(a['end']>b['start'] for a,b in zip(windows,windows[1:]))


def test_quiet_cuts_move_core_boundary_without_losing_audio():
    windows=chunk_windows(0,70000,quiet=[[30800,31200]])
    assert windows[0]['core_end']==31000==windows[1]['core_start']
    assert windows[0]['end']==34000 and windows[1]['start']==28000


def test_gap_recovery_keeps_human_work_times_ids_and_raw_hypotheses_exact():
    base,w,first,peer=example();original=deepcopy(asdict(base));hypothesis=deepcopy(first)
    proposals=missing_candidates(base,first,w,10000,20000)
    result=recover_gaps(base,proposals,{w['id']:peer},'large.bin','other.bin')
    assert len(result['changes'])==1 and result['unresolved']==0
    assert asdict(base)==original and first==hypothesis
    retained=[s for s in result['track']['segments'] if s['id'] in {c.id for c in base.segments}]
    assert retained==original['segments']
    added=result['changes'][0]['after']
    assert added['text']=='待ってください。' and (added['start'],added['end'])==(13000,14500)
    assert added['parents']==[first['track']['segments'][0]['id'],peer['track']['segments'][0]['id']]


@pytest.mark.parametrize('change',['disagreement','failed','no_confidence','low_confidence','nan','same_model','distant'])
def test_missing_line_is_not_invented_or_accepted_without_audio_corroboration(change):
    base,w,first,peer=example();other='other.bin'
    cue=first['track']['segments'][0]
    if change=='disagreement':peer['track']['segments'][0]['text']='別の文です。'
    if change=='failed':peer={'usable':False}
    if change=='no_confidence':first['confidence']={}
    if change=='low_confidence':first['confidence'][cue['id']]['mean']=.7
    if change=='nan':first['confidence'][cue['id']]['mean']=float('nan')
    if change=='same_model':other='LARGE.bin'
    if change=='distant':peer['track']['segments'][0].update(start=15000,end=16500)
    result=recover_gaps(base,missing_candidates(base,first,w,10000,20000),{w['id']:peer},'large.bin',other)
    assert not result['changes'] and result['unresolved']==1


def test_gap_search_covers_head_tail_but_declines_existing_text_and_crop_edges():
    base,w,first,peer=example()
    cue=first['track']['segments'][0]
    for left,right,expected in [(10000,10500,False),(11050,12000,False),(9000,9500,True),
                                (19000,19900,True),(12000,12500,True)]:
        cue.update(start=left,end=right)
        assert bool(missing_candidates(base,first,{'id':'x','start':8000,'end':20000},8000,20000))==expected
    cue.update(start=12000,end=13000)
    assert not missing_candidates(base,first,{'id':'x','start':12000,'end':15000},0,20000)


def test_overlap_duplicates_are_deduplicated_but_repeated_real_utterances_survive():
    base,w,first,peer=example();proposals=missing_candidates(base,first,w,10000,20000)
    duplicate=deepcopy(proposals[0]);duplicate['cue'].update(start=13050,end=14550)
    repeated=deepcopy(proposals[0]);repeated['cue'].update(start=15000,end=16500,id='second')
    peer['track']['segments'].append(dict(repeated['cue']))
    result=recover_gaps(base,proposals+[duplicate,repeated],{w['id']:peer},'base','aux')
    assert len(result['changes'])==2 and result['unresolved']==0


def test_conflicting_overlap_is_retained_for_review_instead_of_choosing_first():
    base,w,first,peer=example();proposals=missing_candidates(base,first,w,10000,20000)
    conflict=deepcopy(proposals[0]);conflict['cue']['text']='違う言葉です。'
    result=recover_gaps(base,proposals+[conflict],{w['id']:peer},'base','aux')
    assert not result['changes'] and result['unresolved']==2


@pytest.mark.parametrize('failure',[None,'quality','oom'])
def test_coverage_batches_resume_without_inference_and_detect_receipt_tampering(tmp_path,monkeypatch,failure):
    from studio import source_review_v3
    base,w,first,peer=example();audio=tmp_path/'input.wav'
    with wave.open(str(audio),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*16000*10)
    for name in ('base.bin','aux.bin','third.bin'):(tmp_path/name).write_bytes(b'model fixture')
    baseline={'engine':2,'vad':True,'model':str(tmp_path/'base.bin')}
    auxiliary={'engine':2,'vad':True,'model':str(tmp_path/'aux.bin')}
    third={'engine':1,'vad':True,'model':str(tmp_path/'third.bin')}
    calls=[]
    def decode(runner,root,item,jobs):
        if not jobs:return []
        calls.append((item['vad'],len(jobs)))
        if item==auxiliary and failure=='oom':raise ValueError('CUDA memory failure')
        if item==auxiliary and failure=='quality':return [{'usable':False,'error':'alignment collapse'} for job in jobs]
        return [dict(deepcopy(first if item['model']==baseline['model'] else peer),model=item['model']) for job in jobs]
    monkeypatch.setattr(source_review_v3,'decode_batch',decode)
    def crop(args,folder,name,timeout):
        __import__('pathlib').Path(args[-1]).write_bytes(audio.read_bytes())
    runner=SimpleNamespace(config={'asr_coverage':{'enabled':True},'start':10000,'duration':10000,
        'asr':[baseline],'retry_asr':{'auxiliary':auxiliary,'third':third}},settings=Settings(reserve_gib=0),
        call=crop,event=lambda *a,**k:None,progress=lambda *a:None)
    folder=tmp_path/'coverage';folder.mkdir()
    if failure=='oom':
        with pytest.raises(ValueError,match='CUDA memory'):search_coverage(runner,folder,base,audio)
        assert len(calls)==2
        return
    result=search_coverage(runner,folder,base,audio)
    assert len(result['changes'])==1 and calls==[(False,1),(True,1)]+([(True,1)] if failure else [])
    if failure:
        assert result['changes'][0]['corroborating_model']==third['model'] and len(result['failed_windows'])==1
    assert not list(folder.glob('*/window.wav'))
    count=len(calls)
    assert search_coverage(runner,folder,base,audio)==result and len(calls)==count
    receipt=next(folder.glob('*/baseline/receipt.json'));saved=read_json(receipt)
    saved['result']['track']['segments'][0]['text']='tampered';write_json(receipt,saved)
    with pytest.raises(ValueError,match='coverage receipt'):search_coverage(runner,folder,base,audio)


def test_coverage_plan_is_opt_in_and_validates_models_and_limits(config):
    config.update(transcription_only=True,source_review_version=3,translations=[],asr=[config['asr'][0]],
                  retry_asr={'enabled':True,'auxiliary':{'engine':1,'model':config['settings']['llm_model']}},review='rules')
    config['asr'][0]['vad']=True
    assert 'asr-coverage' not in [s['id'] for s in plan(config)]
    config['asr_coverage']={'enabled':True};validate_config(config)
    keys=[s['id'] for s in plan(config)]
    assert keys.index('asr-0')<keys.index('asr-coverage')<keys.index('asr-retry')
    config['asr_coverage']['chunk_ms']=True
    with pytest.raises(ValueError,match='coverage limit'):validate_config(config)
    config['asr_coverage']['chunk_ms']=30000
    config['retry_asr']['auxiliary']=config['asr'][0]
    with pytest.raises(ValueError,match='distinct auxiliary'):validate_config(config)


def test_recovered_line_survives_complete_jp_export_report_and_replay(config,tmp_path,monkeypatch):
    from studio import asr_coverage
    from studio.pipeline import create_run, load_run
    from studio.pipeline_worker import PipelineRunner, run_pipeline
    from studio.core import load_srt
    base,w,first,peer=example()
    config.update(transcription_only=True,source_review_version=3,translations=[],asr=[config['asr'][0]],
                  retry_asr={'enabled':True,'auxiliary':{'engine':1,'model':config['settings']['llm_model']}},
                  asr_coverage={'enabled':True},review='rules',start=10000,duration=10000,media_duration=20000)
    config['asr'][0]['vad']=True;config['settings']['crisp_vad']=config['settings']['ffmpeg']
    config['settings']['crisp_aligner']=config['settings']['ffmpeg']
    calls=[]
    monkeypatch.setattr(PipelineRunner,'audio',lambda self,folder:{'audio':config['media']})
    monkeypatch.setattr(PipelineRunner,'asr',lambda *a,**k:{'track':asdict(base)})
    def search(*args):
        calls.append('coverage')
        result=recover_gaps(base,missing_candidates(base,first,w,10000,20000),{w['id']:peer},'base','aux')
        return {**result,'windows':[w],'failed_windows':[]}
    monkeypatch.setattr(asr_coverage,'search_coverage',search)
    create_run(config,tmp_path/'run');manifest=tmp_path/'run/manifest.json'
    run_pipeline(manifest,lambda *a,**k:None)
    state=load_run(manifest);report=read_json(tmp_path/'exports/report.json')
    assert state['status']=='needs_review' and all(s['status']=='completed' for s in state['stages'])
    assert state['asr_coverage_added']==1 and len(report['asr_coverage']['changes'])==1
    assert any('Recovered missing-line' in issue for row in report['review'] for issue in row['issues'])
    assert [s.text for s in load_srt(tmp_path/'exports/Japanese.srt').segments]==['最初です。','待ってください。','最後です。']
    run_pipeline(manifest,lambda *a,**k:None)
    assert calls==['coverage']

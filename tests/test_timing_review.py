from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from studio.core import Track,Segment
from studio.pipeline import plan,track_from,validate_config,create_run,load_run
from studio.pipeline_worker import AsrQualityError,PipelineRunner,read_json,run_pipeline
from studio.review import ReviewSettings,review_track
from studio.timing_review import boundary_merge,boundary_prefix_merge,display_recovery,repair_timing,retry_replacement,timing_issues,retry_window
from tests.test_pipeline import config


def test_boundary_repair_preserves_text_source_bounds_and_limits_display_hold():
    base=Track('native',[Segment(1000,2640,'あ'*12),Segment(2640,2640,'ね。'),Segment(4000,5000,'次')])
    before=asdict(base);merged,change=boundary_merge(base,1,ReviewSettings(),6000)
    assert merged.text==base.segments[0].text+base.segments[1].text
    assert (merged.start,merged.end)==(1000,2750)
    assert change['source_end']==2640 and change['display_hold_ms']==110
    assert merged.parents==[c.id for c in base.segments[:2]]
    assert asdict(base)==before


@pytest.mark.parametrize('failure',['manual','reviewed','translated','not_boundary','long_suffix','no_room','too_much_hold','speaker'])
def test_boundary_repair_rejects_protected_or_unsupported_edits(failure):
    base=Track('native',[Segment(0,1640,'あ'*12),Segment(1640,1640,'ね。'),Segment(4000,5000,'次')])
    if failure=='manual':base.segments[0].status='manual'
    elif failure=='reviewed':base.segments[1].review_status='reviewed'
    elif failure=='translated':base.segments[0].translation='Protected translation'
    elif failure=='not_boundary':base.segments[1].start=base.segments[1].end=1641
    elif failure=='long_suffix':base.segments[1].text='あいうえお'
    elif failure=='no_room':base.segments[2].start=1650
    elif failure=='speaker':base.segments[1].text='-A'
    else:base.segments[0].end=base.segments[1].start=base.segments[1].end=50
    assert boundary_merge(base,1,ReviewSettings(),6000) is None


def test_audio_retry_keeps_exact_original_characters_and_uses_only_measured_cue_bounds():
    original=[Segment(100,100,'前。'),Segment(200,200,'次です。')]
    retry=Track('retry',[Segment(100,900,'前'),Segment(950,1700,'次です')])
    result=retry_replacement(original,retry,0,2000)
    assert ''.join(c.text for c in result)==''.join(c.text for c in original)
    assert [(c.start,c.end) for c in result]==[(100,900),(950,1700)]
    retry.segments[1].text='違う';assert retry_replacement(original,retry,0,2000) is None
    retry.segments[1].text='次です';retry.segments[1].start=500
    assert retry_replacement(original,retry,0,2000) is None
    original[0].status='manual';assert retry_replacement(original,Track('x',[]),0,2000) is None


def test_retry_cannot_split_a_casefold_expansion_into_empty_source_captions():
    assert retry_replacement([Segment(0,0,'ß')],Track('retry',[Segment(0,500,'s'),Segment(600,900,'s')]),0,1000) is None


class Runner:
    def __init__(self,root,track,mode='valid'):
        self.config={'start':0,'duration':20000,'asr_timing_review':{'enabled':True,'max_targets':8},'asr':[{'engine':2,'model':'existing.bin'}]}
        self.settings=SimpleNamespace(ffmpeg='fake',whisper_vocal_extract='');self.rules=ReviewSettings();self.calls=0;self.mode=mode
    def event(self,*a,**k):pass
    def call(self,args,folder,name,timeout):
        with wave.open(str(args[-1]),'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0'*32000)
    def retry_decode(self,folder,item,audio,start,end):
        self.calls+=1
        if self.mode=='oom':raise RuntimeError('CUDA out of memory')
        if self.mode=='mixed_error':
            (folder/'engine.log').write_text('no speech detected\nout of memory');raise ValueError('Device failure')
        if self.mode=='quality_oom':
            (folder/'engine.log').write_text('out of memory\nword timestamps required');raise AsrQualityError('Bad timestamps')
        if self.mode=='changed':return {'track':asdict(Track('retry',[Segment(100,1000,'Other text')]))}
        return {'track':asdict(Track('retry',[Segment(100,1200,'前'),Segment(1300,2400,'中央'),Segment(2600,3900,'後')]))}


def fixture_audio(tmp_path):
    audio=tmp_path/'source.wav'
    with wave.open(str(audio),'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0'*32000)
    track=Track('raw',[Segment(0,900,'前'),Segment(2000,2000,'中央'),Segment(3000,4000,'後'),Segment(18000,19000,'outside')])
    return audio,track


def test_local_retry_replaces_only_bounded_context_and_resumes(tmp_path):
    audio,track=fixture_audio(tmp_path);folder=tmp_path/'review';folder.mkdir();runner=Runner(tmp_path,track)
    result=repair_timing(runner,folder,{'track':asdict(track)},audio)
    final=track_from(result['track'])
    assert runner.calls==1 and not timing_issues(final,0,20000)
    assert final.segments[-1].text=='outside' and (final.segments[-1].start,final.segments[-1].end)==(18000,19000)
    assert result['changes'][0]['action']=='text_preserving_audio_retry'
    repair_timing(runner,folder,{'track':asdict(track)},audio);assert runner.calls==1
    audio.write_bytes(audio.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='Changed timing review source'):repair_timing(runner,folder,{'track':asdict(track)},audio)


def test_formal_repairs_do_not_consume_the_expensive_audio_budget(tmp_path):
    audio,_=fixture_audio(tmp_path)
    track=Track('native',[])
    for i in range(4):track.segments += [Segment(i*3000,i*3000+1500,'前'),Segment(i*3000+1500,i*3000+1500,'ね')]
    runner=Runner(tmp_path,track);runner.config['asr_timing_review']['max_targets']=1
    folder=tmp_path/'review';folder.mkdir();result=repair_timing(runner,folder,{'track':asdict(track)},audio)
    assert len(result['changes'])==4 and runner.calls==0 and not result['audio_targets']


def test_partial_timing_edits_without_decision_provenance_are_rejected(tmp_path):
    from studio.pipeline_worker import write_json
    audio,track=fixture_audio(tmp_path);folder=tmp_path/'review';folder.mkdir();runner=Runner(tmp_path,track)
    repair_timing(runner,folder,{'track':asdict(track)},audio)
    partial=read_json(folder/'partial.json');partial['track']['segments'][0]['start']+=1
    write_json(folder/'partial.json',partial)
    with pytest.raises(ValueError,match='Changed timing review checkpoint'):repair_timing(runner,folder,{'track':asdict(track)},audio)


@pytest.mark.parametrize('mode,exception',[('oom',RuntimeError),('mixed_error',ValueError),('quality_oom',RuntimeError),('changed',AsrQualityError)])
def test_operational_failures_stop_and_content_changes_never_become_timing_repairs(tmp_path,mode,exception):
    audio,track=fixture_audio(tmp_path);folder=tmp_path/'review';folder.mkdir();runner=Runner(tmp_path,track,mode)
    if mode=='changed':runner.config['asr_timing_review']['display_fallback']=False
    with pytest.raises(exception):repair_timing(runner,folder,{'track':asdict(track)},audio)
    assert asdict(track)==read_json(folder/'partial.json')['track'] or ''.join(c.text for c in track.segments)==''.join(c['text'] for c in read_json(folder/'partial.json')['track']['segments'])


def test_audio_retry_never_crosses_reviewed_context_but_display_recovery_continues(tmp_path):
    audio,track=fixture_audio(tmp_path);track.segments[0].review_status='reviewed'
    before=asdict(track);runner=Runner(tmp_path,track);folder=tmp_path/'review';folder.mkdir()
    assert retry_window(track,1,6000,0,20000) is None
    result=repair_timing(runner,folder,{'track':asdict(track)},audio)
    recovered=track_from(result['track'])
    preserved=asdict(recovered.segments[0]);source=asdict(track.segments[0])
    for key in ('id','parents'):preserved.pop(key);source.pop(key)
    assert preserved==source and recovered.segments[0].parents==[track.segments[0].id]
    assert result['estimated_display_repairs']==1 and not timing_issues(recovered,0,20000)
    assert runner.calls==0 and asdict(track)==before


def test_raw_invalid_times_are_deferred_with_exact_offset_only_when_review_is_enabled(config,tmp_path):
    config['asr_timing_review']={'enabled':True};config['transcription_only']=True;config['asr']=[{**config['asr'][0],'vad':True}];config['translations']=[]
    config['settings']['crisp_vad']=config['media'];config['media_duration']=20000
    create_run(config,tmp_path/'run');runner=PipelineRunner(tmp_path/'run/manifest.json',lambda *a,**k:None)
    folder=tmp_path/'asr-0';folder.mkdir();(folder/'x.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\na\n\n2\n00:00:03,000 --> 00:00:03,000\nb\n')
    value=runner.parse_asr(folder,config['asr'][0],'',10000,5000)
    assert value['timing_review_pending'] and [(c['start'],c['end']) for c in value['track']['segments']]==[(11000,12000),(13000,13000)]
    runner.config['asr_timing_review']['enabled']=False
    with pytest.raises(AsrQualityError):runner.parse_asr(folder,config['asr'][0],'',10000,5000)


def test_pipeline_repair_reaches_export_and_legacy_plans_remain_unchanged(config,tmp_path,monkeypatch):
    config.update(transcription_only=True,translations=[],source_review_version=None,review='rules',asr_timing_review={'enabled':True})
    config['asr']=[{**config['asr'][0],'vad':True}];config['settings']['crisp_vad']=config['media']
    original=deepcopy(config);original.pop('asr_timing_review')
    assert 'asr-timing-review' not in [s['id'] for s in plan(original)]
    create_run(config,tmp_path/'run');calls=[]
    raw=Track('native',[Segment(100,1740,'あ'*12),Segment(1740,1740,'ね。'),Segment(4000,5000,'次')])
    monkeypatch.setattr(PipelineRunner,'audio',lambda self,f:{'audio':config['media']})
    def asr(self,*args):calls.append('asr');return {'track':asdict(raw),'timing_review_pending':True}
    monkeypatch.setattr(PipelineRunner,'asr',asr)
    path=tmp_path/'run/manifest.json';run_pipeline(path,lambda *a,**k:None);state=load_run(path)
    assert all(s['status']=='completed' for s in state['stages']) and state['asr_timing_repairs']==1
    report=read_json(Path(config['output_dir'])/'report.json')
    assert not report['blocked_exports'] and report['asr_timing_review']['changes']
    assert raw.segments[1].end==raw.segments[1].start
    run_pipeline(path,lambda *a,**k:None);assert calls==['asr']


def test_prefix_merge_keeps_existing_bounds_and_does_not_hide_duration_warnings():
    base=Track('native',[Segment(100,840,'あ'*32),Segment(840,840,'ね。'),Segment(840,7940,'次'*18)])
    before=asdict(base);merged,change=boundary_prefix_merge(base,1,ReviewSettings(),9000)
    assert merged.text==base.segments[1].text+base.segments[2].text
    assert (merged.start,merged.end)==(840,7940) and change['display_hold_ms']==0
    assert merged.parents==[c.id for c in base.segments[1:]] and asdict(base)==before
    assert review_track(Track('merged',[merged]),ReviewSettings(),9000)[0]['issues']
    base.segments[2].status='manual';assert boundary_prefix_merge(base,1,ReviewSettings(),9000) is None


def test_estimated_gap_display_keeps_text_order_and_leaves_neighbours_unchanged():
    base=Track('native',[Segment(2890,4210,'前'*31),Segment(4710,4710,'あいうえおかき'),Segment(5430,7170,'次'*13)])
    before=asdict(base);left,right,cue,change=display_recovery(base,1,ReviewSettings(),0,10000)
    assert (left,right)==(1,2) and (cue.start,cue.end)==(4475,5350)
    assert cue.text==base.segments[1].text and change['requires_listening'] and change['timing_basis']=='estimated_display'
    assert change['before'][0]['start']==change['before'][0]['end']==4710
    assert asdict(base)==before
    issues=review_track(Track('recovered',[cue]),ReviewSettings(),10000)[0]['issues']
    assert 'Estimated display timing; speech boundaries require listening' in issues
    cue.review_status='reviewed'
    assert 'Estimated display timing; speech boundaries require listening' not in review_track(Track('reviewed',[cue]),ReviewSettings(),10000)[0]['issues']


@pytest.mark.parametrize('kind',['first','last','all_zero','overlap','outside','one_ms'])
def test_display_recovery_handles_degenerate_timelines_without_dropping_source(kind):
    tracks={
        'first':([Segment(0,0,'前'),Segment(0,3000,'後')],5000),
        'last':([Segment(0,2000,'前'),Segment(2000,2000,'後')],2000),
        'all_zero':([Segment(0,0,'前'),Segment(0,0,'後')],2000),
        'overlap':([Segment(0,3000,'前'),Segment(1000,2000,'後')],4000),
        'outside':([Segment(-900,-100,'前'),Segment(9000,10000,'後')],5000),
        'one_ms':([Segment(0,0,'前'),Segment(0,0,'後')],1)}
    cues,end=tracks[kind];base=Track('raw',cues);source=''.join(c.text for c in cues);seen=0
    while timing_issues(base,0,end):
        index=timing_issues(base,0,end)[0]['index'];value=display_recovery(base,index,ReviewSettings(),0,end)
        assert value is not None
        left,right,recovered,_=value;base.segments[left:right]=[recovered];seen+=1
        assert seen<=len(cues)
    assert ''.join(c.text for c in base.segments)==source


def test_changed_audio_retry_text_and_exhausted_budget_use_flagged_display_recovery(tmp_path):
    audio,track=fixture_audio(tmp_path);track.segments.insert(3,Segment(8000,8000,'二番目'))
    runner=Runner(tmp_path,track,'changed');runner.config['asr_timing_review']['max_targets']=1
    folder=tmp_path/'review';folder.mkdir();result=repair_timing(runner,folder,{'track':asdict(track)},audio)
    final=track_from(result['track'])
    assert runner.calls==2 and result['estimated_display_repairs']==2 and len(result['audio_targets'])==1
    assert ''.join(c.text for c in final.segments)==''.join(c.text for c in track.segments)
    assert not timing_issues(final,0,20000)
    repair_timing(runner,folder,{'track':asdict(track)},audio);assert runner.calls==2


def test_display_recovery_cannot_change_a_protected_cue_or_cross_protected_barriers():
    base=Track('raw',[Segment(0,1000,'前',status='manual'),Segment(1000,1000,'中'),Segment(1000,2000,'後',review_status='reviewed')])
    before=asdict(base)
    assert display_recovery(base,1,ReviewSettings(),0,2000) is None
    assert display_recovery(base,0,ReviewSettings(),0,2000) is None
    assert asdict(base)==before


def test_pipeline_exports_unverified_display_recovery_as_needs_review(config,tmp_path,monkeypatch):
    config.update(transcription_only=True,translations=[],source_review_version=None,review='rules',
        asr_timing_review={'enabled':True},duration=20000,media_duration=20000)
    config['asr']=[{**config['asr'][0],'vad':True}];config['settings']['crisp_vad']=config['media']
    raw=Track('raw',[Segment(100,1000,'前'),Segment(3000,3000,'あいうえお'),Segment(5000,6000,'後')])
    monkeypatch.setattr(PipelineRunner,'audio',lambda self,f:{'audio':config['media']})
    monkeypatch.setattr(PipelineRunner,'asr',lambda *a:{'track':asdict(raw),'timing_review_pending':True})
    monkeypatch.setattr(PipelineRunner,'retry_decode',lambda *a:{'track':asdict(Track('changed',[Segment(100,200,'Other')]))})
    def crop(self,args,folder,name,timeout):Path(args[-1]).write_bytes(b'WAVE'+b'\0'*100)
    monkeypatch.setattr(PipelineRunner,'call',crop)
    path=tmp_path/'run/manifest.json';create_run(config,path.parent);run_pipeline(path,lambda *a,**k:None)
    state=load_run(path);report=read_json(Path(config['output_dir'])/'report.json')
    assert state['status']=='needs_review' and state['asr_timing_estimated']==1
    assert not report['blocked_exports'] and (Path(config['output_dir'])/'Japanese.srt').is_file()
    assert any('Estimated display timing' in issue for row in report['review'] for issue in row['issues'])
    assert raw.segments[1].start==raw.segments[1].end


def test_resume_of_failed_review_reuses_rejected_audio_receipts_without_duplicate_attempts(tmp_path,monkeypatch):
    import studio.timing_review as timing_module
    audio,track=fixture_audio(tmp_path);runner=Runner(tmp_path,track,'changed');folder=tmp_path/'review';folder.mkdir()
    with monkeypatch.context() as context:
        context.setattr(timing_module,'display_recovery',lambda *a:None)
        with pytest.raises(AsrQualityError):repair_timing(runner,folder,{'track':asdict(track)},audio)
    assert runner.calls==2 and len(read_json(folder/'partial.json')['attempts'])==2
    result=repair_timing(runner,folder,{'track':asdict(track)},audio)
    assert runner.calls==2 and len(result['attempts'])==2 and result['estimated_display_repairs']==1
    assert not timing_issues(track_from(result['track']),0,20000)


@pytest.mark.parametrize('value',[1,'yes',None])
def test_display_recovery_option_requires_a_boolean(config,value):
    config['asr_timing_review']={'enabled':True,'display_fallback':value}
    with pytest.raises(ValueError,match='Invalid display timing fallback option'):validate_config(config)

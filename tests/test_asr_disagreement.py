from dataclasses import asdict

from studio.asr_disagreement import disagreement_targets,reuse_scan
from studio.asr_retry import retry_windows
from studio.asr_review import review_fragments
from studio.core import Segment,Track


def test_high_confidence_disagreement_is_targeted_without_a_reference():
    base=Track('base',[Segment(0,1000,'最初です'),Segment(1100,2500,'明日は雨です'),Segment(2600,4000,'最後です')])
    scan=Track('scan',[Segment(0,1000,'最初です'),Segment(1100,2500,'明日は晴れです'),Segment(2600,4000,'最後です')])
    targets=disagreement_targets(base,scan)
    assert [r['id'] for r in targets]==[base.segments[1].id]
    scores={s.id:{'mean':.99,'low_ratio':0} for s in base.segments}
    assert not retry_windows(base,scores,0,4000)[0]
    windows,_=retry_windows(base,scores,0,4000,additional_targets=targets)
    assert len(windows)==1 and windows[0]['suspects'][0]['signals']==['asr_disagreement']


def test_different_segmentation_and_punctuation_do_not_create_false_targets():
    base=Track('base',[Segment(0,1000,'こんにちは。'),Segment(1000,2000,'日本語です。')])
    scan=Track('scan',[Segment(0,2000,'こんにちは 日本語です！')])
    assert not disagreement_targets(base,scan)
    base.segments[0].status='manual';scan.segments[0].text='別の文です'
    assert base.segments[0].id not in {t['id'] for t in disagreement_targets(base,scan)}


def test_scan_reuse_keeps_real_times_and_declines_partial_target_coverage():
    cue=Segment(1000,2000,'日本語です')
    model={'model':'kotoba.bin','name':'Kotoba'}
    scan={'track':asdict(Track('scan',[cue])),'confidence':{cue.id:{'mean':.9}}}
    window={'start':500,'end':2500,'before':[asdict(cue)],'suspects':[{'id':cue.id}]}
    result=reuse_scan(window,scan,model,'scan-dir')
    assert result['reused_from']=='asr-scan' and result['seconds']==0
    assert [(s['start'],s['end']) for s in result['track']['segments']]==[(1000,2000)]
    window['end']=1500
    assert reuse_scan(window,scan,model,'scan-dir') is None


def test_version_two_requires_real_disagreement_and_independent_retry_support():
    from tests.test_asr_review import example
    base,window,_=example();scores={base.segments[1].id:{'mean':.99,'low_ratio':0}}
    window['suspects']=[{'id':base.segments[1].id,'signals':['asr_disagreement']}]
    assert not review_fragments(base,[window],scores,'large.bin',version=1)['changes']
    assert len(review_fragments(base,[window],scores,'large.bin',version=2)['changes'])==2
    window['attempts']=window['attempts'][:1]
    assert not review_fragments(base,[window],scores,'large.bin',version=2)['changes']


def test_disagreement_budget_cannot_starve_existing_low_confidence_targets():
    cues=[Segment(i*5000,i*5000+1000,'字幕です') for i in range(5)]
    base=Track('base',cues);scores={cues[-1].id:{'mean':.2,'low_ratio':.5}}
    extras=[{'id':c.id,'start':c.start,'end':c.end,'priority':100,'signals':['asr_disagreement'],'reasons':['different']} for c in cues[:3]]
    windows,_=retry_windows(base,scores,0,25000,padding=1000,max_targets=1,additional_targets=extras)
    assert len(windows)==1 and cues[-1].id in windows[0]['cue_ids']


def test_reusing_native_attempts_does_not_create_a_fake_benchmark_speedup(tmp_path):
    from tools.verify_asr_scan import replay_aware_cost
    attempts=[{'seconds':6,'directory':str(tmp_path/'old')},
              {'seconds':3,'directory':str(tmp_path/'new/attempt')},
              {'seconds':0,'directory':str(tmp_path/'scan'),'reused_from':'asr-scan'}]
    assert replay_aware_cost(attempts,tmp_path/'new',4)==10

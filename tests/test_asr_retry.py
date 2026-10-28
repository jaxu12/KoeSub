from dataclasses import asdict
import pytest
from studio.core import Segment,Track
from studio.asr_retry import token_confidence,suspects,retry_windows,consensus


def baseline():
    cues=[Segment(0,1000,'最初の文。'),Segment(1200,2200,'間違った文。'),Segment(2400,3400,'最後の文。')]
    return Track('base',cues)


def test_confidence_uses_token_times_and_ignores_special_tokens():
    track=Track('base',[Segment(10000,11000,'はい')])
    raw={'transcription':[{'offsets':{'from':0,'to':1000},'tokens':[
        {'text':'はい','p':.6,'offsets':{'from':0,'to':1000}}, {'text':'<|end|>','p':0}]}]}
    score=token_confidence(raw,track,10000)[track.segments[0].id]
    assert score=={'mean':.6,'low_ratio':0,'tokens':1}
    assert len(suspects(track,{track.segments[0].id:score}))==1


def test_retry_window_keeps_whole_neighboring_cues_and_respects_budget():
    track=baseline();scores={track.segments[1].id:{'mean':.4,'low_ratio':.3}}
    windows,skipped=retry_windows(track,scores,0,4000,padding=1000,max_window=30000,max_targets=1)
    assert not skipped and len(windows)==1
    assert windows[0]['start']==0 and windows[0]['end']==3400
    assert windows[0]['cue_ids']==[s.id for s in track.segments]
    track.segments[0].status='manual'
    assert not retry_windows(track,scores,0,4000,padding=1000)[0]


@pytest.mark.parametrize('other,confidence,expected',[
    ('正しい文。',.9,True),('別の文。',.9,False),('正しい文。',None,False),('正しい文。',.3,False)])
def test_auxiliary_alone_cannot_replace_baseline(other,confidence,expected):
    track=baseline()
    window={'start':0,'end':3400,'before':[asdict(s) for s in track.segments],
            'suspects':[{'id':track.segments[1].id}]}
    def attempt(middle,score):
        return {'usable':True,'mean_confidence':score,'track':asdict(Track('retry',[
            Segment(0,1000,'最初の文。'),Segment(1200,2200,middle),Segment(2400,3400,'最後の文。')]))}
    a=attempt('正しい文。',confidence);b=attempt(other,.9)
    assert consensus(window,[a,b])[0] is expected
    assert not consensus(window,[b])[0]


def test_context_loss_and_invalid_candidate_timing_are_rejected():
    track=baseline()
    window={'start':0,'end':3400,'before':[asdict(s) for s in track.segments],'suspects':[{'id':track.segments[1].id}]}
    a={'usable':True,'mean_confidence':.9,'track':asdict(Track('retry',[Segment(0,3400,'違う文。正しい文。最後の文。')]))}
    assert not consensus(window,[a,a])[0]
    a['track']['segments'][0]['text']='最初の文。正しい文。最後の文。'
    a['track']['segments'][0]['end']=4000
    assert not consensus(window,[a,a])[0]

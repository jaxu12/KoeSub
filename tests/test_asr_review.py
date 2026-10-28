from copy import deepcopy
from dataclasses import asdict

import pytest

from studio.asr_review import review_fragments
from studio.core import Segment, Track


def example():
    base=Track('Large',[Segment(0,1000,'魚の話です。'),
        Segment(1100,5000,'新鮮な魚を得ても国の開発度が一番良いところですね。'),
        Segment(5100,6000,'日本の食べ物です。')])
    def attempt(model,text):
        cues=[Segment(0,1000,'別の話です。'),Segment(1150,4900,text),Segment(5100,6000,'日本の食べ物です。')]
        return {'usable':True,'model':model,'name':model,'track':asdict(Track(model,cues)),
                'confidence':{s.id:{'mean':.9} for s in cues}}
    attempts=[attempt('large.bin','新鮮な魚いつでも国配列道が一番いいとこですね。'),
              attempt('kotoba.bin','新鮮な魚いつでも国配列堂が一番いいところですね。')]
    window={'id':'fish','start':0,'end':6000,'before':[asdict(s) for s in base.segments],'attempts':attempts}
    scores={base.segments[1].id:{'mean':.77,'low_ratio':.2}}
    return base,window,scores


def test_local_fusion_survives_different_context_but_never_splices_disputed_kanji():
    base,window,scores=example();before=deepcopy(base)
    result=review_fragments(base,[window],scores,'large.bin')
    assert base==before
    assert result['changed_cues']==1 and len(result['changes'])==2
    cues=result['track']['segments']
    assert cues[1]['text']=='新鮮な魚いつでも国の開発度が一番いいところですね。'
    assert [(s['start'],s['end']) for s in cues]==[(s.start,s.end) for s in base.segments]
    assert cues[0]['text']==base.segments[0].text and cues[2]['text']==base.segments[2].text
    assert cues[1]['parents']==[base.segments[1].id] and cues[1]['review_status']=='unreviewed'
    disputed=next(r for r in result['fragments'] if r['before']=='の開発度')
    assert not disputed['applied']
    assert [a['text'] for a in disputed['alternatives']]==['配列道','配列堂']
    assert result['changes'][0]['alternatives'][0]['cue_ids']


@pytest.mark.parametrize('mode',['one_model','same_model','no_confidence','low_retry','strong_base','manual','reviewed','bad_timing','wrong_base_model'])
def test_weak_or_protected_evidence_cannot_change_text(mode):
    base,window,scores=example();attempts=window['attempts']
    if mode=='one_model': window['attempts']=attempts[1:]
    if mode=='same_model': attempts[1]['model']='large.bin'
    if mode=='no_confidence': attempts[0]['confidence']={}
    if mode=='low_retry':
        for score in attempts[0]['confidence'].values(): score['mean']=.7
    if mode=='strong_base': scores={}
    if mode=='manual': base.segments[1].status='manual'
    if mode=='reviewed': base.segments[1].review_status='reviewed'
    if mode=='bad_timing': attempts[1]['track']['segments'][1]['end']=6500
    model='other.bin' if mode=='wrong_base_model' else 'large.bin'
    result=review_fragments(base,[window],scores,model)
    assert not result['changes']
    assert [s['text'] for s in result['track']['segments']]==[s.text for s in base.segments]


def test_stale_source_is_rejected_instead_of_patching_wrong_offsets():
    base,window,scores=example();base.segments[1].text='Zmieniono tekst'
    with pytest.raises(ValueError,match='źródła'): review_fragments(base,[window],scores,'large.bin')


def test_missing_or_inserted_boundary_content_is_visible_but_never_auto_added():
    base,window,scores=example()
    for attempt in window['attempts']:
        attempt['track']['segments'][0]['text']='追加'+base.segments[0].text
        attempt['track']['segments'][-1]['text']+='追加'
    result=review_fragments(base,[window],scores,'large.bin')
    added=[r for r in result['fragments'] if r['before']=='']
    assert len(added)==2 and not any(r['applied'] for r in added)
    assert result['track']['segments'][0]['text']==base.segments[0].text


def test_cross_cue_changes_remain_visible_and_keep_times():
    base,window,scores=example()
    for attempt in window['attempts']:
        attempt['track']['segments']=[asdict(Segment(0,6000,'全然違う内容です。'))]
    result=review_fragments(base,[window],scores,'large.bin')
    assert result['fragments'] and not result['changes']
    assert any(' granice ' in r['reason'] for r in result['fragments'])


def test_a_third_disagreeing_model_blocks_local_majority_change():
    base,window,scores=example()
    third=deepcopy(window['attempts'][1]);third['model']='qwen.gguf'
    third['track']['segments'][1]['text']=base.segments[1].text
    window['attempts'].append(third)
    result=review_fragments(base,[window],scores,'large.bin')
    assert not result['changes']


def test_unanchored_short_utterance_is_a_proposal_even_if_models_agree():
    base=Track('base',[Segment(0,2000,'熊谷もなです')])
    def attempt(model):
        cue=Segment(0,2000,'熊谷モナです')
        return {'usable':True,'model':model,'track':asdict(Track(model,[cue])), 'confidence':{cue.id:{'mean':.95}}}
    window={'id':'name','start':0,'end':2000,'before':[asdict(s) for s in base.segments],
            'attempts':[attempt('large.bin'),attempt('kotoba.bin')]}
    result=review_fragments(base,[window],{base.segments[0].id:{'mean':.4}},'large.bin')
    assert result['fragments'] and not result['changes']

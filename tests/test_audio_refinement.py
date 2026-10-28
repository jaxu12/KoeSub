from copy import deepcopy
from dataclasses import asdict
import math
import wave
from array import array

import pytest

from studio.audio_boundaries import quiet_regions,context_window
from studio.audio_alignment import apply_alignment,aligned_words,split_aligned
from studio.asr_review import review_fragments
from studio.core import Track,Segment,normalize
from studio.review import ReviewSettings
from studio.pipeline import track_from


def entry(text,start,end,words=None):
    return {'text':text,'start':start/1000,'end':end/1000,
        'words':words or [{'word':text,'start':start/1000,'end':end/1000}]}


def test_quiet_hints_and_whole_cue_context_do_not_trim_speech_or_enter_protected_cues(tmp_path):
    path=tmp_path/'audio.wav'
    with wave.open(str(path),'wb') as audio:
        audio.setparams((1,2,16000,0,'NONE','not compressed'))
        audio.writeframes(array('h',[0]*16000+[1000]*16000+[0]*16000).tobytes())
    regions=quiet_regions(path)
    assert regions==[[0,1000],[2000,3000]]
    track=Track('test',[Segment(1100,1900,'魚が好きです。')]);cue=track.segments[0]
    window=context_window(track,cue,700,0,3000,regions)
    assert window['start']<=cue.start and window['end']>=cue.end
    assert window['quiet_left'] and window['quiet_right']
    cue.review_status='reviewed'
    assert context_window(track,cue,700,0,3000,regions) is None


@pytest.mark.parametrize('bad',['nan','negative','huge_shift','words_missing','different_text','overlap_words','all_zero'])
def test_bad_alignment_keeps_all_original_text_and_times(bad):
    base=Track('base',[Segment(2000,4000,'日本語です。')]);original=deepcopy(base)
    value=entry(base.segments[0].text,2100,3900)
    if bad=='nan':value['start']=float('nan')
    if bad=='negative':value['start']=-1
    if bad=='huge_shift':value=entry(base.segments[0].text,5000,7000)
    if bad=='words_missing':value['words']=[]
    if bad=='different_text':value['text']='別の文章'
    if bad=='overlap_words':value['words']=[{'word':'日本','start':2.1,'end':3.2},{'word':'語です。','start':3,'end':3.9}]
    if bad=='all_zero':value['words']=[{'word':base.segments[0].text,'start':2.1,'end':2.1}]
    result=apply_alignment(base,[value],0,10000,ReviewSettings(),{'split':True})
    assert not result['changes']
    assert [(s['start'],s['end'],s['text']) for s in result['track']['segments']]==[(s.start,s.end,s.text) for s in base.segments]
    assert base==original


def test_alignment_selects_nonoverlapping_path_and_never_moves_a_protected_neighbour():
    base=Track('base',[Segment(0,2000,'最初です。'),Segment(2000,4000,'手で確認。'),Segment(4100,6000,'最後です。')])
    base.segments[1].status='manual'
    values=[entry('最初です。',100,2300),entry('手で確認。',2400,4100),entry('最後です。',4200,5900)]
    result=apply_alignment(base,values,0,6500,ReviewSettings(),{'split':False})
    cues=result['track']['segments']
    assert (cues[0]['start'],cues[0]['end'])==(0,2000)
    assert (cues[1]['start'],cues[1]['end'],cues[1]['status'])==(2000,4000,'manual')
    assert (cues[2]['start'],cues[2]['end'])==(4200,5900)
    assert len(result['changes'])==1


def test_adjacent_zero_tokens_are_coalesced_without_creating_synthetic_intervals():
    cue=Segment(1000,5000,'これは日本語です。')
    words=[{'word':'これ','start':1,'end':1.8},{'word':'は','start':1.8,'end':1.8},
           {'word':'日本語','start':2,'end':3.4},{'word':'です。','start':3.4,'end':4.8}]
    start,end,aligned=aligned_words(cue,entry(cue.text,1000,4800,words),0,6000)
    assert aligned[0]['text']=='これは' and (aligned[0]['start'],aligned[0]['end'])==(1000,1800)
    assert normalize(''.join(w['text'] for w in aligned))==normalize(cue.text)
    words[1].update(start=1.9,end=1.9)
    with pytest.raises(ValueError,match='Unattached'):aligned_words(cue,entry(cue.text,1000,4800,words),0,6000)


def test_aligned_split_preserves_every_character_and_uses_only_measured_boundaries():
    first='今日はとても良い天気なので散歩に行きます。'
    second='明日は友達と一緒に買い物へ出かける予定です。'
    cue=Segment(1000,11000,first+second);base=Track('base',[cue])
    words=[{'word':first,'start':1.1,'end':5.4},{'word':second,'start':5.8,'end':10.8}]
    result=apply_alignment(base,[entry(cue.text,1100,10800,words)],0,12000,ReviewSettings(),{'split':True})
    cues=result['track']['segments']
    assert len(cues)==2 and ''.join(c['text'] for c in cues)==cue.text
    assert [(c['start'],c['end']) for c in cues]==[(1100,5400),(5800,10800)]
    assert all(c['parents']==[cue.id] for c in cues)
    assert result['split_cues']==1 and base.segments[0].text==first+second
    # One long unsegmented word provides no safe acoustic split point.
    assert split_aligned(cue,[{'text_start':0,'text_end':len(cue.text),'start':1100,'end':10800}],ReviewSettings()) is None


def test_nonzero_pipeline_offset_and_translated_cues_do_not_lose_text():
    cue=Segment(11000,16000,'長い日本語の文章です。',translation='Existing translation')
    result=apply_alignment(Track('base',[cue]),[entry(cue.text,1200,5800)],10000,8000,ReviewSettings(),{'split':True})
    value=result['track']['segments'][0]
    assert (value['start'],value['end'])==(11200,15800) and value['translation']==cue.translation


def test_same_weights_and_one_context_cannot_impersonate_independent_adaptive_agreement():
    from tests.test_asr_review import example
    base,window,scores=example()
    agreed=deepcopy(window['attempts'][0])
    window['attempts']=[]
    for model in ('large.bin','kotoba.bin'):
        for context in ('short','wide'):
            attempt=deepcopy(agreed);attempt.update(model=model,context_variant=context);window['attempts'].append(attempt)
    result=review_fragments(base,[window],scores,'large.bin',version=2,context_consistency=True)
    assert result['changes']
    window['attempts'][-1]['context_variant']='short'
    assert not review_fragments(base,[window],scores,'large.bin',version=2,context_consistency=True)['changes']
    window['attempts'][-1]['context_variant']='wide'
    for score in window['attempts'][1]['confidence'].values():score['mean']=.6
    assert not review_fragments(base,[window],scores,'large.bin',version=2,context_consistency=True)['changes']


def test_alignment_does_not_create_a_faster_reading_problem_and_records_display_hold():
    cue=Segment(0,2000,'おはようです。')
    result=apply_alignment(Track('base',[cue]),[entry(cue.text,500,1000)],0,3000,ReviewSettings(),{'split':False})
    record=result['records'][0];target=result['track']['segments'][0]
    assert record['applied'] and record['proposal']['speech_end']==1000
    assert 0<record['proposal']['display_hold_ms']<=600
    assert len(cue.text)*1000/(target['end']-target['start'])<=8.001
    longer=Segment(0,2000,'これは大切な文章です。')
    rejected=apply_alignment(Track('base',[longer]),[entry(longer.text,500,1000)],0,3000,ReviewSettings(),{'split':False})
    assert not rejected['changes'] and 'reading exposure' in rejected['records'][0]['reason']

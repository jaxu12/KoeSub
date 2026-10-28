import copy
from dataclasses import asdict
import pytest

from studio.core import Segment,Track,export_subtitles,load_subtitles,merge_segments
from studio.editing import processing_digest,propose_cleanup,shift_track
from studio.review import ReviewSettings
from studio.waveform import load_peaks,save_peaks,source_key


def test_shift_selected_is_atomic_preserves_duration_and_rejects_negative():
    track=Track('JP',[Segment(1000,2000,'はい。'),Segment(3000,4500,'いえ。')])
    shifted=shift_track(track,500,[1])
    assert (shifted.segments[0].start,shifted.segments[1].start)==(1000,3500)
    assert shifted.segments[1].end-shifted.segments[1].start==1500
    assert shifted.segments[1].id==track.segments[1].id
    with pytest.raises(ValueError): shift_track(track,-2000)
    assert track.segments[0].start==1000


def test_cleanup_merges_only_conservative_pairs_and_preserves_bilingual_source():
    a,b=Segment(0,400,'はい',translation='Yes.'),Segment(450,2000,'そうです。',translation='That is right.')
    track=Track('JP',[a,b])
    result,changes,_=propose_cleanup(track,ReviewSettings(),merge_short=True)
    assert len(result.segments)==1 and changes
    assert result.segments[0].parents==[a.id,b.id]
    assert 'Yes.' in result.segments[0].translation and 'right.' in result.segments[0].translation
    assert len(track.segments)==2
    b.text='- そうです。'
    assert len(propose_cleanup(track,ReviewSettings(),merge_short=True)[0].segments)==2
    b.text='そうです。';b.translation=''
    assert len(propose_cleanup(track,ReviewSettings(),merge_short=True)[0].segments)==2
    with pytest.raises(ValueError,match='częściowy EN'): merge_segments([a,b])


def test_technical_time_preview_does_not_guess_when_no_space_or_rate_too_high():
    original=Track('JP',[Segment(1000,1000,'はい'),Segment(3000,4500,'次です。')])
    result,changes,unresolved=propose_cleanup(original,ReviewSettings(),5000,timing=True)
    assert result.segments[0].end>1000 and changes and not unresolved
    assert any('odsłuch' in n for n in result.segments[0].notes)
    assert original.segments[0].end==1000
    overlap=Track('JP',[Segment(0,2000,'長い'*40,translation='Long '*40),Segment(1900,3000,'次。')])
    assert propose_cleanup(overlap,ReviewSettings(),4000,timing=True)[0].segments[0].end==2000
    bad=Track('bad',[Segment(-100,0,'はい'),Segment(1000,1000,'長い'*40),Segment(1100,2000,'次')])
    fixed,_,unresolved=propose_cleanup(bad,ReviewSettings(),3000,timing=True)
    assert fixed.segments[0].start==-100 and fixed.segments[1].end==1000 and len(unresolved)==2


def test_human_annotations_are_saved_but_not_pipeline_processing_changes():
    track=Track('JP',[Segment(0,2000,'はい',translation='Yes.')])
    key=processing_digest(track)
    track.segments[0].comment='Check speaker'
    track.segments[0].bookmarked=True;track.segments[0].review_status='reviewed'
    assert processing_digest(track)==key
    track.segments[0].translation='No.'
    assert processing_digest(track)!=key


@pytest.mark.parametrize('extension',['ass','ssa','srt'])
def test_subtitle_export_roundtrip_and_english_validation(tmp_path,extension):
    track=Track('JA',[Segment(1200,2500,'こんにちは。\nはい。',translation='Hello.\nYes.')])
    path=tmp_path/('JP.'+extension)
    export_subtitles(track,path)
    recovered=load_subtitles(path)
    assert (recovered.segments[0].start,recovered.segments[0].end,recovered.segments[0].text)==(1200,2500,track.segments[0].text)
    export_subtitles(track,tmp_path/'EN.txt',True)
    assert 'Hello.' in (tmp_path/'EN.txt').read_text('utf8')
    track.segments[0].translation=''
    with pytest.raises(ValueError,match='Brakuje'): export_subtitles(track,path,True)


def test_compact_waveform_cache_fingerprints_and_validation(tmp_path):
    media=tmp_path/'test.wav';media.write_bytes(b'fixture')
    key=source_key(media,0)
    assert source_key(media,1)!=key
    path=tmp_path/'peaks.json'
    save_peaks(path,key,bytes([0,40,255]),240)
    peaks,duration=load_peaks(path,key)
    assert peaks==bytes([0,40,255]) and duration==60
    with pytest.raises(ValueError): load_peaks(path,'other source')
    save_peaks(path,key,b'wrong count',1)
    with pytest.raises(ValueError): load_peaks(path,key)
    media.write_bytes(b'different source')
    assert source_key(media,0)!=key


def test_cache_cleanup_never_deletes_models_checkpoints_or_unselected_files(tmp_path):
    from studio.cache_tools import candidates,delete_cache
    root=tmp_path/'cache';root.mkdir()
    audio=root/('audio-'+'a'*24+'.wav');audio.write_bytes(b'cached audio')
    model=root/'Qwen3.gguf';model.write_bytes(b'GGUFmodel')
    pipeline=root/'pipeline';pipeline.mkdir();(pipeline/'manifest.json').write_text('{}')
    peaks=root/'waveforms';peaks.mkdir();peak=peaks/('b'*64+'.json');peak.write_text('{}')
    assert set(candidates(root))=={audio,peak}
    with pytest.raises(ValueError): delete_cache(root,[audio,model])
    assert audio.exists() and model.exists()
    freed,errors=delete_cache(root,[audio])
    assert freed==len(b'cached audio') and not errors and not audio.exists()
    assert peak.exists() and model.exists() and (pipeline/'manifest.json').exists()

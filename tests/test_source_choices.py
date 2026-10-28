from copy import deepcopy

import pytest

from studio.asr_review import review_fragments
from studio.core import Project
from studio.pipeline import clone_track,track_from
from studio.source_choices import choice_preview


def setup():
    from tests.test_asr_review import example
    base,window,scores=example();result=review_fragments(base,[window],scores,'large.bin')
    reviewed=track_from(result['track']);final=clone_track(reviewed,'final')
    project=Project();project.add_track(base);project.add_track(reviewed);project.add_track(final)
    row=next(i for i,f in enumerate(result['fragments']) if f['before']=='の開発度')
    return project,result,row,{}


def test_explicit_choice_modifies_only_the_selected_phrase_and_keeps_timing():
    project,result,row,job=setup();before=deepcopy(project.to_dict())
    preview=choice_preview(project,result,row,1,job)
    assert '国配列堂' in preview['text']
    assert 'いつでも' in preview['text']  # previous automatic edit is preserved
    assert project.to_dict()==before
    assert preview['record']['model']=='kotoba.bin'


@pytest.mark.parametrize('change',['manual','reviewed','text','time'])
def test_stale_or_previously_approved_text_cannot_be_overwritten(change):
    project,result,row,job=setup();cue=project.active.segments[1]
    if change=='manual':cue.status='manual'
    if change=='reviewed':cue.review_status='reviewed'
    if change=='text':cue.text+='変更'
    if change=='time':cue.end+=1
    with pytest.raises(ValueError):choice_preview(project,result,row,1,job)


def test_multiple_human_choices_and_reverting_to_baseline_are_consistent():
    project,result,row,job=setup();preview=choice_preview(project,result,row,1,job)
    target=preview['target'];target.text=preview['text'];target.status='manual'
    job['manual_source_choices']=[preview['record']]
    again=choice_preview(project,result,row,-1,job)
    assert '国の開発度' in again['text'] and 'いつでも' in again['text']
    assert choice_preview(project,result,row,1,job) is None


def test_unrelated_active_track_is_not_a_valid_edit_target():
    project,result,row,job=setup()
    for cue in project.active.segments:cue.parents=[]
    with pytest.raises(ValueError,match='active track'):choice_preview(project,result,row,1,job)


def test_original_asr_track_is_never_modified_by_the_review_choice_action():
    project,result,row,job=setup();project.active_track=project.tracks[0].id
    with pytest.raises(ValueError,match='active track'):choice_preview(project,result,row,1,job)

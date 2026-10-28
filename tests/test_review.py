from dataclasses import asdict

import pytest

from studio.core import Project, ProjectStore, Segment, Track, split_segment
from studio.review import (ReviewSettings, char_count, metrics, reflow_english,
                           review_track, split_position, split_proposal)


def test_review_speed_and_line_overflow_are_independent():
    fast = Segment(0, 1000, 'はい。', translation='A short sentence is still too fast to read in one second.')
    long_line = Segment(2000, 8000, 'はい。', translation='This is a long single line but it has enough reading time.')
    rows = review_track(Track('test', [fast, long_line]), ReviewSettings())
    assert any('EN: za szybko' in issue for issue in rows[0]['issues'])
    assert not any('EN: za szybko' in issue for issue in rows[1]['issues'])
    assert any('EN: długi wiersz' in issue for issue in rows[1]['issues'])
    assert 'sam podział nie obniża' in rows[0]['advice']
    assert rows[0]['needed'] > rows[0]['duration']


def test_timing_checks_nested_unsorted_overlap_gaps_and_media_end():
    # The long first interval still overlaps the third interval; checking just its predecessor misses this.
    rows = review_track(Track('test', [Segment(2000, 3000, 'はい'), Segment(0, 10000, 'はい'),
                                       Segment(1000, 1500, 'はい'), Segment(10050, 11000, 'はい'),
                                       Segment(11040, 12000, 'はい')]), ReviewSettings(), 11500)
    assert all('Nakładanie napisów' in rows[i]['issues'] for i in (0, 1, 2))
    assert 'Mała przerwa: 50 ms' in rows[1]['issues']
    assert 'Mała przerwa: 40 ms' in rows[3]['issues']
    assert 'Koniec poza filmem' in rows[4]['issues']
    assert 'Nieprawidłowy czas' in review_track(Track('bad', [Segment(0, 0, 'はい')]), ReviewSettings())[0]['issues']


def test_counts_markup_unicode_and_empty_en():
    assert char_count('<i>Cafe\u0301</i>\nはい') == 6
    result = metrics('A B\nC', 2000)
    assert result == {'chars': 4, 'lines': 2, 'line': 3, 'cps': 2}
    row = review_track(Track('empty en', [Segment(0, 2000, 'はい')]), ReviewSettings())[0]
    assert row['en']['chars'] == 0 and not any(i.startswith('EN:') for i in row['issues'])


def test_custom_limits_and_project_persistence(tmp_path):
    p = Project(review_settings=asdict(ReviewSettings(en_cps=12, en_line=30)))
    p.add_track(Track('test', [Segment(0, 2000, 'はい', translation='This text now exceeds the custom reading speed.')]))
    store = ProjectStore(tmp_path/'review.sqlite')
    store.save(p)
    saved = store.load()
    assert saved.review_settings['en_cps'] == 12
    assert any('EN: za szybko' in i for i in review_track(saved.active, ReviewSettings.load(saved.review_settings))[0]['issues'])
    old = p.to_dict()
    del old['review_settings']
    assert Project.from_dict(old).review_settings == {}
    with pytest.raises(ValueError):
        ReviewSettings.load({'min_ms': 9000, 'max_ms': 1000})
    with pytest.raises(ValueError):
        ReviewSettings.load({'en_cps': 0})


def test_bilingual_split_preserves_text_times_provenance_and_protects_en():
    s = Segment(12000, 18000, '今日は晴れです。明日は雨です。', translation='It is sunny today. Tomorrow it will rain.')
    proposal = split_proposal(s, ReviewSettings())
    assert proposal
    jp, en, at = proposal
    first, second = split_segment(s, jp, at, en)
    assert first.start == s.start and first.end == second.start and second.end == s.end
    assert first.text + second.text == s.text
    assert (first.translation + ' ' + second.translation).split() == s.translation.split()
    assert first.parents == second.parents == [s.id]
    assert first.status == second.status == 'stale'
    assert first.id != second.id and first.id != s.id
    with pytest.raises(ValueError, match='EN'):
        split_segment(s, jp, at)
    with pytest.raises(ValueError):
        split_segment(s, jp, s.end, en)


def test_split_does_not_claim_to_fix_reading_speed_or_cut_english_words():
    assert split_position('supercalifragilisticexpialidocious') is None
    s = Segment(0, 1000, '今日は晴れです。明日は雨です。')
    row = review_track(Track('test', [s]), ReviewSettings())[0]
    assert 'Za mało czasu na dwie' in row['advice']
    jp, en, at = row['proposal']
    a, b = split_segment(s, jp, at)
    assert abs((metrics(a.text, a.end-a.start)['cps'] + metrics(b.text, b.end-b.start)['cps'])/2 -
               metrics(s.text, 1000)['cps']) < .1


def test_reflow_preserves_words_speaker_breaks_and_long_words():
    original = '- This is the first speaker.\n- Another speaker answers with some long words.'
    proposed = reflow_english(original, 20)
    assert proposed.split() == original.split()
    assert '\n- Another' in proposed
    assert all(len(line) <= 20 for line in proposed.splitlines())
    assert reflow_english('extraordinarylongunbrokenword', 5) == 'extraordinarylongunbrokenword'

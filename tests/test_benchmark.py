import pytest
from tools.compare_reference import normalize_text,score_text
from tools.fetch_reference_media import normalize_srt


def test_character_error_rate_counts_edits_not_subtitle_segmentation():
    result=score_text('abc','axbc!')
    assert result['cer']==pytest.approx(1/3)
    assert result['insertions']==1 and result['substitutions']==result['deletions']==0
    assert score_text('字幕です。\n本日','字幕です 本日')['cer']==0
    assert score_text('abc','ac')['deletions']==1
    assert score_text('abc','axc')['substitutions']==1
    assert score_text('abc','')['cer']==1
    assert normalize_text('ＡＢＣ１２３。 [音楽]')=='abc123'
    with pytest.raises(ValueError): score_text('。','text')


def test_reference_srt_repairs_only_structure_and_records_empty_entries():
    original='1\n00:00:01,000 --> 00:00:02,000\n日本語\n2\n00:00:02,000 --> 00:00:03,000\n次の文\n\n3\n00:00:03,000 --> 00:00:04,000'
    result,empty=normalize_srt(original)
    assert empty==[3]
    assert result=='1\n00:00:01,000 --> 00:00:02,000\n日本語\n\n2\n00:00:02,000 --> 00:00:03,000\n次の文\n'

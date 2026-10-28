from itertools import product

import pytest

from tools.asr_oracle import evaluate_oracle, hypothesis_lattice, lattice_oracle
from tools.compare_reference import score_text


def test_phrase_oracle_can_combine_complementary_model_errors():
    hypotheses={'large-v3':'A1xB2yC','kotoba':'A1aB2yC','qwen':'A1xB2bC'}
    result=evaluate_oracle('A1aB2bC',hypotheses)
    assert result['score']['edit_distance']==0 and result['best_whole_hypothesis']['score']['edit_distance']==1
    assert result['selection']=='phrase-lattice' and not result['deployable']
    assert {p['source'] for p in result['choices']} >= {'kotoba','qwen'}


def test_oracle_matches_exhaustive_complete_phrase_paths_not_character_voting():
    parts=[{'start':0,'end':2,'options':[{'source':'a','text':'ax'},{'source':'b','text':'yb'}]},
           {'start':2,'end':3,'options':[{'source':'a','text':'c'},{'source':'b','text':''}]}]
    result=lattice_oracle('abc',parts)
    possibilities=[''.join(p['options'][i]['text'] for p,i in zip(parts,path)) for path in product(range(2),repeat=2)]
    assert result['hypothesis_jp'] in possibilities
    assert result['score']['edit_distance']==min(score_text('abc',t)['edit_distance'] for t in possibilities)==1


@pytest.mark.parametrize('reference',['abcd','axc','日本語です',''])
def test_oracle_never_scores_worse_than_any_usable_whole_hypothesis(reference):
    hypotheses={'large-v3':'abcd','other':'axc'}
    if not reference:
        with pytest.raises(ValueError):evaluate_oracle(reference,hypotheses)
    else:
        r=evaluate_oracle(reference,hypotheses)
        assert r['score']['edit_distance']<=min(score_text(reference,t)['edit_distance'] for t in hypotheses.values())


def test_lattice_is_reference_free_and_source_options_are_contiguous():
    hypotheses={'large-v3':'新鮮な魚を得ても国の開発度が一番良いところですね',
                'kotoba':'新鮮な魚いつでも国配列堂が一番いいところですね'}
    parts=hypothesis_lattice(hypotheses,'large-v3')
    for part in parts:
        for option in part['options']:
            assert option['text'] in hypotheses[option['source']]


def test_oracle_handles_empty_hypothesis_and_does_not_invent_missing_text():
    result=evaluate_oracle('missing',{'large-v3':'','other':'mi'})
    assert result['score']['edit_distance']==5
    assert result['hypothesis_jp']=='mi'

from dataclasses import asdict
import json
import pytest

from studio.core import Segment, Track
from studio.storage import Settings
from tools.benchmark_asr_fusion import audio_input, config_for, MODELS, cuda_evidence, valid_timing, summarize, edit_effects, evaluate, markdown, retry_candidates
from tools.compare_reference import score_text
from tools import benchmark_asr_fusion as benchmark


def test_reference_labels_cannot_enter_inference_configuration(tmp_path):
    sample={'id':'test','audio':str(tmp_path/'audio.flac'),'audio_sha256':'abc','source_range_ms':[1000,3000],
            'reference_jp':'絶対にモデルに渡さない正解','expected_action':'fix','split':'control'}
    inputs=audio_input(sample)
    assert set(inputs)=={'id','audio','audio_sha256','source_range_ms'}
    for jp_only in (False,True):
        config=config_for(inputs,MODELS[0],Settings(),tmp_path,jp_only)
        assert sample['reference_jp'] not in json.dumps(config,ensure_ascii=False)
        assert config['prompt']=='' and config['start']==0 and config['duration']==2000


def test_cuda_banner_is_not_proof_of_actual_cuda_inference():
    assert not cuda_evidence('backends: cpu,cuda\nggml_cuda_init: found 1 CUDA devices')
    assert cuda_evidence('whisper_backend_init_gpu: using CUDA0 backend')
    assert cuda_evidence('model buffer on CUDA0')
    assert not cuda_evidence('using CPU backend')


def test_timing_invalid_text_is_not_eligible_for_subtitle_fusion():
    assert valid_timing(Track('ok',[Segment(0,100,'a'),Segment(100,200,'b')]),200)
    assert not valid_timing(Track('zero',[Segment(0,0,'a')]),200)
    assert not valid_timing(Track('overlap',[Segment(0,150,'a'),Segment(100,200,'b')]),200)
    assert not valid_timing(Track('bounds',[Segment(0,201,'a')]),200)


def test_summary_uses_weighted_cer_and_exposes_incomplete_coverage():
    def row(ref,hyp,readable=True):
        model={'usable':readable,'original_seconds':2,'cached':True,'readable_text':readable}
        if readable:model['score']=score_text(ref,hyp)
        return {'corpus':'test','models':{m['key']:model.copy() for m in MODELS},
                'production':{'usable':False},'oracles':{}}
    rows=[row('a','x'),row('aaaaaaaaa','aaaaaaaaa')]
    summary=summarize(rows)['all']['scores']['large-v3']
    assert summary['complete_text_cer']==.1  # not mean(1, 0)
    rows.append(row('a','',False))
    summary=summarize(rows)['all']['scores']['large-v3']
    assert summary['complete_text_cer'] is None and summary['available_text_cer']==.1
    assert summary['scored_text_cases']==2 and summary['total_cases']==3


def test_applied_edit_audit_separates_helpful_harmful_and_neutral():
    cue=Segment(0,1000,'axb');base={'decoded':{'track':asdict(Track('base',[cue]))}}
    changes=[{'cue_id':cue.id,'text_start':1,'text_end':2,'before':'x','after':text} for text in ('a','yz','q')]
    result=edit_effects('aab',base,{'review':{'changes':changes}})
    assert [r['effect'] for r in result]==['helpful','harmful','neutral']
    assert cue.text=='axb'


def test_evaluation_retains_frozen_results_and_counts_seeded_baseline_cost():
    cue=Segment(0,1000,'abc');decoded={'track':asdict(Track('base',[cue]))}
    model={'readable_text':True,'usable':True,'hypothesis_jp':'abc','decoded':decoded,'original_seconds':10,'cached':True}
    production={'usable':True,'hypothesis_jp':'abc','original_seconds':3,'review':{'changes':[]},'retry_windows':0}
    frozen=[{'id':'clip','models':[{'model':'large-v3',**model}],'production':production}]
    before=json.dumps(frozen)
    rows=evaluate([{'id':'clip','reference_jp':'abc','split':'control'}],frozen)
    assert rows[0]['production']['original_seconds']==13
    assert rows[0]['production']['incremental_review_seconds']==3
    assert json.dumps(frozen)==before


def test_report_table_has_no_blank_lines_between_rows():
    report=markdown({'all':{'scores':{'large-v3':{'complete_text_cer':.1,'usable_timing_cases':1,
        'scored_text_cases':1,'total_cases':1,'original_seconds':2,'cached_cases':0}},
        'phrase_edits':{},'retry_windows':0,'production_cases':{},'baseline_mismatch_without_retry':0,'selection_opportunity':{}}})
    assert '|---|---:|' in report and '|\n\n|' not in report


def test_oracle_retry_pool_preserves_outside_audio_and_rejects_invalid_times():
    cues=[Segment(0,1000,'left'),Segment(1000,2000,'wrong'),Segment(2000,3000,'right')]
    baseline={'decoded':{'track':asdict(Track('base',cues))}}
    def attempt(end):
        return {'usable':True,'track':asdict(Track('retry',[Segment(1000,end,'correct')])),
                'model':'large.bin','directory':'raw'}
    retry={'windows':[{'id':'middle','cue_ids':[cues[1].id],'attempts':[attempt(2000),attempt(2500)]}]}
    result=retry_candidates(baseline,retry,3000)
    assert list(result)==['retry-middle-0']
    assert result['retry-middle-0']['hypothesis_jp']=='left\ncorrect\nright'
    assert baseline['decoded']['track']['segments'][1]['text']=='wrong'


def test_resumed_operational_failure_cannot_be_silently_counted_as_bad_asr(tmp_path,monkeypatch):
    pointer=tmp_path/'pointers'/'test-large-v3.json';pointer.parent.mkdir()
    pointer.write_text(json.dumps({'manifest':str(tmp_path/'manifest.json')}))
    monkeypatch.setattr(benchmark,'load_run',lambda *a:{'failure_kind':'operational','error':'CUDA out of memory'})
    monkeypatch.setattr(benchmark,'inspect_asr',lambda *a:pytest.fail('Operational failure must stop scoring'))
    with pytest.raises(RuntimeError,match='operational'):
        benchmark.collect_asr({'id':'test'},MODELS[0],Settings(),tmp_path,tmp_path)

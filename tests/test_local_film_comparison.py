from itertools import product
from dataclasses import asdict
from pathlib import Path

import pytest

from studio.core import Track,Segment
from studio.evaluation_text import score_text
from tools.compare_local_film import exact_distance,text_score,matched_timing,comparison_examples,render_comparison_report,window_comparisons,compare_results,film_config,save_project
from tools.verify_long_whisper import transcript_diagnostics
from studio.audio_boundaries import audio_digest
from studio.pipeline import create_run,digest
from studio.pipeline_worker import read_json,write_json
from tests.test_pipeline import config
from studio.storage import Settings
from studio.pipeline import plan,validate_config
from studio.core import ProjectStore


def test_bit_vector_distance_matches_exact_dp_exhaustively_and_handles_empty_input():
    words=[''.join(chars) for size in range(5) for chars in product('ab',repeat=size)]
    for left in words:
        for right in words:
            expected=score_text(left,right)['edit_distance'] if left else len(right)
            assert exact_distance(left,right)==expected
            assert exact_distance(right,left)==expected


def test_long_comparison_stays_exact_without_a_quadratic_traceback_buffer():
    left='あいうえお'*3000
    right=left[:7000]+'新'+left[7001:]+'後'
    assert exact_distance(left,right)==2
    result=text_score('Ａ、あ。','a あ')
    assert result['cer']==0 and result['reference_characters']==2
    with pytest.raises(ValueError):text_score('。','あ')


def test_unique_complete_caption_timing_reports_coverage_not_interpolated_matches():
    reference=Track('SE',[Segment(100,1000,'今日は良い天気です'),Segment(2000,3000,'同じ文章です'),Segment(4000,5000,'同じ文章です')])
    actual=Track('ours',[Segment(150,1200,'今日は良い天気です。'),Segment(2100,3100,'同じ文章です'),Segment(5200,6000,'今日は')])
    result=matched_timing(reference,actual)
    assert result['matched_cues']==1 and result['reference_cues']==3
    assert result['start']['mean_absolute_ms']==50 and result['end']['mean_absolute_ms']==200
    assert result['start']['mean_signed_ms']==50


def test_listening_examples_are_separate_from_exact_character_distance():
    reference=Track('SE',[Segment(1000,2000,'あいうえお'),Segment(50000,51000,'かきくけこ')])
    actual=Track('ours',[Segment(1000,2000,'あいうえか'),Segment(50000,51000,'かきくけさ')])
    rows=comparison_examples(reference,actual)
    assert len(rows)==2 and [r['reference_time_ms'] for r in rows]==[1000,50000]
    assert all('Heuristic' in r['scope'] for r in rows)


def test_comparison_report_distinguishes_agreement_coverage_and_incomplete_checks():
    reference=Track('SE',[Segment(100,1000,'今日は良い天気です')])
    actual=Track('ours',[Segment(200,1100,'今日は良い天気です')])
    comparison={'reference_technical':transcript_diagnostics(reference,2000),'variants':{'jp-layout':{
        'score':text_score(reference.segments[0].text,actual.segments[0].text),
        'technical':transcript_diagnostics(actual,2000),'timing':matched_timing(reference,actual)}}}
    summary={'media_seconds':7200,'wall_seconds':3000,'status':'completed',
        'stages':[{'id':'asr-0','seconds':2999,'status':'completed'}],
        'gpu_peak_mib':7000,'engine_pid_observed_on_nvidia':True,'engine_peak_ram_mib':4000,'minimum_available_ram_mib':500}
    report=render_comparison_report(summary,comparison)
    assert 'unverified ASR reference' in report and 'not independently measured transcription accuracy' in report
    assert '0 / 9 | 0.00%' in report and '1 matched captions / 1 reference / 1 actual' in report
    assert 'median absolute difference 100 ms' in report
    assert 'Exact export audit: **not completed**' in report
    comparison['variants']['jp-layout']['timing']=matched_timing(reference,Track('unmatched',[Segment(100,500,'別の文')]))
    report=render_comparison_report(summary,comparison)
    assert '0 matched captions / 1 reference / 1 actual' in report
    assert 'median absolute difference' not in report
    summary.update(status='failed',error={'type':'AsrQualityError','message':'Unsupported timing repair'})
    report=render_comparison_report(summary,comparison)
    assert 'Final export did not complete' in report and 'Unsupported timing repair' in report
    assert '| Fast reading |\n|---|' in report
    summary.update(status='needs_review',error=None,asr_failures=[{'name':'Kotoba','reason':'Alignment collapse'}])
    report=render_comparison_report(summary,comparison)
    assert 'Rejected auxiliary ASR (pipeline continued)' in report and 'Kotoba: Alignment collapse' in report
    assert 'Final export did not complete' not in report


def test_limited_listening_locations_cover_beginning_middle_and_end():
    reference=Track('SE',[Segment(i*60000+1000,i*60000+2000,chr(0x4e00+i)*3+'あ') for i in range(7)])
    actual=Track('ours',[Segment(c.start,c.end,c.text[:-1]+'い') for c in reference.segments])
    rows=comparison_examples(reference,actual,limit=3)
    assert [r['reference_time_ms'] for r in rows]==[1000,181000,361000]
    assert len(comparison_examples(reference,actual,limit=1))==1
    assert comparison_examples(reference,actual,limit=0)==[]
    assert comparison_examples(Track('empty',[]),actual)==[]


def test_temporal_bins_report_empty_reference_and_midpoint_exclusions():
    reference=Track('SE',[Segment(590000,610000,'あいう')])
    actual=Track('ours',[Segment(1000,2000,'え'),Segment(590001,609999,'あいう'),Segment(1200000,1201000,'外')])
    result=window_comparisons(reference,actual,1200000)
    first,second=result['windows']
    assert first['reference_characters']==0 and first['edit_distance']==1 and first['cer'] is None
    assert second['reference_cues']==second['actual_cues']==1 and second['cer']==0
    assert result['excluded_reference_cues']==0 and result['excluded_actual_cues']==1
    with pytest.raises(ValueError):window_comparisons(reference,actual,0)


def test_failed_review_still_compares_completed_asr_without_rewriting_evidence(config,tmp_path):
    config.update(transcription_only=True,translations=[],source_review_version=None,review='rules',
        asr_timing_review={'enabled':True},duration=20000,media_duration=20000)
    config['asr']=[{**config['asr'][0],'vad':True}];config['settings']['crisp_vad']=config['media']
    state=create_run(config,tmp_path/'run');raw=Track('raw',[Segment(100,900,'前です'),Segment(2000,2000,'次です')])
    for stage in state['stages']:
        if stage['id'] in ('audio','asr-0'):
            value={'audio':config['media']} if stage['id']=='audio' else {'track':asdict(raw)}
            path=tmp_path/'run'/stage['id']/'result.json';write_json(path,value)
            stage.update(status='completed',artifact=str(path),digest=digest(value),seconds=1)
        elif stage['id']=='asr-timing-review':stage.update(status='failed',seconds=2)
    state['status']='failed';write_json(tmp_path/'run/manifest.json',state)
    reference=tmp_path/'reference.srt';reference.write_text('1\n00:00:00,100 --> 00:00:00,900\n前です\n\n2\n00:00:02,000 --> 00:00:03,000\n次です\n',encoding='utf8')
    write_json(tmp_path/'protocol.json',{'reference':str(reference),'reference_sha256':audio_digest(reference)})
    frozen={p:audio_digest(p) for p in (reference,tmp_path/'run/manifest.json',tmp_path/'run/asr-0/result.json')}
    result=compare_results(tmp_path)
    assert result['production_status']=='failed' and result['comparison_stage']=='asr-0'
    assert list(result['variants'])==['asr-0'] and result['variants']['asr-0']['score']['cer']==0
    assert result['variants']['asr-0']['technical']['zero_duration_cues']==1
    assert result['window_comparison']['windows'][0]['cer']==0
    assert Path(read_json(tmp_path/'ui/last_project.json')['path']).is_file()
    assert frozen=={p:audio_digest(p) for p in frozen}


def test_full_film_mode_uses_complete_existing_japanese_policy_and_restores_controls(tmp_path,monkeypatch):
    media=tmp_path/'movie.mp4';media.write_bytes(b'synthetic media identity')
    settings=Settings(crisp_gpu_backend='cuda',llm_device='cuda',llm_model='local-review.gguf')
    def forbidden(*args):raise AssertionError('Full JP must not select the standalone native preset')
    monkeypatch.setattr(Settings,'use_subtitle_edit_whisper',forbidden)
    cfg=film_config(media,7200000,settings,tmp_path,True);validate_config(cfg)
    assert [s['id'] for s in plan(cfg)]==['audio','asr-0','asr-timing-review','asr-coverage','asr-scan','asr-retry','jp-review',
        'jp-context','jp-adaptive','jp-align','jp-layout','jp-export']
    assert cfg['translations']==[] and cfg['judge_model']=='local-review.gguf'
    assert cfg['retry_asr']['max_targets']==12 and cfg['retry_asr']['third_max_targets']==6
    assert cfg['adaptive_retry']['max_targets']==4 and cfg['asr_timing_review']['display_fallback']
    assert cfg['asr'][0]['engine']==2 and cfg['retry_asr']['third']['engine']==1
    assert 'benchmark_audio_sha256' not in cfg and 'reference' not in cfg
    raw=Track('raw',[Segment(100,900,'合成の例')]);path=tmp_path/'raw.json';write_json(path,{'track':asdict(raw)})
    state={'config':cfg,'stages':[{'id':'asr-0','status':'completed','artifact':str(path)}],
        'final_track':raw.id,'id':'synthetic','status':'needs_review'}
    save_project(tmp_path,state,Track('reference',[Segment(100,900,'合成の例')]))
    prefs=ProjectStore(Path(read_json(tmp_path/'ui/last_project.json')['path'])).load().pipeline_prefs
    assert prefs['retry_clips'] and prefs['jp_context_review'] and prefs['adaptive_audio'] and prefs['align_audio']
    assert prefs['retry_third_model']==cfg['retry_asr']['third']['model']
    assert prefs['asr_coverage'] and prefs['coverage_seconds']==30 and cfg['asr_coverage']['version']==2


@pytest.mark.parametrize('field',['crisp_gpu_backend','llm_device'])
def test_full_film_mode_rejects_non_cuda_configuration(tmp_path,field):
    settings=Settings(crisp_gpu_backend='cuda',llm_device='cuda');setattr(settings,field,'cpu')
    with pytest.raises(ValueError,match='requires CUDA'):film_config(tmp_path/'movie.mp4',7200000,settings,tmp_path,True)


def test_native_film_mode_retains_the_existing_profile(tmp_path,monkeypatch):
    settings=Settings()
    monkeypatch.setattr(Settings,'use_subtitle_edit_whisper',lambda self:tmp_path/'faster-whisper-large-v3')
    cfg=film_config(tmp_path/'movie.mp4',7200000,settings,tmp_path)
    assert [s['id'] for s in plan(cfg)]==['audio','asr-0','asr-timing-review','jp-layout','jp-export']
    assert cfg['asr'][0]['engine']==0 and not cfg['retry_asr']['enabled']

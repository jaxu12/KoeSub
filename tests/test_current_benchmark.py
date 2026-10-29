from array import array
import math

import pytest

from studio.pipeline import digest
from studio.pipeline_worker import write_json
from studio.storage import Settings
from tools.benchmark_current_pipeline import add_noise, production_config, exact_timing_matches, score, gpu_evidence, export_differences


def test_noise_is_reproducible_measured_and_does_not_clip():
    values = array('h', (round(12000*math.sin(i/9)) for i in range(16000)))
    mixed, info = add_noise(values, 9)
    repeated, _ = add_noise(values, 9)
    assert mixed == repeated and len(mixed) == len(values)
    gain = info['gain']
    signal = sum((v*gain)**2 for v in values)
    noise = sum((m-v*gain)**2 for v, m in zip(values, mixed))
    assert 10*math.log10(signal/noise) == pytest.approx(10, abs=.01)
    assert max(abs(v) for v in mixed) <= 32000


def test_production_config_excludes_reference_and_perturbation_metadata(tmp_path):
    sample = {'id': 'sample', 'audio': 'audio.wav', 'audio_sha256': 'abc', 'source_range_ms': [0, 10000],
        'reference_jp': 'SECRET_LABEL', 'group': 'SECRET_GROUP', 'perturbation': {'reference': 'SECRET_EXTRA'}}
    config = production_config(sample, Settings(), tmp_path)
    assert 'SECRET' not in str(config)
    assert config['jp_context_review'] and config['adaptive_retry']['enabled'] and config['jp_alignment']['enabled']


def test_gpu_proof_uses_asr_buffers_and_owned_alignment_llm_pids(tmp_path):
    for directory, value in [('asr-0', 'backend: cuda'), ('jp-align/block-0', 'found 1 CUDA devices'),
                             ('native-sessions/session', '')]:
        path = tmp_path/directory; path.mkdir(parents=True)
        (path/'engine.log').write_text(value)
    write_json(tmp_path/'jp-align/block-0/engine-process.json', {'pid': 21})
    write_json(tmp_path/'native-sessions/session/session.json', {'pid': 22})
    result = gpu_evidence(tmp_path, {'compute_processes': [{'pid': 21}, {'pid': 22}, {'pid': 999}]})
    assert list(result['asr_logs'].values()) == [True]
    assert result['alignment_pids_observed'] == [21] and result['owned_llm_pids_observed'] == [22]
    assert not gpu_evidence(tmp_path, {})['alignment_pids_observed']


def test_timing_comparison_requires_unique_complete_exact_text():
    reference = [{'start': 100, 'end': 1000, 'text': '今日は良い天気です。'},
        {'start': 2000, 'end': 3000, 'text': '同じ文章を繰り返す'},
        {'start': 4000, 'end': 5000, 'text': '同じ文章を繰り返す'}]
    track = {'segments': [{'start': 150, 'end': 1200, 'text': '今日は良い天気です'},
        {'start': 2100, 'end': 3000, 'text': '同じ文章を繰り返す'},
        {'start': 5000, 'end': 6000, 'text': '今日は良い'}]}
    matches = exact_timing_matches(track, reference)
    assert len(matches) == 1
    assert matches[0]['start_delta_ms'] == 50 and matches[0]['end_delta_ms'] == 200


def test_export_audit_distinguishes_trailing_space_from_lost_dialogue(tmp_path):
    path = tmp_path/'Japanese.srt'
    path.write_text('1\n00:00:00,000 --> 00:00:01,000\n3月 \n', encoding='utf8')
    result = export_differences({'exports': [str(path)]}, {'segments': [{'start': 0, 'end': 1000, 'text': '3月 '}]})
    assert result['expected_cues'] == result['recovered_cues'] == 1
    assert result['differences'][0]['whitespace_only'] and result['differences'][0]['times_equal']


def benchmark_files(root):
    inputs = [{'id': name} for name in ('a', 'b', 'silence')]
    labels = {'a': {'reference_jp': 'あいうえ'}, 'b': {'reference_jp': 'あいうえおかきく'}, 'silence': {'reference_jp': ''}}
    protocol = {'inputs_digest': digest(inputs), 'labels_digest': digest(labels), 'policy': {'asr': 'frozen'}}
    def track(text): return {'segments': [{'start': 0, 'end': 1000, 'text': text}]}
    records = [
        {'id': 'a', 'group': 'speech', 'status': 'completed', 'seconds': 2,
         'tracks': {'asr-0': track('あいうけ'), 'jp-layout': track('あいうえ')}},
        {'id': 'b', 'group': 'speech', 'status': 'failed', 'seconds': 3,
         'tracks': {'asr-0': track('あいうえおかきく')}},
        {'id': 'silence', 'group': 'no-speech-control', 'status': 'failed', 'seconds': 1,
         'tracks': {'asr-0': track('架空の発言')}}]
    frozen = {'records': records, 'inputs_digest': protocol['inputs_digest'], 'policy': protocol['policy']}
    for name, value in [('inputs', inputs), ('labels', labels), ('protocol', protocol), ('collected', frozen)]:
        write_json(root/(name+'.json'), value)
    return frozen


def test_weighted_scores_keep_failed_output_in_planned_coverage_and_negative_controls(tmp_path):
    benchmark_files(tmp_path)
    result = score(tmp_path); speech = result['groups']['speech']
    assert speech['cases'] == 2 and speech['completed_exports'] == 1
    assert speech['scores']['asr-0']['cer'] == pytest.approx(1/12)
    final = speech['scores']['jp-layout']
    assert final['available'] == 1 and final['reference_characters'] == 4 and final['planned_reference_characters'] == 12
    assert result['records'][0]['effect'] == 'helpful'
    assert result['records'][2]['scores']['asr-0'] == {'hallucinated_characters': 5}
    assert result['groups']['no-speech-control']['scores']['jp-layout']['cer'] is None
    report = (tmp_path/'report.md').read_text('utf8')
    assert 'Incomplete (1/2)' in report and 'No reference speech' in report


def test_no_speech_native_diagnostic_does_not_count_as_successful_export(tmp_path):
    frozen = benchmark_files(tmp_path)
    directory = tmp_path/'runs/silence/asr-0'; directory.mkdir(parents=True)
    (directory/'engine.log').write_text('Final speech segments after filtering: 0\nwarning: no speech detected')
    frozen['records'][-1].update(manifest=str(directory.parent/'manifest.json'), tracks={})
    write_json(tmp_path/'collected.json', frozen)
    result = score(tmp_path)
    native = result['records'][-1]['no_speech_native']
    assert native['vad_reported_no_speech'] and native['srt_files'] == []
    assert result['groups']['no-speech-control']['completed_exports'] == 0


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'policy', 'input_digest'])
def test_scoring_refuses_incomplete_or_changed_collection(tmp_path, change):
    frozen = benchmark_files(tmp_path)
    if change == 'missing': frozen['records'].pop()
    elif change == 'duplicate': frozen['records'].append(frozen['records'][0])
    elif change == 'policy': frozen['policy'] = {'asr': 'changed'}
    else: frozen['inputs_digest'] = 'changed'
    write_json(tmp_path/'collected.json', frozen)
    with pytest.raises(ValueError, match='collection'): score(tmp_path)

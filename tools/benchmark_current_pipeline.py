"""Frozen CUDA production benchmark: new recordings, paired noise and no-speech controls.

Preparation stores labels separately. Collection only reads allowlisted inputs;
scoring requires the complete frozen collection and never calls production code.
"""
import argparse
from array import array
from collections import Counter
from copy import deepcopy
from datetime import datetime
import math
from pathlib import Path
import random
import subprocess
import sys
import time
import wave

from studio.audio_boundaries import audio_digest
from studio.core import load_srt
from studio.pipeline import create_run, digest, load_run
from studio.pipeline_worker import read_json, write_json, run_pipeline
from studio.review import ReviewSettings, metrics
from studio.storage import Settings, check_space
from tools.benchmark_asr_fusion import MODELS, config_for, cuda_evidence
from tools.compare_reference import normalize_text, score_text
from tools.gpu_telemetry import GpuTelemetry
from tools.verify_pipeline import audit_result

STAGES = ('asr-0', 'asr-scan', 'jp-review', 'jp-context', 'jp-adaptive', 'jp-align', 'jp-layout')


def policy():
    return {str(p): audio_digest(p) for p in sorted(Path('studio').glob('*.py'))}


def pcm(path):
    with wave.open(str(path), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise ValueError('Expected mono PCM16 at 16 kHz')
        values = array('h', source.readframes(source.getnframes()))
    if sys.byteorder != 'little': values.byteswap()
    return values


def save_pcm(path, values):
    values = array('h', values)
    if sys.byteorder != 'little': values.byteswap()
    with wave.open(str(path), 'wb') as target:
        target.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        target.writeframes(values.tobytes())


def add_noise(values, seed, snr_db=10):
    rng = random.Random(seed)
    noise = [rng.gauss(0, 1) for _ in values]
    signal_rms = math.sqrt(sum(v*v for v in values)/len(values))
    noise_rms = math.sqrt(sum(v*v for v in noise)/len(noise))
    amplitude = signal_rms / (10**(snr_db/20)) / noise_rms
    mixture = [v+n*amplitude for v, n in zip(values, noise)]
    gain = min(1, 32000/max(1, max(abs(v) for v in mixture)))
    return array('h', (round(v*gain) for v in mixture)), {'seed': seed, 'snr_db': snr_db,
        'definition': 'Whole-file PCM RMS signal/noise ratio before common anti-clipping gain', 'gain': gain}


def prepare(index_path, output, meeting_dir):
    if (output/'inputs.json').exists(): raise ValueError('Use a new preparation directory')
    output.mkdir(parents=True, exist_ok=True); check_space(output, 256*1024**2, 2)
    settings = Settings.load(); index = read_json(index_path)
    if index['selected_rows'] != list(range(30, 40)): raise ValueError('Protocol fixes FLEURS rows 30–39')
    inputs = []; labels = {}; audio_dir = output/'audio'; audio_dir.mkdir()

    def append(name, group, audio, duration, reference, source, **extra):
        inputs.append({'id': name, 'group': group, 'audio': str(audio), 'audio_sha256': audio_digest(audio),
            'source_range_ms': [0, duration], **extra})
        labels[name] = {'reference_jp': reference, 'source': source, 'human_audio_verified': False}

    for sample in index['samples']:
        if audio_digest(sample['audio']) != sample['audio_sha256']: raise ValueError('Changed source audio')
        duration = sample['source_range_ms'][1]
        append(sample['id'], 'new-clean-read-speech', sample['audio'], duration, sample['reference_jp'],
            {'dataset': index['source'], 'revision': index['revision'], 'row': sample['source_row']})
        if sample['source_row'] < 34:
            clean = audio_dir/(sample['id']+'-pcm.wav')
            subprocess.run([settings.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                '-i', sample['audio'], '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(clean)], check=True, timeout=30)
            mixed, description = add_noise(pcm(clean), 20261029+sample['source_row'])
            noisy = audio_dir/(sample['id']+'-noise10.wav'); save_pcm(noisy, mixed)
            append(sample['id']+'-noise10', 'paired-synthetic-noise', noisy, duration, sample['reference_jp'],
                {'parent': sample['id'], 'note': 'Same spoken content; not an independent recording'}, perturbation=description)
    reference_path = meeting_dir/'reference.ja.srt'
    cues = [s for s in load_srt(reference_path).segments if 900000 <= s.start and s.end <= 1080000]
    if not cues: raise ValueError('No complete reference cues in fixed meeting interval')
    start, end = cues[0].start, cues[-1].end
    meeting = audio_dir/'mcdc-15m-18m.wav'
    subprocess.run([settings.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-ss', str(start/1000), '-i', str(meeting_dir/'MCDC-Japanese-23m-240p.webm'), '-t', str((end-start)/1000),
        '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(meeting)], check=True, timeout=120)
    append('mcdc-15m-18m', 'existing-meeting-additional-range', meeting, end-start, ''.join(s.text for s in cues),
        {'reference': str(reference_path), 'sha256': audio_digest(reference_path), 'range_ms': [start, end],
         'note': 'Community subtitles, same source recording as earlier tests; not a new corpus'})
    labels['mcdc-15m-18m']['timed_cues'] = [{'start': s.start-start, 'end': s.end-start, 'text': s.text} for s in cues]
    for name in ('silence', 'noise-only'):
        rng = random.Random(20261029)
        values = [0]*160000 if name == 'silence' else [max(-32767, min(32767, round(rng.gauss(0, 1000)))) for _ in range(160000)]
        audio = audio_dir/(name+'.wav'); save_pcm(audio, values)
        append(name, 'no-speech-control', audio, 10000, '', {'generator': name, 'seed': 20261029})
    # Clean recordings run first; related variants remain a distinct cohort.
    inputs.sort(key=lambda s: (s['group'] != 'new-clean-read-speech', s['group'], s['id']))
    write_json(output/'inputs.json', inputs); write_json(output/'labels.json', labels)
    write_json(output/'protocol.json', {'version': 1, 'policy': policy(), 'inputs_digest': digest(inputs),
        'labels_digest': digest(labels), 'selection': 'Ten fixed FLEURS rows 30–39, four paired 10 dB noise variants, fixed 15–18 minute meeting interval, two no-speech controls',
        'source_index': str(index_path), 'source_revision': index['revision'],
        'limits': 'New to this application test, not a claim about pretrained model training data or independent speakers. No policy tuning during collection.'})
    print('PREPARED', len(inputs), 'cases', flush=True)


def production_config(sample, settings, output):
    allowed = {key: sample[key] for key in ('id', 'audio', 'audio_sha256', 'source_range_ms')}
    config = config_for(allowed, MODELS[0], settings, output, True)
    config.update(source_review_version=3, jp_context_review=True, backend='embedded', judge_model=settings.llm_model,
        llm_keep_loaded=True, readability_repair=True, asr_failure_policy='continue', pause_uncertain=False,
        adaptive_retry={'enabled': True, 'max_targets': 4},
        jp_alignment={'enabled': True, 'split': True, 'max_shift_ms': 1500},
        retry_asr={'enabled': True, 'scan_first': True, 'batch_retries': True,
            'auxiliary': {k: v for k, v in MODELS[1].items() if k != 'key'},
            'third': {k: v for k, v in MODELS[2].items() if k != 'key'}, 'third_max_targets': 6,
            'max_targets': 12, 'padding_ms': 3000, 'max_window_ms': 30000})
    return config


def technical(track, rules):
    cues = track['segments']
    return {'cues': len(cues), 'fast_reading': sum(metrics(s['text'], s['end']-s['start'])['cps'] > rules.jp_cps for s in cues),
        'overlong': sum(s['end']-s['start'] > rules.max_ms for s in cues),
        'over_capacity': sum(len(s['text'].replace('\n', '')) > rules.jp_line*rules.max_lines for s in cues),
        'overlaps': sum(a['end'] > b['start'] for a, b in zip(cues, cues[1:])),
        'normalized_characters': len(normalize_text(''.join(s['text'] for s in cues)))}


def gpu_evidence(folder, gpu):
    # The ASR predicate checks actual CUDA model buffers. Align-only and the
    # embedded LLM have different logs; correlate their owned PIDs with NVIDIA.
    logs = [p for p in folder.rglob('engine.log') if p.relative_to(folder).parts[0].startswith('asr-')
            or p.relative_to(folder).parts[0] == 'jp-adaptive']
    observed = {s['pid'] for s in gpu.get('compute_processes', [])}
    aligners = [read_json(p)['pid'] for p in (folder/'jp-align').glob('block-*/engine-process.json')]
    sessions = [read_json(p)['pid'] for p in (folder/'native-sessions').glob('*/session.json')]
    return {'asr_logs': {str(p.relative_to(folder)): cuda_evidence(p.read_text('utf8', errors='replace')) for p in logs},
        'alignment_pids': aligners, 'alignment_pids_observed': [p for p in aligners if p in observed],
        'owned_llm_pids': sessions, 'owned_llm_pids_observed': [p for p in sessions if p in observed]}


def export_differences(state, track):
    path = next((Path(p) for p in state.get('exports', []) if p.endswith('Japanese.srt')), None)
    if path is None: return {'missing_export': True}
    recovered = load_srt(path).segments; cues = track['segments']
    differences = [{'index': i, 'before': a['text'], 'after': b.text,
        'times_equal': (a['start'], a['end']) == (b.start, b.end),
        'whitespace_only': a['text'].strip() == b.text.strip()}
        for i, (a, b) in enumerate(zip(cues, recovered))
        if (a['start'], a['end'], a['text']) != (b.start, b.end, b.text)]
    return {'expected_cues': len(cues), 'recovered_cues': len(recovered), 'differences': differences}


def collect(output):
    protocol = read_json(output/'protocol.json'); inputs = read_json(output/'inputs.json')
    if policy() != protocol['policy'] or digest(inputs) != protocol['inputs_digest']: raise ValueError('Changed frozen policy or inputs')
    settings = Settings.load()
    if settings.crisp_gpu_backend != 'cuda' or settings.llm_device != 'cuda': raise ValueError('CUDA required')
    frozen = output/'collected.json'
    if frozen.exists(): raise ValueError('Collection already frozen; use score mode')
    records = []; rules = ReviewSettings()
    previous = {r['id']: r for r in read_json(output/'progress.json')} if (output/'progress.json').exists() else {}
    pointer = Path('data/last_project.json'); original_pointer = pointer.read_bytes() if pointer.exists() else None
    for sample in inputs:
        if audio_digest(sample['audio']) != sample['audio_sha256']: raise ValueError('Changed benchmark audio')
        folder = output/'runs'/sample['id']; manifest = folder/'manifest.json'
        config = production_config(sample, settings, output/'exports'/sample['id'])
        if sample['id'] in previous:
            record = previous[sample['id']]
            if load_run(manifest)['config'] != config: raise ValueError('Changed completed case configuration')
            if record['error']: raise ValueError('Previous failed case requires explicit audit')
            if record.get('audit_passed', True): audit_result(manifest)
            record.pop('cuda_logs', None)
            record['gpu_evidence'] = gpu_evidence(folder, read_json(folder/'gpu-telemetry.json'))
            if not record['gpu_evidence']['asr_logs'] or not all(record['gpu_evidence']['asr_logs'].values()):
                raise ValueError('Missing saved ASR CUDA evidence')
            record['collection_reused_from_progress'] = True
            records.append(record)
            print('PRESERVED completed measurement', sample['id'], record['seconds'], flush=True)
            continue
        if manifest.exists():
            state = load_run(manifest)
            if state['config'] != config: raise ValueError('Changed case configuration')
            # Failed cases are recorded, not silently retried and selected for success.
            if state['status'] == 'failed':
                raise ValueError('Earlier failed case requires explicit audit before resuming: '+sample['id'])
        else: create_run(config, folder)
        incoming = read_json(manifest)
        recovered_finished = all(s['status'] == 'completed' for s in incoming['stages'])
        replayed = [s['id'] for s in incoming['stages'] if s['status'] == 'completed']
        print('CASE', sample['id'], sample['group'], flush=True); started = time.monotonic(); error = None
        if recovered_finished:
            # A collector audit can fail after production completed. Preserve
            # native telemetry and stage measurements; do not decode again.
            gpu = read_json(folder/'gpu-telemetry.json'); replayed = []
            elapsed = (datetime.fromisoformat(incoming['finished'])-datetime.fromisoformat(incoming['created'])).total_seconds()
        else:
            telemetry = GpuTelemetry(manifest, folder/'gpu-telemetry.json', capture_processes=True); telemetry.start()
            try:
                run_pipeline(manifest, lambda kind, **data: print(data['message'], flush=True) if kind == 'phase' else None)
            except Exception as exc:
                error = {'type': type(exc).__name__, 'message': str(exc)}
            finally: gpu = telemetry.close()
            elapsed = time.monotonic()-started
        state = read_json(manifest)
        evidence = gpu_evidence(folder, gpu)
        tracks = {}
        for stage in state['stages']:
            if stage['status'] == 'completed':
                value = read_json(stage['artifact'])
                if digest(value) != stage['digest']: raise ValueError('Changed completed stage')
                if stage['id'] in STAGES and 'track' in value: tracks[stage['id']] = value['track']
        record = {'id': sample['id'], 'group': sample['group'], 'manifest': str(manifest), 'status': state['status'],
            'error': error, 'seconds': round(elapsed, 3), 'replayed_stages': replayed,
            'timing_basis': 'Recovered manifest creation-to-finish interval; excludes telemetry close' if recovered_finished else 'Case wall time including telemetry close',
            'stages': [{k: s[k] for k in ('id', 'status', 'seconds') if k in s} for s in state['stages']],
            'gpu_evidence': evidence, 'gpu_samples': len(gpu['samples']), 'telemetry_errors': gpu['errors'],
            'peak_gpu_mib': max((s['memory_used_mib'] for s in gpu['samples']), default=None),
            'compute_pids': sorted({s['pid'] for s in gpu.get('compute_processes', [])}),
            'tracks': tracks, 'technical': {k: technical(t, rules) for k, t in tracks.items()},
            'phrase_changes': state.get('jp_review_changes', 0), 'adaptive_changes': state.get('jp_adaptive_changes', 0),
            'adaptive_targets': state.get('jp_adaptive_targets', 0), 'retimed_cues': state.get('jp_retimed_cues', 0),
            'split_cues': state.get('jp_split_cues', 0), 'quality_failures': state.get('asr_failures', [])}
        if not error:
            try:
                audit_result(manifest); record['audit_passed'] = True
            except AssertionError as exc:
                record['audit_passed'] = False; record['audit_error'] = str(exc)
                record['export_differences'] = export_differences(state, tracks['jp-layout'])
            # Replay must not launch another native process or mutate stage evidence.
            before = [(s['id'], s.get('digest'), s.get('seconds')) for s in state['stages']]
            native_before = {str(p): audio_digest(p) for p in folder.rglob('engine-process.json')}
            run_pipeline(manifest, lambda *a, **k: None)
            after = read_json(manifest)
            record['resume_unchanged'] = before == [(s['id'], s.get('digest'), s.get('seconds')) for s in after['stages']] and native_before == {str(p): audio_digest(p) for p in folder.rglob('engine-process.json')}
            assert record['resume_unchanged']
        if pointer.exists() and pointer.read_bytes() != original_pointer: raise ValueError('Main project pointer changed')
        records.append(record); write_json(output/'progress.json', records)
        print('CASE DONE', sample['id'], record['status'], record['seconds'], record['error'], flush=True)
        if not evidence['asr_logs'] or not all(evidence['asr_logs'].values()):
            # Some no-speech paths exit before creating CUDA model buffers; retain
            # that diagnostic without pretending inference happened on the GPU.
            if sample['group'] != 'no-speech-control': raise ValueError('Missing actual ASR CUDA evidence')
        if error and not sample['group'] == 'no-speech-control': raise RuntimeError('Speech case failed; retained evidence: '+str(error))
    if policy() != protocol['policy']: raise ValueError('Production changed during collection')
    write_json(frozen, {'records': records, 'inputs_digest': digest(inputs), 'policy': protocol['policy']})
    print('FROZEN', digest(read_json(frozen)), flush=True)


def exact_timing_matches(track, reference):
    lookup = {}
    for cue in reference:
        key = normalize_text(cue['text'])
        lookup.setdefault(key, []).append(cue)
    matches = []
    counts = Counter(normalize_text(c['text']) for c in track['segments'])
    for cue in track['segments']:
        key = normalize_text(cue['text'])
        if len(key) >= 6 and len(lookup.get(key, [])) == 1 and counts[key] == 1:
            ref = lookup[key][0]
            matches.append({'text': cue['text'], 'start_delta_ms': cue['start']-ref['start'], 'end_delta_ms': cue['end']-ref['end']})
    return matches


def score(output):
    protocol = read_json(output/'protocol.json'); frozen = read_json(output/'collected.json')
    inputs = read_json(output/'inputs.json'); labels = read_json(output/'labels.json')
    if digest(inputs) != protocol['inputs_digest'] or digest(labels) != protocol['labels_digest']: raise ValueError('Changed benchmark data')
    if (len(frozen['records']) != len(labels) or {r['id'] for r in frozen['records']} != set(labels)
            or frozen['inputs_digest'] != protocol['inputs_digest'] or frozen['policy'] != protocol['policy']):
        raise ValueError('Incomplete or changed collection; do not select surviving cases')
    results = []; groups = {}
    for record in frozen['records']:
        label = labels[record['id']]; row = deepcopy({k: v for k, v in record.items() if k != 'tracks'})
        row['scores'] = {}; row['hypotheses'] = {}
        if record['group'] == 'no-speech-control' and record.get('manifest'):
            directory = Path(record['manifest']).parent/'asr-0'; log_path = directory/'engine.log'
            log = log_path.read_text('utf8', errors='replace') if log_path.exists() else ''
            native_files = []
            for path in directory.glob('*.srt'):
                value = {'path': str(path), 'sha256': audio_digest(path)}
                try: value['text'] = ''.join(s.text for s in load_srt(path).segments)
                except (ValueError, UnicodeError) as exc: value['parse_error'] = str(exc)
                native_files.append(value)
            row['no_speech_native'] = {'vad_reported_no_speech': 'no speech detected' in log.lower(),
                'engine_log_sha256': audio_digest(log_path) if log_path.exists() else None, 'srt_files': native_files}
        for stage, track in record['tracks'].items():
            text = ''.join(s['text'] for s in track['segments']); row['hypotheses'][stage] = text
            if normalize_text(label['reference_jp']): row['scores'][stage] = score_text(label['reference_jp'], text)
            else: row['scores'][stage] = {'hallucinated_characters': len(normalize_text(text))}
        row['reference'] = label['reference_jp']
        if label.get('timed_cues'):
            row['community_timing_matches'] = {stage: exact_timing_matches(track, label['timed_cues']) for stage, track in record['tracks'].items()}
            matching = row['community_timing_matches']
            before = {normalize_text(v['text']): v for v in matching.get('asr-0', [])}
            after = {normalize_text(v['text']): v for v in matching.get('jp-layout', [])}
            shared = sorted(before.keys() & after.keys())
            row['paired_community_timing'] = {'matched_cues': len(shared), 'total_reference_cues': len(label['timed_cues'])}
            if shared:
                for name, values in [('baseline', before), ('final', after)]:
                    row['paired_community_timing'][name] = {edge: sum(abs(values[k][edge+'_delta_ms']) for k in shared)/len(shared) for edge in ('start', 'end')}
        group = groups.setdefault(record['group'], {'cases': 0, 'completed_exports': 0, 'exact_roundtrips': 0, 'seconds': 0, 'scores': {}})
        group['cases'] += 1; group['completed_exports'] += record['status'] in ('completed', 'needs_review'); group['seconds'] += record['seconds']
        group['exact_roundtrips'] += record.get('audit_passed', record['status'] in ('completed', 'needs_review'))
        for stage in STAGES:
            totals = group['scores'].setdefault(stage, {'available': 0, 'edits': 0, 'reference_characters': 0, 'planned_reference_characters': 0})
            totals['planned_reference_characters'] += len(normalize_text(label['reference_jp']))
            value = row['scores'].get(stage)
            if value and 'edit_distance' in value:
                totals['available'] += 1; totals['edits'] += value['edit_distance']; totals['reference_characters'] += value['reference_characters']
        if 'asr-0' in row['scores'] and 'jp-layout' in row['scores'] and label['reference_jp']:
            delta = row['scores']['asr-0']['edit_distance']-row['scores']['jp-layout']['edit_distance']
            row['review_edit_delta'] = delta; row['effect'] = 'helpful' if delta > 0 else 'harmful' if delta < 0 else 'neutral'
        tracks = record['tracks']
        text = lambda stage: ''.join(c['text'] for c in tracks[stage]['segments']).replace('\n', '')
        bounds = lambda stage: [(c['start'], c['end']) for c in tracks[stage]['segments']]
        row['invariants'] = {}
        for a, b, kind in [('asr-0', 'jp-review', 'times'), ('jp-review', 'jp-context', 'text'),
                           ('jp-context', 'jp-adaptive', 'times'), ('jp-adaptive', 'jp-align', 'text'),
                           ('jp-align', 'jp-layout', 'text')]:
            if a in tracks and b in tracks:
                row['invariants'][a+'->'+b+' '+kind] = bounds(a) == bounds(b) if kind == 'times' else text(a) == text(b)
        row['invariant_failures'] = [k for k, v in row['invariants'].items() if not v]
        results.append(row)
    for group in groups.values():
        group['seconds'] = round(group['seconds'], 3)
        for totals in group['scores'].values(): totals['cer'] = totals['edits']/totals['reference_characters'] if totals['reference_characters'] else None
    result = {'collection_digest': digest(frozen), 'groups': groups, 'records': results,
        'limitations': 'Published transcripts and community subtitles, not independently audio-audited. Paired noise is synthetic and not independent data. Character differences are not semantic error counts. Community timing is caption timing, not word-level acoustic gold. Missing outputs remain in coverage denominators.'}
    write_json(output/'results.json', result)
    write_report(result, output/'report.md')
    for name, group in groups.items(): print(name, {k: v for k, v in group.items() if k != 'scores'}, 'baseline/final', [(s, group['scores'][s]) for s in ('asr-0', 'jp-layout')], flush=True)
    return result


def write_report(result, path):
    lines = ['# Frozen current-pipeline benchmark', '',
        'All production stages run before reference scoring. No production policy was tuned during collection.', '',
        'FLEURS source: https://huggingface.co/datasets/google/fleurs (CC BY 4.0). '
        'The additional meeting range uses the already installed Wikimedia Commons recording and its community subtitles.', '',
        '| Cohort | Exports / cases | Exact round trips | Baseline edits / characters | Final edits / characters | Measured work |',
        '|---|---:|---:|---:|---:|---:|']
    def show(value, cases):
        if not value['planned_reference_characters']: return 'No reference speech'
        if value['available'] != cases: return f"Incomplete ({value['available']}/{cases})"
        return f"{value['edits']}/{value['reference_characters']} ({value['cer']:.2%})" if value['cer'] is not None else 'No reference speech'
    for name, group in result['groups'].items():
        lines.append(f"| {name} | {group['completed_exports']}/{group['cases']} | {group['exact_roundtrips']} | {show(group['scores']['asr-0'], group['cases'])} | {show(group['scores']['jp-layout'], group['cases'])} | {group['seconds']:.3f} s |")
    lines += ['', '## Per-case text changes', '', '| Case | Baseline edits | Auxiliary scan edits | Review edits | Adaptive edits | Final edits | Effect | Wall time |',
        '|---|---:|---:|---:|---:|---:|---|---:|']
    for row in result['records']:
        values = [str(row['scores'].get(s, {}).get('edit_distance', '—')) for s in ('asr-0', 'asr-scan', 'jp-review', 'jp-adaptive', 'jp-layout')]
        lines.append('| '+row['id']+' | '+' | '.join(values)+f" | {row.get('effect', row['status'])} | {row['seconds']:.3f} s |")
    costs = Counter()
    for row in result['records']:
        for stage in row.get('stages', []): costs[stage['id']] += stage.get('seconds', 0)
    lines += ['', '## Measured stage durations', '', '| Stage | Sum |', '|---|---:|']
    lines += [f'| {name} | {seconds:.3f} s |' for name, seconds in costs.items()]
    effects = Counter(r.get('effect') for r in result['records'] if r.get('effect'))
    exact = [r for r in result['records'] if r['scores'].get('asr-0', {}).get('edit_distance') == 0]
    regressions = [r['id'] for r in exact if r.get('review_edit_delta', 0) < 0]
    evidence = [r.get('gpu_evidence', {}) for r in result['records']]
    logs = [v for r in evidence for v in r.get('asr_logs', {}).values()]
    aligners = [(p, p in r.get('alignment_pids_observed', [])) for r in evidence for p in r.get('alignment_pids', [])]
    llms = [(p, p in r.get('owned_llm_pids_observed', [])) for r in evidence for p in r.get('owned_llm_pids', [])]
    lines += ['', '## Diagnostics', '', f'- Reference-distance effects per speech case: {dict(effects)}.',
        f'- Perfect-baseline cases: {len(exact)}; worsened by final output: {regressions}.',
        f'- Actual CUDA ASR-buffer evidence: {sum(logs)}/{len(logs)} logs (includes copied per-clip logs).',
        f'- Aligner PIDs observed by NVIDIA sampling: {sum(v for _, v in aligners)}/{len(aligners)}.',
        f'- Owned LLM PIDs observed by NVIDIA sampling: {sum(v for _, v in llms)}/{len(llms)}.',
        f'- Text/timing stage invariant failures: {[(r["id"], r["invariant_failures"]) for r in result["records"] if r.get("invariant_failures")]}.',
        f'- Completed-case cache replays preserving stage digests, timing costs and native process evidence: {sum(r.get("resume_unchanged", False) for r in result["records"])}.',
        f'- Export audit failures: {[(r["id"], r.get("audit_error"), r.get("export_differences")) for r in result["records"] if r.get("audit_passed") is False]}.',
        f'- Frozen collection digest: `{result["collection_digest"]}`.', '',
        '## Technical caption metrics', '',
        '| Case | Fast reading before / after | Overlong before / after | Capacity violations before / after | Retimed / split |',
        '|---|---:|---:|---:|---:|']
    for row in result['records']:
        technicals = row.get('technical', {})
        if 'asr-0' not in technicals or 'jp-layout' not in technicals: continue
        before, after = technicals['asr-0'], technicals['jp-layout']
        values = [f"{before[key]} / {after[key]}" for key in ('fast_reading', 'overlong', 'over_capacity')]
        lines.append('| '+row['id']+' | '+' | '.join(values)+f" | {row.get('retimed_cues', 0)} / {row.get('split_cues', 0)} |")
    lines += ['', '## Community caption timing', '']
    for row in result['records']:
        if 'paired_community_timing' in row:
            lines.append(f"- {row['id']}: {row['paired_community_timing']}. Absolute boundary differences in milliseconds, restricted to unique exact full-cue text present in both variants. These are community display times, not verified speech boundaries.")
    lines += ['',
        '## No-speech controls', '']
    for row in result['records']:
        if row['group'] == 'no-speech-control':
            lines.append(f"- {row['id']}: {row['status']}; emitted characters per available stage: {row['scores']}; failure: {row.get('error')}; native evidence: {row.get('no_speech_native')}.")
    lines += ['', '## Interpretation', '', result['limitations'], '',
        'A failed no-speech case with no emitted text is distinct from a successful empty export. '
        'Quality warnings are not confirmed error counts. Missing GPU PID samples are inconclusive, not proof of CPU fallback. '
        'Per-case results retain coverage, replay flags, exact hypotheses, timing matches, technical issues and failures.', '']
    path.write_text('\n'.join(lines), encoding='utf8')


def main():
    sys.stdout.reconfigure(encoding='utf8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'collect', 'score')); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--index', type=Path); parser.add_argument('--meeting-dir', type=Path, default=Path('D:/models/test-media/mcdc-japanese'))
    args = parser.parse_args()
    if args.mode == 'prepare':
        if not args.index: parser.error('Preparation needs --index')
        prepare(args.index, args.output, args.meeting_dir)
    elif args.mode == 'collect': collect(args.output)
    else: score(args.output)


if __name__ == '__main__': main()

"""Compare existing Whisper runtimes and Subtitle Edit settings on local audio.

Native outputs and private transcript excerpts stay in the requested cache.
Without a reference this measures execution, disagreement and timing validity,
not independently verified transcription accuracy.
"""
import argparse
from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import sys
import time

from studio.adapters import validate_flags, whisper_cpp_command
from studio.audio_boundaries import audio_digest
from studio.core import load_srt
from studio.pipeline import digest
from studio.pipeline_worker import read_json, write_json
from studio.storage import Model, Settings, offline_env, check_space
from tools.gpu_telemetry import GpuTelemetry
from tools.compare_reference import score_text


def collect(output, source_manifest):
    output.mkdir(parents=True, exist_ok=True); check_space(output, 128*1024**2, 2)
    settings = Settings.load(); installation = Path(settings.subtitle_edit)/'SpeechToText/Purfview-Faster-Whisper-XXL'
    exe = installation/'faster-whisper-xxl.exe'; model = installation/'_models/faster-whisper-large-v3'
    vocal = installation/'_xxl_data/faster_whisper/assets/Kim_Vocal_2.onnx'
    for path in (exe, model/'model.bin', model/'config.json', vocal):
        if not path.is_file(): raise ValueError('Missing local prerequisite: '+str(path))
    settings.crisp_gpu_backend = 'cuda'
    env = os.environ.copy(); env.update(offline_env()); temporary = output/'temporary'; temporary.mkdir(exist_ok=True)
    env.update(TEMP=str(temporary), TMP=str(temporary), PATH=str(Path(settings.ffmpeg).parent)+os.pathsep+env.get('PATH', ''))
    help_text = subprocess.check_output([str(exe), '--help'], env=env, text=True, encoding='utf8', errors='replace', timeout=90)
    (output/'xxl-help.txt').write_text(help_text, encoding='utf8')
    crisp_help = subprocess.check_output([settings.crisp_exe, '--help'], env=env, text=True, encoding='utf8', errors='replace', timeout=30)
    cases = [('public-interview', Path('D:/models/test-media/easy-japanese-1/Easy_Japanese_1_Typical_Japanese.mp4'), 0, 45000)]
    if source_manifest:
        source = read_json(source_manifest.parent/'audio/result.json')['audio']
        cases += [('private-dialogue', Path(source), 129000, 30000), ('private-invalid-time-window', Path(source), 1569000, 30000)]
    index_path = Path('D:/models/datasets/koesub-fleurs-ja-holdout-20261029/index.json')
    if index_path.exists():
        sample = next(s for s in read_json(index_path)['samples'] if s['source_row'] == 31)
        cases.append(('published-reference', Path(sample['audio']), 0, sample['source_range_ms'][1]))
    protocol = {'cases': [{'id': name, 'source': str(source), 'start': start, 'duration': duration,
        'source_size': source.stat().st_size, 'source_mtime': source.stat().st_mtime_ns} for name, source, start, duration in cases],
        'xxl_exe': str(exe), 'xxl_model': str(model), 'vocal_model': str(vocal),
        'crisp_model': 'D:/models/whisper/ggml-large-v3.bin', 'scope': 'Fresh local native comparison; no model downloads; private hypotheses stay local'}
    if (output/'protocol.json').exists() and read_json(output/'protocol.json') != protocol: raise ValueError('Changed comparison inputs')
    write_json(output/'protocol.json', protocol); records = []
    for name, source, start, duration in cases:
        wav = output/(name+'.wav')
        if not wav.exists():
            subprocess.run([settings.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-ss', str(start/1000),
                '-i', str(source), '-t', str(duration/1000), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)], check=True, timeout=120)
        for variant in ('crisp-current', 'xxl-no-vocal', 'xxl-subtitle-edit-mdx'):
            folder = output/name/variant; folder.mkdir(parents=True, exist_ok=True)
            path = folder/'measurement.json'
            if path.exists():
                records.append(read_json(path)); continue
            if variant == 'crisp-current':
                local = Model('Large V3', protocol['crisp_model'], 'Whisper / GGML', 0)
                command = [settings.crisp_exe, *whisper_cpp_command(settings, local, wav, folder, True, crisp_help)]
            else:
                args = [str(wav), '--model', 'large-v3', '--model_dir', str(model.parent), '--language', 'ja',
                    '--task', 'transcribe', '--device', 'cuda', '--compute_type', 'float16', '--standard_asia',
                    '--output_dir', str(folder), '--output_format', 'srt', 'json', '--beep_off']
                if variant == 'xxl-subtitle-edit-mdx': args += ['--ff_vocal_extract', 'mdx_kim2', '--voc_device', 'cuda']
                validate_flags(help_text, args); command = [str(exe), *args]
            manifest = folder/'telemetry-state.json'; write_json(manifest, {'status': 'running', 'stages': [{'id': variant, 'status': 'running'}]})
            write_json(folder/'command.json', command); telemetry = GpuTelemetry(manifest, folder/'gpu.json', capture_processes=True)
            print('START', name, variant, flush=True); started = time.monotonic(); telemetry.start()
            try:
                result = subprocess.run(command, cwd=folder, env=env, capture_output=True, timeout=900)
            finally: gpu = telemetry.close()
            log = result.stdout.decode('utf8', errors='replace')+'\n'+result.stderr.decode('utf8', errors='replace')
            (folder/'engine.log').write_text(log, encoding='utf8')
            record = {'case': name, 'variant': variant, 'audio_sha256': audio_digest(wav), 'exit_code': result.returncode,
                'seconds': round(time.monotonic()-started, 3), 'nvidia_pids': sorted({s['pid'] for s in gpu.get('compute_processes', [])}),
                'peak_gpu_mib': max((s['memory_used_mib'] for s in gpu['samples']), default=None), 'telemetry_errors': gpu['errors']}
            files = list(folder.glob('*.srt'))
            if len(files) == 1:
                track = load_srt(files[0]); cues = track.segments
                record.update(track=asdict(track), srt_sha256=audio_digest(files[0]),
                    invalid_times=sum(not 0 <= c.start < c.end <= duration for c in cues),
                    overlaps=sum(a.end > b.start for a, b in zip(cues, cues[1:])), cues=len(cues))
            record['digest'] = digest(record); write_json(path, record); records.append(record)
            write_json(output/'collected.json', records)
            print('DONE', name, variant, {k: record.get(k) for k in ('seconds', 'exit_code', 'cues', 'invalid_times', 'overlaps')}, flush=True)
    # Reference labels are used only after every native call has finished.
    if index_path.exists():
        sample = next(s for s in read_json(index_path)['samples'] if s['source_row'] == 31)
        for r in records:
            if r['case'] == 'published-reference' and 'track' in r:
                r['reference_score'] = score_text(sample['reference_jp'], ''.join(s['text'] for s in r['track']['segments']))
    write_json(output/'results.json', records)


def main():
    sys.stdout.reconfigure(encoding='utf8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-manifest', type=Path); args = parser.parse_args(); collect(args.output, args.source_manifest)


if __name__ == '__main__': main()

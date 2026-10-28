"""Manual hardware smoke test. Uses only an existing model and synthetic local speech."""
import json
import os
import subprocess
import sys
from pathlib import Path

from studio.adapters import crisp_command, whisper_command
from studio.core import load_srt
from studio.storage import ROOT, Settings, discover_models, offline_env


def main():
    settings = Settings.load()
    crisp = '--crisp' in sys.argv
    model = next(m for m in discover_models(settings.model_roots) if
                 (m.kind == 'Qwen ASR' if crisp else m.name == 'faster-whisper-large-v3-turbo'))
    folder = ROOT/'data'/'smoke'
    folder.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **offline_env(), 'TEMP': str(folder), 'TMP': str(folder)}
    executable = settings.crisp_exe if crisp else settings.whisper_exe
    help_result = subprocess.run([executable, '--help'], capture_output=True, timeout=90, env=env)
    help_text = (help_result.stdout+help_result.stderr).decode('utf8', errors='replace')
    prefix = 'crisp' if crisp else 'whisper'
    (folder/f'{prefix}-help.txt').write_text(help_text, encoding='utf8')
    command = crisp_command(settings, model, folder/'speech.wav', folder, True, help_text) if crisp else \
        whisper_command(settings, model, folder/'speech.wav', folder, 'float16', 'cuda', True, help_text)
    # System SAPI only has an English voice. This checks inference, not Japanese accuracy.
    command[command.index('--language')+1] = 'en'
    (folder/f'{prefix}-command.json').write_text(json.dumps(command, indent=2), encoding='utf8')
    with (folder/f'{prefix}.log').open('wb') as log:
        result = subprocess.run([executable, *command], stdout=log, stderr=subprocess.STDOUT,
                                env=env, cwd=ROOT, timeout=180)
    print('ASR exit:', result.returncode, flush=True)
    if result.returncode:
        print((folder/f'{prefix}.log').read_text('utf8', errors='replace')[-5000:])
        raise SystemExit(result.returncode)
    tracks = list(folder.glob('transcript.srt' if crisp else 'speech*.srt'))
    assert tracks, 'No SRT output'
    track = load_srt(tracks[0])
    print('Segments:', len(track.segments))
    print('Text:', ' '.join(s.text for s in track.segments))
    assert track.segments and all(s.end > s.start >= 0 for s in track.segments)


if __name__ == '__main__':
    main()

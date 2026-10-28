"""Exercise the explicitly downloaded ASR on a 20 s Japanese sample. All outputs on D:."""
import json
import os
import subprocess
from pathlib import Path

from studio.adapters import crisp_command
from studio.core import load_srt
from studio.storage import ROOT, Model, Settings, offline_env


def configured_settings():
    root = Path('D:/models')
    manifest = json.loads((root/'subtitle-studio-models.json').read_text('utf8'))
    if manifest.get('status') != 'verified':
        raise RuntimeError('Model download has not completed.')
    settings = Settings.load()
    settings.model_roots = [str(root)]
    settings.cache_dir = str(root/'.cache')
    settings.crisp_exe = manifest['crisp_exe']
    settings.crisp_gpu_backend = 'vulkan'
    settings.crisp_aligner = str(root/'asr/qwen3-forced-aligner-0.6b-q8_0.gguf')
    settings.crisp_vad = str(root/'asr/ggml-silero-v6.2.0.bin')
    for path in (settings.crisp_exe,settings.crisp_aligner,settings.crisp_vad):
        if not Path(path).is_file():
            raise RuntimeError('Missing dependency: '+path)
    return settings


def main():
    settings = configured_settings()
    folder = Path(settings.cache_dir)/'verification-japanese'
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder/'japanese20.wav'
    source = ROOT/'samples/media/Job_Interview.webm'
    result = subprocess.run([settings.ffmpeg,'-hide_banner','-nostdin','-y','-ss','20','-i',str(source),
                             '-t','20','-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(audio)],
                             capture_output=True,timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf8',errors='replace')[-2000:])
    env = {**os.environ,**offline_env(),'TEMP':str(folder),'TMP':str(folder)}
    help_result = subprocess.run([settings.crisp_exe,'--help'],capture_output=True,env=env,timeout=30)
    help_text = (help_result.stdout+help_result.stderr).decode('utf8',errors='replace')
    (folder/'engine-help.txt').write_text(help_text,encoding='utf8')
    path = Path('D:/models/asr/qwen3-asr-1.7b-ja-anime-q8_0.gguf')
    args = crisp_command(settings,Model(path.name,str(path),'Qwen ASR',path.stat().st_size),audio,folder,True,help_text)
    (folder/'command.json').write_text(json.dumps(args,indent=2),encoding='utf8')
    print('ASR verification running on Vulkan; outputs:',folder,flush=True)
    with (folder/'engine.log').open('wb') as log:
        result = subprocess.run([settings.crisp_exe,*args],stdout=log,stderr=subprocess.STDOUT,env=env,timeout=240)
    print('Exit:',result.returncode,flush=True)
    if result.returncode:
        print((folder/'engine.log').read_text('utf8',errors='replace')[-4000:])
        raise SystemExit(result.returncode)
    track = load_srt(folder/'transcript.srt')
    print('Segments:',len(track.segments))
    print('Valid times:',all(s.end>s.start>=0 for s in track.segments))
    print('Text:', ' '.join(s.text for s in track.segments))
    if not track.segments:
        raise RuntimeError('ASR returned no segments.')


if __name__ == '__main__':
    main()

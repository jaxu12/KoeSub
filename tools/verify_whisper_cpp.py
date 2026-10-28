"""Verify the downloaded Whisper Large V3 through the installed Vulkan runtime."""
import json
import os
import subprocess
from pathlib import Path

from studio.adapters import whisper_cpp_command
from studio.core import load_srt
from studio.storage import Model,Settings,offline_env


def main():
    settings=Settings.load()
    folder=Path('D:/models/.cache/verification-whisper')
    folder.mkdir(parents=True,exist_ok=True)
    audio=Path('D:/models/.cache/verification-japanese/japanese20.wav')
    path=Path('D:/models/whisper/ggml-large-v3.bin')
    model=Model(path.name,str(path),'Whisper / GGML',path.stat().st_size)
    env={**os.environ,**offline_env(),'TEMP':str(folder),'TMP':str(folder)}
    info=subprocess.run([settings.crisp_exe,'--help'],capture_output=True,env=env,timeout=30)
    help_text=(info.stdout+info.stderr).decode('utf8',errors='replace')
    args=whisper_cpp_command(settings,model,audio,folder,True,help_text)
    (folder/'command.json').write_text(json.dumps(args,indent=2),encoding='utf8')
    print('Whisper Large V3 verification running; local Japanese audio, Vulkan GPU.',flush=True)
    with (folder/'engine.log').open('wb') as log:
        result=subprocess.run([settings.crisp_exe,*args],stdout=log,stderr=subprocess.STDOUT,env=env,timeout=240)
    if result.returncode:
        print((folder/'engine.log').read_text('utf8',errors='replace')[-4000:])
        raise SystemExit(result.returncode)
    track=load_srt(folder/'transcript.srt')
    assert track.segments and all(s.end>s.start>=0 for s in track.segments)
    print('Valid segments:',len(track.segments))
    print('Text:',' '.join(s.text for s in track.segments))


if __name__=='__main__':
    main()

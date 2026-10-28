"""Capture independent burned-in subtitle samples for visual comparison; no OCR or ASR used."""
import json
import subprocess
import sys
from pathlib import Path

from studio.core import atomic_text
from studio.storage import Settings


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    root=Path('D:/models/test-media/easy-japanese-1')
    source=json.loads((root/'source.json').read_text('utf8'))
    folder=root/'reference-frames';folder.mkdir(exist_ok=True)
    times=[3.5,7,14,25,44,63,88,117,145,172,199,220,243,265]
    settings=Settings.load();frames=[]
    for position in times:
        image=folder/f'{position:06.1f}.jpg'
        result=subprocess.run([settings.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                               '-ss',str(position),'-i',source['video'],'-threads','2','-frames:v','1','-q:v','2',str(image)],
                              capture_output=True,timeout=20)
        if result.returncode: raise ValueError(result.stderr.decode('utf8',errors='replace'))
        frames.append({'seconds':position,'image':str(image),'reference':'Original burned-in creator subtitles; independent of app output'})
    atomic_text(folder/'index.json',json.dumps({'video':source['video'],'frames':frames,
                'scope':'Visual samples only, not a complete verified transcript or timestamp benchmark'},indent=2))
    print('Reference samples:',len(frames),'in',folder)


if __name__=='__main__': main()

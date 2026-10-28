import array
import json
import os
import subprocess
import sys
from pathlib import Path

from .process_control import ChildJob
from .storage import check_space,offline_env
from .waveform import HOP,RATE,save_peaks,source_key


def emit(kind,**value):
    print(json.dumps({'type':kind,**value},ensure_ascii=False),flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf8')
    spec=json.loads(sys.argv[1])
    path=Path(spec['output'])
    check_space(path,2*1024**2,spec.get('reserve_gib',2))
    path.parent.mkdir(parents=True,exist_ok=True)
    key=source_key(spec['media'],spec['track'])
    args=[spec['ffmpeg'],'-hide_banner','-nostdin','-loglevel','error','-threads','2','-i',spec['media'],
          '-map',f'0:a:{spec["track"]}','-vn','-ac','1','-ar',str(RATE),'-f','s16le','pipe:1']
    peaks,samples,pending=bytearray(),0,b''
    last=0
    with path.with_suffix('.log').open('wb') as log:
        child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=log,
                               env={**os.environ,**offline_env(),'TEMP':str(path.parent),'TMP':str(path.parent)},
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            with ChildJob(child):
                while True:
                    raw=child.stdout.read(65536)
                    if not raw:
                        break
                    pending+=raw
                    length=len(pending)//(HOP*2)*(HOP*2)
                    if length:
                        values=array.array('h')
                        values.frombytes(pending[:length])
                        if sys.byteorder!='little':
                            values.byteswap()
                        samples+=len(values)
                        for i in range(0,len(values),HOP):
                            peak=max(abs(v) for v in values[i:i+HOP])
                            peaks.append(min(255,round(peak/32768*255)))
                        pending=pending[length:]
                    if samples-last>RATE*5:
                        emit('progress',milliseconds=round(samples/RATE*1000))
                        last=samples
                code=child.wait(timeout=15)
        finally:
            child.stdout.close()
            if child.poll() is None:
                child.kill();child.wait(timeout=5)
    if code:
        raise RuntimeError(path.with_suffix('.log').read_text('utf8',errors='replace')[-1500:])
    if pending:
        if len(pending)%2:
            raise ValueError('Niepełne próbki audio z FFmpeg.')
        tail=array.array('h');tail.frombytes(pending)
        if sys.byteorder!='little':
            tail.byteswap()
        samples+=len(tail)
        peaks.append(min(255,round(max(abs(v) for v in tail)/32768*255)))
    if not samples:
        raise ValueError('Brak audio do waveformu.')
    if source_key(spec['media'],spec['track'])!=key:
        raise ValueError('Plik źródłowy zmienił się podczas analizy audio.')
    save_peaks(path,key,peaks,samples)
    emit('done',path=str(path),key=key)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        emit('error',message=str(exc))
        sys.exit(1)

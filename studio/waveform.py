"""Compact cached waveform: 50 one-byte peaks/second, no decoded WAV stored on disk."""
import base64
import hashlib
import json
from pathlib import Path

from .core import atomic_text

RATE,HOP = 4000,80


def source_key(media,track):
    source=Path(media).resolve()
    stat=source.stat()
    payload=[str(source),stat.st_size,stat.st_mtime_ns,track,RATE,HOP,1]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def cache_path(cache,media,track):
    return Path(cache)/'waveforms'/(source_key(media,track)+'.json')


def save_peaks(path,key,peaks,samples):
    atomic_text(Path(path),json.dumps({'version':1,'key':key,'rate':RATE,'hop':HOP,
                                     'samples':samples,'peaks':base64.b64encode(peaks).decode()}))


def load_peaks(path,key):
    path=Path(path)
    if path.stat().st_size>16*1024**2:
        raise ValueError('Cache waveformu jest zbyt duży.')
    value=json.loads(path.read_text('utf8'))
    if value.get('version')!=1 or value.get('key')!=key or value.get('rate')!=RATE or value.get('hop')!=HOP:
        raise ValueError('Nieaktualny cache waveformu.')
    peaks=base64.b64decode(value['peaks'],validate=True)
    samples=value['samples']
    if not isinstance(samples,int) or samples<=0 or len(peaks)!=(samples+HOP-1)//HOP:
        raise ValueError('Uszkodzony cache waveformu.')
    return peaks,round(samples/RATE*1000)

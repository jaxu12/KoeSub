"""Fetch one small, openly licensed Japanese test video; never fetch models."""
import hashlib
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://upload.wikimedia.org/wikipedia/commons/e/ec/Job_Interview.webm'
SHA1 = '628f841a1c2a61bf25948da346981dfc393b3040'
MAX_BYTES = 25 * 1024**2


def main():
    target = ROOT / 'samples/media/Job_Interview.webm'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and hashlib.sha1(target.read_bytes()).hexdigest() == SHA1:
        print('Existing verified file:', target)
        return
    if shutil.disk_usage(target.parent).free < MAX_BYTES + 1024**3:
        raise RuntimeError('Not enough disk space; requires 1 GiB reserve.')
    partial = target.with_suffix('.download')
    request = urllib.request.Request(URL, headers={'User-Agent': 'SubtitleStudioPrototype/0.1 (local media test)'})
    total = 0
    digest = hashlib.sha1()
    try:
        with urllib.request.urlopen(request, timeout=45) as response, partial.open('wb') as stream:
            while chunk := response.read(256*1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError('The file exceeds the 25 MiB download limit.')
                stream.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != SHA1:
            raise RuntimeError('Checksum differs from the original Wikimedia file.')
        partial.replace(target)
        print('Downloaded:', target)
        print('Bytes:', total)
        print('SHA1:', digest.hexdigest())
    finally:
        partial.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

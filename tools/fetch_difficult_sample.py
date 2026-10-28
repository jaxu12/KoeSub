"""Fetch a bounded prefix of a Commons film and keep a small live-action test clip."""
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

from studio.storage import ROOT, Settings

API = ('https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=videoinfo'
       '&viprop=url%7Cderivatives&titles=File%3ASisters_of_the_Gion_%281936%29_by_Kenji_Mizoguchi.webm')
MAX_BYTES = 12*1024**2


def request(url, **headers):
    return urllib.request.Request(url, headers={'User-Agent': 'SubtitleStudioPrototype/0.1', **headers})


def main():
    folder = ROOT/'samples/media'
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < 1024**3:
        raise RuntimeError('Requires at least 1 GiB free disk space.')
    settings = Settings.load()
    with urllib.request.urlopen(request(API), timeout=30) as response:
        info = json.load(response)
    page = next(iter(info['query']['pages'].values()))
    derivatives = page['videoinfo'][0]['derivatives']
    source = next(d['src'] for d in derivatives if d.get('transcodekey') == '240p.vp9.webm')
    prefix = folder/'gion-prefix.download.webm'
    target = folder/'Sisters_of_Gion_02m00_04m00.mkv'
    noisy = folder/'Sisters_of_Gion_02m00_04m00_noisy.mkv'
    total = 0
    try:
        if not target.exists():
            with urllib.request.urlopen(request(source, Range=f'bytes=0-{MAX_BYTES-1}'), timeout=45) as response, prefix.open('wb') as stream:
                while total < MAX_BYTES:
                    chunk = response.read(min(256*1024, MAX_BYTES-total))
                    if not chunk:
                        break
                    stream.write(chunk)
                    total += len(chunk)
            command = [settings.ffmpeg, '-hide_banner', '-nostdin', '-y', '-i', str(prefix),
                       '-ss', '120', '-t', '120', '-map', '0:v:0', '-map', '0:a:0',
                       '-c:v', 'libx264', '-preset', 'fast', '-crf', '24', '-c:a', 'copy', str(target)]
            result = subprocess.run(command, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError(result.stderr.decode('utf8', errors='replace')[-2000:])
        # Deterministic artificial degradation is a separate file; the baseline audio is retained.
        if not noisy.exists():
            filters = ('[0:a]highpass=f=250,lowpass=f=3400,volume=0.7[speech];'
                       'anoisesrc=color=pink:amplitude=0.025:sample_rate=48000:duration=120:seed=42[noise];'
                       '[speech][noise]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]')
            result = subprocess.run([settings.ffmpeg, '-hide_banner', '-nostdin', '-y', '-i', str(target),
                                     '-filter_complex', filters, '-map', '0:v:0', '-map', '[out]', '-c:v', 'copy',
                                     '-c:a', 'aac', '-b:a', '64k', str(noisy)], capture_output=True, timeout=90)
            if result.returncode:
                raise RuntimeError(result.stderr.decode('utf8', errors='replace')[-2000:])
        print('Downloaded prefix bytes:', total)
        for p in (target, noisy):
            print(str(p), p.stat().st_size)
        manifest = {'source_page': page['videoinfo'][0]['descriptionurl'], 'download_source': source,
                    'download_limit_bytes': MAX_BYTES, 'downloaded_bytes': total,
                    'source_start_seconds': 120, 'duration_seconds': 120,
                    'baseline': str(target), 'artificially_degraded': str(noisy),
                    'degradation': 'bandpass 250-3400 Hz, speech gain 0.7, seeded pink noise amplitude 0.025, AAC 64k'}
        (folder/'gion-source.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    finally:
        prefix.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

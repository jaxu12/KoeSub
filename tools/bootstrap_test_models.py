r"""Explicit, bounded installation of the user's test models to D:\models only.

Streams directly to destination, verifies published hashes and keeps no HF/pip cache.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path('D:/models')
PLAN = [
    ('cstr/qwen3-asr-1.7b-ja-anime-GGUF', 'qwen3-asr-1.7b-ja-anime-q8_0.gguf', 'asr'),
    ('cstr/qwen3-forced-aligner-0.6b-GGUF', 'qwen3-forced-aligner-0.6b-q8_0.gguf', 'asr'),
    ('lmstudio-community/Qwen3-4B-Instruct-2507-GGUF', 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf',
     'lmstudio-community/Qwen3-4B-Instruct-2507-GGUF'),
    ('ggml-org/whisper-vad', 'ggml-silero-v6.2.0.bin', 'asr'),
]
HEADERS = {'User-Agent': 'AI-Subtitle-Studio-local-model-setup/0.1'}


def json_url(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=45) as response:
        return json.load(response)


def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8*1024**2):
            value.update(chunk)
    return value.hexdigest()


def download(item):
    target = ROOT / item['relative_path']
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        if target.stat().st_size == item['bytes'] and sha256(target) == item['sha256']:
            print('Already verified:', target, flush=True)
            return target
        raise RuntimeError(f'Existing file differs from published checksum; not overwriting: {target}')
    partial = target.with_name(target.name+'.part')
    for attempt in range(3):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == item['bytes']:
            break
        if offset > item['bytes']:
            raise RuntimeError(f'Unexpected partial size: {partial}')
        if shutil.disk_usage(ROOT).free < item['bytes']-offset + 3*1024**3:
            raise RuntimeError('Less than 3 GiB disk reserve on D: after this download.')
        request = urllib.request.Request(item['url'], headers={**HEADERS, 'Range': f'bytes={offset}-'})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                resumed = offset > 0 and response.status == 206
                current = offset if resumed else 0
                next_report = current + 128*1024**2
                with partial.open('ab' if resumed else 'wb') as stream:
                    while chunk := response.read(4*1024**2):
                        current += len(chunk)
                        if current > item['bytes']:
                            raise RuntimeError('Server returned more bytes than the manifest allows.')
                        stream.write(chunk)
                        if current >= next_report:
                            print(f"{target.name}: {current/item['bytes']:.0%} ({current/1024**3:.2f} GiB)", flush=True)
                            next_report = current + 128*1024**2
                if current != item['bytes']:
                    raise RuntimeError(f'Truncated response: {current}/{item["bytes"]}')
            break
        except Exception as exc:
            print(f'Download attempt {attempt+1}/3: {exc}', flush=True)
            if attempt == 2:
                raise
            time.sleep(2)
    print('Verifying SHA-256:', target.name, flush=True)
    if sha256(partial) != item['sha256']:
        raise RuntimeError(f'Checksum mismatch; partial retained for inspection: {partial}')
    partial.replace(target)
    print('Verified:', target, flush=True)
    return target


def build_manifest():
    items = []
    for repo, filename, folder in PLAN:
        meta = json_url(f'https://huggingface.co/api/models/{repo}?blobs=true')
        record = next(s for s in meta['siblings'] if s['rfilename'] == filename)
        lfs = record['lfs']
        items.append({'repo': repo, 'revision': meta['sha'], 'filename': filename,
                      'bytes': lfs['size'], 'sha256': lfs['sha256'],
                      'relative_path': f'{folder}/{filename}',
                      'url': f'https://huggingface.co/{repo}/resolve/{meta["sha"]}/{urllib.parse.quote(filename)}?download=true'})
    release = json_url('https://api.github.com/repos/CrispStrobe/CrispASR/releases/latest')
    asset = next(a for a in release['assets'] if a['name'] == 'crispasr-windows-x86_64-vulkan.zip')
    digest = asset.get('digest', '')
    if not digest.startswith('sha256:'):
        raise RuntimeError('GitHub did not publish a SHA-256 digest for this runtime.')
    items.append({'repo': 'CrispStrobe/CrispASR', 'revision': release['tag_name'], 'filename': asset['name'],
                  'bytes': asset['size'], 'sha256': digest.split(':',1)[1],
                  'relative_path': f'.downloads/{asset["name"]}', 'url': asset['browser_download_url']})
    return {'root': str(ROOT), 'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'items': items}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest_file = ROOT/'subtitle-studio-models.json'
    manifest = json.loads(manifest_file.read_text('utf8')) if manifest_file.exists() else build_manifest()
    present = {(item['repo'],item['filename']) for item in manifest['items']}
    if any((repo,filename) not in present for repo,filename,_ in PLAN):
        fresh = build_manifest()
        manifest['items'].extend(item for item in fresh['items'] if (item['repo'],item['filename']) not in present)
    total = sum(item['bytes'] for item in manifest['items'])
    if total > 8*1024**3:
        raise RuntimeError('Model set exceeds the intended 8 GiB budget.')
    print(f'Planned download: {total/1024**3:.2f} GiB. All files and partials: {ROOT}', flush=True)
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    for item in manifest['items']:
        target = ROOT/item['relative_path']
        if item['filename'].endswith('.zip'):
            output = ROOT/'.runtime'/f'crispasr-{item["revision"]}-vulkan'
            binaries = list(output.rglob('crispasr.exe')) if output.is_dir() else []
            if not binaries:
                archive_path = download(item)
                with zipfile.ZipFile(archive_path) as archive:
                    for entry in archive.infolist():
                        destination = (output/entry.filename).resolve()
                        if not destination.is_relative_to(output.resolve()):
                            raise RuntimeError('Unsafe runtime archive path.')
                    archive.extractall(output)
                binaries = list(output.rglob('crispasr.exe'))
                if not binaries:
                    raise RuntimeError('The runtime archive did not contain crispasr.exe.')
                archive_path.unlink()  # Verified runtime retained, duplicate ZIP removed.
            manifest['crisp_exe'] = str(binaries[0])
        else:
            download(item)
    manifest['status'] = 'verified'
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    print('COMPLETE:', manifest_file, flush=True)


if __name__ == '__main__':
    main()

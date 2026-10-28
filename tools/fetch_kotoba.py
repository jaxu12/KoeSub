"""One official Kotoba GGML file, pinned and SHA256 verified; no secondary model cache."""
import json
import urllib.parse
from .bootstrap_test_models import ROOT, download, json_url


def main():
    repo = 'kotoba-tech/kotoba-whisper-v2.0-ggml'
    filename = 'ggml-kotoba-whisper-v2.0.bin'
    meta = json_url(f'https://huggingface.co/api/models/{repo}?blobs=true')
    record = next(s for s in meta['siblings'] if s['rfilename'] == filename)['lfs']
    if record['size'] > 2 * 1024**3:
        raise ValueError('Kotoba exceeds the intended single-file 2 GiB budget')
    item = dict(repo=repo, revision=meta['sha'], filename=filename,
                relative_path=f'whisper/{filename}', bytes=record['size'], sha256=record['sha256'],
                url=f'https://huggingface.co/{repo}/resolve/{meta["sha"]}/{urllib.parse.quote(filename)}?download=true')
    ROOT.mkdir(parents=True, exist_ok=True)
    receipt = ROOT / 'subtitle-studio-kotoba.json'
    receipt.write_text(json.dumps(item, indent=2), encoding='utf8')
    print('Official Kotoba v2.0 FP16:', round(item['bytes']/1024**3, 3), 'GiB; destination D:/models/whisper', flush=True)
    path = download(item)
    print('COMPLETE:', path, flush=True)


if __name__ == '__main__':
    main()

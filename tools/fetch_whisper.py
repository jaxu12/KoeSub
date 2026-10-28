"""Explicit single-model Whisper download on D:, with no secondary HF cache."""
import json
import urllib.parse

from .bootstrap_test_models import ROOT, download, json_url


def main():
    repo, filename = 'ggerganov/whisper.cpp', 'ggml-large-v3.bin'
    manifest_file = ROOT/'subtitle-studio-whisper.json'
    if manifest_file.exists():
        item = json.loads(manifest_file.read_text('utf8'))
    else:
        metadata = json_url(f'https://huggingface.co/api/models/{repo}?blobs=true')
        record = next(s for s in metadata['siblings'] if s['rfilename']==filename)
        item = {'repo':repo,'revision':metadata['sha'],'filename':filename,
                'relative_path':f'whisper/{filename}','bytes':record['lfs']['size'],
                'sha256':record['lfs']['sha256'],
                'url':f'https://huggingface.co/{repo}/resolve/{metadata["sha"]}/{urllib.parse.quote(filename)}?download=true'}
        manifest_file.write_text(json.dumps(item,indent=2),encoding='utf8')
    if item['bytes'] > 4*1024**3:
        raise RuntimeError('Single Whisper file exceeds the intended 4 GiB limit.')
    print(f'Whisper Large V3 FP16: {item["bytes"]/1024**3:.2f} GiB; destination {ROOT}',flush=True)
    path = download(item)
    print('COMPLETE:',path,flush=True)


if __name__=='__main__':
    main()

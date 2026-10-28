"""One CrispASR-compatible ReazonSpeech NeMo v2 FP16 file, pinned and hashed on D:."""
import json
import urllib.parse
from .bootstrap_test_models import ROOT,download,json_url


def main():
    repo='cstr/reazonspeech-nemo-v2-GGUF';filename='reazonspeech-nemo-v2-f16.gguf'
    meta=json_url(f'https://huggingface.co/api/models/{repo}?blobs=true')
    record=next(s for s in meta['siblings'] if s['rfilename']==filename)['lfs']
    if record['size']>2*1024**3:raise ValueError('ReazonSpeech exceeds the single-file 2 GiB budget')
    item={'repo':repo,'upstream':'reazon-research/reazonspeech-nemo-v2','revision':meta['sha'],
          'filename':filename,'relative_path':'asr/'+filename,'bytes':record['size'],'sha256':record['sha256'],
          'url':f'https://huggingface.co/{repo}/resolve/{meta["sha"]}/{urllib.parse.quote(filename)}?download=true'}
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'subtitle-studio-reazonspeech.json').write_text(json.dumps(item,indent=2),encoding='utf8')
    print('ReazonSpeech NeMo v2 FP16:',round(item['bytes']/1024**3,3),'GiB; D:/models/asr',flush=True)
    print('COMPLETE:',download(item),flush=True)


if __name__=='__main__':main()

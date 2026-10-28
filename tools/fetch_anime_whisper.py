"""Single pinned community GGML conversion of litagin/anime-whisper, directly to D:."""
import json
import urllib.parse
from .bootstrap_test_models import ROOT,download,json_url


def main():
    repo='Aratako/anime-whisper-ggml';filename='ggml-anime-whisper.bin'
    meta=json_url(f'https://huggingface.co/api/models/{repo}?blobs=true')
    record=next(s for s in meta['siblings'] if s['rfilename']==filename)['lfs']
    if record['size']>2*1024**3:raise ValueError('Anime Whisper exceeds the single-file 2 GiB budget')
    item={'repo':repo,'upstream':'litagin/anime-whisper','revision':meta['sha'],'filename':filename,
          'relative_path':'whisper/'+filename,'bytes':record['size'],'sha256':record['sha256'],
          'url':f'https://huggingface.co/{repo}/resolve/{meta["sha"]}/{urllib.parse.quote(filename)}?download=true',
          'format_note':'Community GGML conversion; not the upstream Safetensors training weights'}
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'subtitle-studio-anime-whisper.json').write_text(json.dumps(item,indent=2),encoding='utf8')
    print('Anime Whisper FP16 GGML:',round(item['bytes']/1024**3,3),'GiB; D:/models/whisper',flush=True)
    print('COMPLETE:',download(item),flush=True)


if __name__=='__main__':main()

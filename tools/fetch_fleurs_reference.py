"""Fetch five fixed FLEURS recordings, not the full corpus or any model weights."""
import argparse
import hashlib
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

import httpx

from studio.pipeline_worker import read_json, write_json
from studio.storage import Settings, check_space

REVISION = '70bb2e84b976b7e960aa89f1c648e09c59f894dd'
VIEWER = 'https://datasets-server.huggingface.co/first-rows'
PER_FILE_LIMIT = 8*1024**2
TOTAL_LIMIT = 20*1024**2


def fetch(root,offset=0,count=5):
    if not 0<=offset<100 or not 1<=count<=10 or offset+count>100: raise ValueError('Select 1–10 rows within the first 100')
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    index_path=root/'index.json'
    if index_path.exists():
        index=read_json(index_path)
        if index['revision']!=REVISION or index['selected_rows']!=list(range(offset,offset+count)):
            raise ValueError('Changed reference selection; use a new directory')
        for sample in index['samples']:
            if hashlib.sha256(Path(sample['audio']).read_bytes()).hexdigest()!=sample['audio_sha256']:
                raise ValueError('Changed reference audio')
        return index
    check_space(root,TOTAL_LIMIT,2)
    samples=[];downloaded=0
    with httpx.Client(timeout=60,follow_redirects=True,headers={'User-Agent':'KoeSub/0.1 reference evaluation'}) as client:
        response=client.get(VIEWER,params={'dataset':'google/fleurs','config':'ja_jp','split':'validation'})
        response.raise_for_status();payload=response.json()
        rows=payload['rows'][offset:offset+count]
        if [r['row_idx'] for r in rows]!=list(range(offset,offset+count)): raise ValueError('Unexpected sample order')
        for entry in rows:
            row=entry['row'];index=entry['row_idx'];source=row['audio'][0]['src']
            parsed=urlsplit(source)
            if parsed.hostname!='datasets-server.huggingface.co' or f'/--/{REVISION}/--/ja_jp/validation/{index}/audio/' not in parsed.path:
                raise ValueError('Audio revision or origin differs from the declared selection')
            temporary=root/f'row-{index}.download.wav';audio=root/f'fleurs-validation-{index:02d}.flac'
            file_hash=hashlib.sha256();size=0
            try:
                with client.stream('GET',source) as stream,temporary.open('wb') as target:
                    stream.raise_for_status()
                    if int(stream.headers.get('Content-Length',0))>PER_FILE_LIMIT: raise ValueError('Audio exceeds download budget')
                    for chunk in stream.iter_bytes(128*1024):
                        size+=len(chunk);downloaded+=len(chunk)
                        if size>PER_FILE_LIMIT or downloaded>TOTAL_LIMIT: raise ValueError('Download budget exceeded')
                        file_hash.update(chunk);target.write(chunk)
                subprocess.run([Settings.load().ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                    '-i',str(temporary),'-ac','1','-ar','16000','-c:a','flac',str(audio)],check=True,timeout=30)
            finally:
                temporary.unlink(missing_ok=True)
            duration=round(row['num_samples']/16000*1000)
            samples.append({'id':f'fleurs-validation-{index:02d}','split':'external-validation','corpus':'fleurs',
                'source_group':'google/fleurs-ja-validation','source_row':index,'source_id':row['id'],
                'audio':str(audio),'source_range_ms':[0,duration],'audio_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),
                'reference_jp':row['raw_transcription'],'human_audio_verified':False,
                'reference_status':'Published read-speech transcript; not independently audio-audited here',
                'download_source':source.split('?')[0],'download_sha256':file_hash.hexdigest(),'download_bytes':size})
            print(samples[-1]['id'],duration/1000,'seconds',size,'download bytes',flush=True)
    result={'dataset':'google/fleurs','revision':REVISION,'license':'CC BY 4.0',
        'source':'https://huggingface.co/datasets/google/fleurs','selected_rows':list(range(offset,offset+count)),
        'selection_policy':f'Contiguous Japanese validation rows {offset}–{offset+count-1}, fixed before ASR; read speech, not a movie or meeting',
        'limitation':'Separate corpus from MCDC; no claim about model-training contamination or independent speaker identities',
        'downloaded_bytes':downloaded,'samples':samples}
    write_json(index_path,result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('D:/models/datasets/koesub-fleurs-ja-v1'))
    parser.add_argument('--offset',type=int,default=0);parser.add_argument('--count',type=int,default=5)
    args=parser.parse_args();result=fetch(args.root,args.offset,args.count)
    print('Ready:',len(result['samples']),'samples;',result['downloaded_bytes'],'download bytes')


if __name__=='__main__': main()

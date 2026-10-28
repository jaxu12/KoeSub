"""Fetch the selected public subtitled test video to D:, using a verified official yt-dlp zipapp."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse
from pathlib import Path

from studio.core import atomic_text
from studio.storage import Settings

URL='https://www.youtube.com/watch?v=qzzweIQoIOU'
FOLDER=Path('D:/models/test-media/easy-japanese-1')
RUNTIME=Path('D:/models/.runtime/media-tools/yt-dlp-2026.10.26')
TOOL_URL='https://github.com/yt-dlp/yt-dlp/releases/download/2026.10.26/yt-dlp'
SHA256='e51e69e89489f199530f13d32a4342da3ddb2cf34842f364603a066db05afbf3'
NODE=Path('C:/Users/jfred/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')


def public_api_copy():
    page='https://www.bilibili.com/video/BV1yt411N7mb/?p=1'
    headers={'User-Agent':'AI-Subtitle-Studio/0.1','Referer':page}
    def get(url):
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=30) as response:
            result=json.load(response)
        if result.get('code')!=0: raise ValueError('Public API unavailable: '+str(result.get('message')))
        return result['data']
    info=get('https://api.bilibili.com/x/web-interface/view?bvid=BV1yt411N7mb')
    part=next(p for p in info['pages'] if p['page']==1)
    if part['part']!='Easy Japanese 1 - Typical Japanese' or part['duration']!=283: raise ValueError('Wrong episode')
    playback=get(f'https://api.bilibili.com/x/player/playurl?bvid=BV1yt411N7mb&cid={part["cid"]}&qn=32&fnval=1')
    streams=playback.get('durl',[])
    if len(streams)!=1 or not 280000<playback['timelength']<285000: raise ValueError('Unexpected stream structure')
    stream=streams[0];limit=75*1024**2
    if stream.get('size',limit+1)>limit: raise ValueError('Copy exceeds budget')
    urls=[stream['url'],*stream.get('backup_url',[])]
    for url in urls:
        hostname=urllib.parse.urlparse(url).hostname or ''
        if not hostname.endswith(('.bilivideo.com','.bilivideo.cn','.hdslb.com','.akamaized.net')): raise ValueError('Unexpected video CDN')
    target=FOLDER/'Easy_Japanese_1_Typical_Japanese.mp4';partial=target.with_suffix('.download')
    total=0;sha=hashlib.sha256()
    print('Public copy:',part['part'],'expected MiB:',round(stream['size']/1024**2,2),flush=True)
    if not target.exists():
        try:
            for n,url in enumerate(urls):
                total=0
                print('Public CDN:',urllib.parse.urlparse(url).hostname,flush=True)
                try:
                    # This public CDN serves the media player via HTTP byte ranges.
                    # Validate every returned range instead of accepting an empty 200.
                    with partial.open('wb') as output:
                        while total<stream['size']:
                            end=min(total+1024**2,stream['size'])-1
                            request=urllib.request.Request(url,headers={**headers,'Range':f'bytes={total}-{end}'})
                            with urllib.request.urlopen(request,timeout=30) as response:
                                chunk=response.read(end-total+2)
                                expected=f'bytes {total}-{end}/{stream["size"]}'
                                if response.status!=206 or response.headers.get('Content-Range')!=expected or len(chunk)!=end-total+1:
                                    raise ValueError('Invalid public media byte range')
                            output.write(chunk);total+=len(chunk)
                            if total%(10*1024**2)==0: print('Downloaded MiB:',total//1024**2,flush=True)
                    if total!=stream['size']: raise ValueError('Incomplete public stream')
                    partial.replace(target);break
                except urllib.error.HTTPError as error:
                    if n==len(urls)-1: raise
                    print('CDN unavailable:',error.code,'; trying API-provided backup',flush=True)
        finally: partial.unlink(missing_ok=True)
    manifest={'url':URL,'download_page':page,'public_mirror':True,'title':part['part'],
              'original_creator':'Easy Languages / Ari-TV','mirror_uploader':info.get('owner',{}).get('name'),
              'duration_seconds':playback['timelength']/1000,'video':str(target),'video_bytes':target.stat().st_size,
              'video_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'subtitle_files':[],
              'reference':'Creator burned-in JP/EN subtitles. Public mirror, visual episode check needed; not a bit-identical YouTube source.',
              'limit_bytes':limit,'retrieval':'Public unauthenticated Bilibili API; no cookies/account used'}
    atomic_text(FOLDER/'source.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    print('Downloaded:',target,'MiB:',round(target.stat().st_size/1024**2,2),flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--info-only',action='store_true')
    parser.add_argument('--public-mirror',action='store_true',help='Use the publicly indexed Bilibili copy, part 1')
    parser.add_argument('--public-api',action='store_true',help='Public Bilibili API when its HTML extractor is incompatible')
    args=parser.parse_args();FOLDER.mkdir(parents=True,exist_ok=True);RUNTIME.parent.mkdir(parents=True,exist_ok=True)
    if args.public_api:
        if shutil.disk_usage(FOLDER).free<3*1024**3: raise ValueError('Requires 3 GiB free on D:')
        public_api_copy();return
    source_url='https://www.bilibili.com/video/BV1yt411N7mb/?p=1' if args.public_mirror else URL
    platform='bilibili' if args.public_mirror else 'youtube'
    if shutil.disk_usage(FOLDER).free<3*1024**3: raise ValueError('Requires 3 GiB free on D:')
    if not RUNTIME.exists():
        request=urllib.request.Request(TOOL_URL,headers={'User-Agent':'AI-Subtitle-Studio/0.1'})
        with urllib.request.urlopen(request,timeout=45) as response: data=response.read(4*1024**2)
        if len(data)!=3073072 or hashlib.sha256(data).hexdigest()!=SHA256: raise ValueError('Invalid official yt-dlp checksum')
        RUNTIME.write_bytes(data)
        atomic_text(RUNTIME.with_suffix('.receipt.json'),json.dumps({'url':TOOL_URL,'sha256':SHA256,'bytes':len(data)},indent=2))
    elif hashlib.sha256(RUNTIME.read_bytes()).hexdigest()!=SHA256: raise ValueError('Changed media tool checksum')
    settings=Settings.load()
    base=[sys.executable,str(RUNTIME),'--ignore-config','--no-playlist','--no-cache-dir','--socket-timeout','25',
          '--retries','2','--fragment-retries','2','--extractor-retries','1','--js-runtimes','node:'+str(NODE),
          '--remote-components','ejs:github','--ffmpeg-location',settings.ffmpeg]
    info_path=FOLDER/('metadata.'+platform+'.json');log_path=FOLDER/('download.'+platform+'.log')
    print('Fetching public video metadata; all media/cache on D:',flush=True)
    with info_path.open('wb') as output,log_path.open('wb') as log:
        result=subprocess.run([*base,'--skip-download','--dump-single-json',source_url],stdout=output,stderr=log,timeout=180)
    if result.returncode:
        raise RuntimeError(log_path.read_text('utf8',errors='replace')[-4500:])
    info=json.loads(info_path.read_text('utf8'))
    if (not args.public_mirror and info['id']!='qzzweIQoIOU') or not 240<float(info['duration'])<330: raise ValueError('Unexpected test video')
    print('Video:',info['title'],'duration:',info['duration'],'manual subtitle languages:',list(info.get('subtitles',{})),flush=True)
    if args.info_only: return
    with log_path.open('ab') as log:
        command=[*base,'--format','bv*[height<=720]+ba/b[height<=720]/b','--max-filesize','250M',
                 '--paths',str(FOLDER),'--paths','temp:'+str(FOLDER/'.download'),
                 '--output','Easy_Japanese_1_Typical_Japanese.%(ext)s','--merge-output-format','mkv',
                 '--write-subs','--sub-langs','ja,en','--sub-format','srt/vtt/best','--convert-subs','srt',
                 '--no-progress',source_url]
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    if result.returncode: raise RuntimeError(log_path.read_text('utf8',errors='replace')[-4500:])
    media=[p for p in FOLDER.iterdir() if p.suffix in {'.mkv','.mp4','.webm'}]
    if len(media)!=1: raise ValueError('Ambiguous or missing downloaded video')
    manifest={'url':URL,'download_page':source_url,'public_mirror':args.public_mirror,
              'title':info['title'],'uploader':info.get('uploader'),'original_creator':'Easy Languages / Ari-TV',
              'duration_seconds':info['duration'],
              'video':str(media[0]),'video_bytes':media[0].stat().st_size,
              'video_sha256':hashlib.sha256(media[0].read_bytes()).hexdigest(),
              'manual_subtitle_languages':list(info.get('subtitles',{})),
              'subtitle_files':[str(p) for p in FOLDER.glob('*.srt')],
              'reference':'Creator burned-in JP/EN subtitles; downloaded captions are existing manual tracks only, never our ASR.',
              'tool_sha256':SHA256,'limit_bytes_per_stream':250*1024**2}
    atomic_text(FOLDER/'source.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    print('Downloaded:',media[0],'MiB:',round(media[0].stat().st_size/1024**2,2),flush=True)
    print('Existing subtitles:',manifest['subtitle_files'],flush=True)


if __name__=='__main__': main()

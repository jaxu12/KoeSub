"""Fetch one Commons Japanese recording and existing JP/EN reference subtitles, with a bounded download."""
import hashlib
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from studio.core import atomic_text,load_srt

TITLE='MCDC Onboarding "Ask me Anything" session - Japanese language.webm'
FOLDER=Path('D:/models/test-media/mcdc-japanese')
LIMIT=90*1024**2


def api(**params):
    url='https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode({'format':'json','formatversion':2,**params})
    request=urllib.request.Request(url,headers={'User-Agent':'AI-Subtitle-Studio/0.1 (local subtitle comparison)'})
    with urllib.request.urlopen(request,timeout=45) as response:
        payload=response.read(3*1024**2+1)
    if len(payload)>3*1024**2: raise ValueError('Metadata exceeds limit')
    return json.loads(payload)


def normalize_srt(raw):
    raw=raw.replace('\r\n','\n').replace('\r','\n')
    pattern=re.compile(r'(?m)^\s*(\d+)[ \t]*\n(\d{1,3}:\d{2}:\d{2}[,.]\d{3}[ \t]*-->[^\n]+)(?:\n|$)')
    matches=list(pattern.finditer(raw))
    if not matches or len(matches)!=raw.count('-->'): raise ValueError('Unrecognized reference SRT structure')
    blocks=[];empty=[]
    for i,match in enumerate(matches):
        text=raw[match.end():matches[i+1].start() if i+1<len(matches) else len(raw)].strip()
        if not text:
            empty.append(int(match[1]))
            continue
        blocks.append(f'{len(blocks)+1}\n{match[2].strip()}\n{text}')
    return '\n\n'.join(blocks)+'\n',empty


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    FOLDER.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(FOLDER).free<LIMIT+2*1024**3: raise ValueError('Insufficient free space')
    page=api(action='query',prop='videoinfo',viprop='url|derivatives|size|sha1',titles='File:'+TITLE)['query']['pages'][0]
    info=page['videoinfo'][0]
    derivative=next(d for d in info['derivatives'] if d.get('transcodekey')=='240p.vp9.webm')
    target=FOLDER/'MCDC-Japanese-23m-240p.webm'
    references={}
    for language in ('ja','en'):
        title='TimedText:'+TITLE+'.'+language+'.srt'
        result=api(action='query',prop='revisions',rvprop='ids|timestamp|user|comment|content',rvslots='main',titles=title)
        revision=result['query']['pages'][0]['revisions'][0]
        content=revision['slots']['main']['content']
        atomic_text(FOLDER/f'reference.{language}.original.srt',content)
        normalized=FOLDER/f'reference.{language}.srt'
        normalized_text,empty=normalize_srt(content)
        atomic_text(normalized,normalized_text)
        track=load_srt(normalized)
        references[language]={'path':str(normalized),'original_path':str(FOLDER/f'reference.{language}.original.srt'),
                              'source':'https://commons.wikimedia.org/wiki/'+urllib.parse.quote(title,safe=''),
                              'revision':{k:revision.get(k) for k in ('revid','timestamp','user','comment')},
                              'cues':len(track.segments),'sha256':hashlib.sha256(content.encode()).hexdigest(),
                              'normalization':'Cue separators/numbering only; nonempty text and times preserved',
                              'omitted_empty_source_cues':empty,
                              'quality':'Community reference subtitles; not independently verified verbatim gold'}
        print(language,':',len(track.segments),'existing reference cues',flush=True)
    manifest={'source_page':info['descriptionurl'],'author':'TCappelletto (WMF)',
              'video_license':'CC BY-SA 4.0','video_license_url':'https://creativecommons.org/licenses/by-sa/4.0/',
              'subtitle_attribution':'Wikimedia Commons TimedText contributors; revision IDs recorded below',
              'download_source':derivative['src'],'download_limit_bytes':LIMIT,'video':str(target),
              'references':references}
    if not target.exists():
        partial=target.with_suffix('.download')
        total=0
        try:
            request=urllib.request.Request(derivative['src'],headers={'User-Agent':'AI-Subtitle-Studio/0.1'})
            with urllib.request.urlopen(request,timeout=60) as response,partial.open('wb') as stream:
                if int(response.headers.get('Content-Length',0))>LIMIT: raise ValueError('Video exceeds download budget')
                while chunk:=response.read(256*1024):
                    total+=len(chunk)
                    if total>LIMIT: raise ValueError('Video exceeds download budget')
                    stream.write(chunk)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    manifest['downloaded_bytes']=target.stat().st_size
    manifest['video_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    atomic_text(FOLDER/'source.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    print('Video:',target,'bytes:',target.stat().st_size,flush=True)
    print('Source/revisions:',FOLDER/'source.json',flush=True)


if __name__=='__main__': main()

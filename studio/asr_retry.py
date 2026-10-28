"""Audio-grounded retry planning. Alternatives cannot outvote the baseline by themselves."""
from dataclasses import asdict
import math
import re

from .core import normalize
from .pipeline import digest


def token_confidence(document,track,offset=0):
    entries=document.get('transcription',[])
    result={}
    for cue in track.segments:
        values=[]
        for entry in entries:
            span=entry.get('offsets',{})
            start,end=span.get('from',-1)+offset,span.get('to',-1)+offset
            if min(end,cue.end)<=max(start,cue.start): continue
            for token in entry.get('tokens',[]):
                text=token.get('text','').strip()
                probability=token.get('p')
                if not text or text.startswith('<|') or not isinstance(probability,(int,float)) or not math.isfinite(probability): continue
                times=token.get('offsets',span)
                mid=(times.get('from',span.get('from',0))+times.get('to',span.get('to',0)))/2+offset
                if cue.start<=mid<=cue.end: values.append(float(probability))
        if values:
            result[cue.id]={'mean':sum(values)/len(values),'low_ratio':sum(p<.4 for p in values)/len(values),'tokens':len(values)}
    return result


def suspects(track,confidence):
    result=[]
    for i,cue in enumerate(track.segments):
        if cue.status=='manual' or cue.review_status=='reviewed': continue
        score=confidence.get(cue.id,{})
        reasons=[];priority=0
        if score.get('mean',1)<.78 or score.get('low_ratio',0)>=.2:
            reasons.append('Niska pewność tokenów ASR — wskaźnik ryzyka, nie dowód błędu')
            priority=1-score.get('mean',1)+score.get('low_ratio',0)
        if re.search(r'(.{2,12}?)\1{3,}',normalize(cue.text)):
            reasons.append('Wielokrotne powtórzenie tekstu');priority+=1
        if i and normalize(cue.text)==normalize(track.segments[i-1].text) and cue.start-track.segments[i-1].end<500:
            reasons.append('Powtórzenie sąsiedniego napisu');priority+=.5
        if re.fullmatch(r'[\s。！？!?.,、…]+',cue.text):
            reasons.append('Sama interpunkcja');priority+=1
        if reasons: result.append({'id':cue.id,'start':cue.start,'end':cue.end,'reasons':reasons,'priority':priority})
    return sorted(result,key=lambda item:(-item['priority'],item['start']))


def retry_windows(track,confidence,start,end,padding=3000,max_window=30000,max_targets=12,additional_targets=()):
    selected=suspects(track,confidence)
    if additional_targets:
        merged={s['id']:s for s in selected}
        primary=[s['id'] for s in selected]
        for extra in additional_targets:
            if extra['id'] in merged:
                old=merged[extra['id']]
                old.update(signals=sorted(set(old.get('signals',[])+extra.get('signals',[]))),
                    reasons=old['reasons']+extra['reasons'])
            else: merged[extra['id']]=extra
        extras=sorted((v for key,v in merged.items() if key not in primary),key=lambda item:(-item['priority'],item['start']))
        selected=[merged[key] for key in primary]+extras
    windows=[];covered=set();skipped=[]
    for item in selected:
        if item['id'] in covered: continue
        if len(windows)>=max_targets:
            skipped.append({'id':item['id'],'reason':'Limit wycinków w jednym przebiegu'});continue
        left=max(start,item['start']-padding);right=min(end,item['end']+padding)
        while True:
            cues=[s for s in track.segments if s.start<right and s.end>left]
            expanded=(min([left]+[s.start for s in cues]),max([right]+[s.end for s in cues]))
            if expanded==(left,right): break
            left,right=expanded
        if right-left>max_window or any(s.status=='manual' or s.review_status=='reviewed' for s in cues):
            skipped.append({'id':item['id'],'reason':'Zbyt długi wycinek lub ręcznie sprawdzony tekst w kontekście'});continue
        ids=[s.id for s in cues]
        if covered.intersection(ids):
            skipped.append({'id':item['id'],'reason':'Wycinek przecina wcześniej wybrany kontekst'});continue
        covered.update(ids)
        related=[s for s in selected if s['id'] in ids]
        windows.append({'id':digest([left,right,ids])[:16],'start':left,'end':right,'cue_ids':ids,
                        'suspects':related,'before':[asdict(s) for s in cues]})
    return sorted(windows,key=lambda item:item['start']),skipped


def consensus(window,attempts):
    usable=[a for a in attempts if a.get('usable')]
    if len(usable)<2: return False,'Brak dwóch poprawnych ponowień; zachowano bazę'
    first,second=usable[:2]
    text=lambda a:normalize(''.join(s['text'] for s in a['track']['segments']))
    original=normalize(''.join(s['text'] for s in window['before']))
    if not text(first) or text(first)!=text(second): return False,'Ponowienia różnią się; zachowano Large V3'
    if text(first)==original: return False,'Ponowienia potwierdzają tekst bazy'
    if first.get('mean_confidence') is None or first['mean_confidence']<.65: return False,'Ponowienie bazy ma niską lub niedostępną pewność'
    for candidate in usable[:2]:
        cues=sorted(candidate['track']['segments'],key=lambda s:(s['start'],s['end']))
        if not cues or any(s['start']<window['start'] or s['end']>window['end'] or s['end']<=s['start'] for s in cues):
            return False,'Wadliwe granice wycinka'
        if any(a['end']>b['start'] for a,b in zip(cues,cues[1:])): return False,'Nakładanie w ponowieniu'
    before=window['before']
    if len(before)<3: return False,'Za mało pełnego kontekstu do bezpiecznej automatycznej zamiany'
    suspects_ids={s['id'] for s in window['suspects']}
    if before[0]['id'] in suspects_ids or before[-1]['id'] in suspects_ids:
        return False,'Niepewny tekst na granicy kontekstu; zachowano bazę'
    if not text(first).startswith(normalize(before[0]['text'])) or not text(first).endswith(normalize(before[-1]['text'])):
        return False,'Ponowienie zmienia także granice kontekstu; zachowano bazę'
    return True,'Zgodność dwóch ponowień audio i zachowany kontekst; wynik nadal wymaga odsłuchu'

"""Reference-free ASR disagreement targeting and reuse of whole scan cues."""
from bisect import bisect_left, bisect_right
from copy import deepcopy
from dataclasses import asdict
from difflib import SequenceMatcher

from .core import Track, normalize
from .pipeline import track_from


def usable_scan(track):
    cues=track.segments
    return bool(cues) and all(s.start<s.end for s in cues) and all(a.end<=b.start for a,b in zip(cues,cues[1:]))


def disagreement_targets(base,scan):
    """Compare only nearby audio intervals, never infer which hypothesis is right."""
    if not usable_scan(scan): return []
    starts=[s.start for s in scan.segments];ends=[s.end for s in scan.segments]
    result=[]
    for index,cue in enumerate(base.segments):
        if cue.status=='manual' or cue.review_status=='reviewed': continue
        context=base.segments[max(0,index-1):index+2]
        left=min(s.start for s in context);right=max(s.end for s in context)
        candidates=scan.segments[bisect_right(ends,left):bisect_left(starts,right)]
        text=''.join(normalize(s.text) for s in context)
        start=sum(len(normalize(s.text)) for s in context[:context.index(cue)])
        end=start+len(normalize(cue.text))
        alternative=''.join(normalize(s.text) for s in candidates)
        if not text or start==end: continue
        changed=0
        for tag,i,j,k,l in SequenceMatcher(None,text,alternative,autojunk=False).get_opcodes():
            if tag=='equal': continue
            overlap=max(0,min(j,end)-max(i,start))
            if overlap: changed+=max(overlap,min(l-k,overlap+2))
            elif i==j and start<i<end: changed+=l-k
        if not changed: continue
        result.append({'id':cue.id,'start':cue.start,'end':cue.end,
            'signals':['asr_disagreement'],'priority':.5+min(1,changed/(end-start)),
            'reasons':['ASR disagreement — matching audio, different text; not proof of an error'],
            'changed_characters':changed,'auxiliary_cue_ids':[s.id for s in candidates],
            'baseline_text':cue.text,'auxiliary_context':' '.join(s.text for s in candidates)})
    return sorted(result,key=lambda item:(-item['priority'],item['start']))


def reuse_scan(window,scan_result,model,directory):
    """Reuse only complete cues with real timestamps covering every target."""
    if not scan_result or not scan_result.get('usable',True): return None
    scan=track_from(scan_result['track'])
    if not usable_scan(scan): return None
    cues=[s for s in scan.segments if window['start']<=s.start<s.end<=window['end']]
    if not cues: return None
    targets={s['id'] for s in window['suspects']}
    for source in window['before']:
        if source['id'] not in targets: continue
        if not any(min(s.end,source['end'])-max(s.start,source['start'])>=.5*(source['end']-source['start']) for s in cues):
            return None
    selected=Track(scan.name,deepcopy(cues),origin=deepcopy(scan.origin))
    confidence={s.id:deepcopy(scan_result.get('confidence',{}).get(s.id,{})) for s in cues}
    means=[c['mean'] for c in confidence.values() if 'mean' in c]
    return {'track':asdict(selected),'confidence':confidence,'usable':True,
        'mean_confidence':sum(means)/len(means) if means else None,
        'model':model['model'],'name':model['name'],'seconds':0,
        'directory':str(scan_result.get('native_directory',directory)),'reused_from':'asr-scan'}

"""Validate an explicit human ASR phrase choice against the current project."""
import re


def choice_preview(project,result,row,alternative,job):
    if not project.active: raise ValueError('Select a subtitle track first')
    if not 0<=row<len(result['fragments']): raise ValueError('Select a comparison row')
    fragment=result['fragments'][row]
    if alternative==-1:
        candidate={'usable':True,'temporal':True,'text':fragment['before'],'model':'original-baseline','directory':''}
    elif isinstance(alternative,int) and 0<=alternative<len(fragment['alternatives']):candidate=fragment['alternatives'][alternative]
    else:raise ValueError('Select an ASR alternative')
    if not candidate['usable'] or not candidate['temporal'] or not candidate['text']:
        raise ValueError('This alternative has no usable time-matched phrase')
    start,end=fragment['text_start'],fragment['text_end'];original=fragment['context']
    if start==end or original[start:end]!=fragment['before']:
        raise ValueError('Structural changes require editing the cue directly')
    expected_cues=[s for s in result['track']['segments'] if fragment['cue_id'] in s.get('parents',[])]
    if len(expected_cues)!=1: raise ValueError('Ambiguous source cue')
    expected=expected_cues[0]
    if (fragment['start'],fragment['end'])!=(expected['start'],expected['end']):
        raise ValueError('Cross-cue changes require direct editing')
    lookup={s.id:s for track in project.tracks for s in track.segments}
    def descendant(cue):
        pending=[cue.id];seen=set()
        while pending:
            key=pending.pop()
            if key==expected['id']: return True
            if key in seen: continue
            seen.add(key)
            if key in lookup: pending.extend(lookup[key].parents)
        return False
    targets=[s for s in project.active.segments if descendant(s) and (s.start,s.end)==(expected['start'],expected['end'])]
    if len(targets)!=1: raise ValueError('The active track no longer matches this source cue')
    target=targets[0]
    prior=[v for v in job.get('manual_source_choices',[]) if v['track_id']==project.active.id
           and v['review_track_id']==result['track']['id'] and v['cue_id']==fragment['cue_id']]
    if target.review_status=='reviewed' or target.status=='manual' and not prior:
        raise ValueError('This cue has already been manually edited or reviewed')
    edits={(c['text_start'],c['text_end']):c for c in result['changes'] if c['cue_id']==fragment['cue_id']}
    for c in prior: edits[c['text_start'],c['text_end']]=c
    def render(values):
        ordered=sorted(values.items())
        if any(a[0][1]>b[0][0] for a,b in zip(ordered,ordered[1:])):raise ValueError('Overlapping phrase choices')
        text=original
        for (a,b),change in reversed(ordered):
            if original[a:b]!=change['before']:raise ValueError('Stale phrase coordinates')
            text=text[:a]+change['after']+text[b:]
        return text
    compact=lambda text:re.sub(r'\s+','',text)
    if compact(target.text)!=compact(render(edits)):
        raise ValueError('The cue changed after this comparison; review the current text first')
    record={'track_id':project.active.id,'target_id':target.id,'review_track_id':result['track']['id'],
        'cue_id':fragment['cue_id'],'row':row,'text_start':start,'text_end':end,'before':fragment['before'],
        'after':candidate['text'],'model':candidate['model'],'directory':candidate['directory']}
    edits[start,end]=record;new_text=render(edits)
    if compact(new_text)==compact(target.text): return None
    return {'target':target,'text':new_text,'record':record}

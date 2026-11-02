"""Automatic repair of isolated ASR timing defects, before strict downstream use.

Keep raw hypotheses, protect manual work, preserve text, and distinguish reading
exposure from acoustic boundaries. Unsupported repairs remain explicit failures.
"""
from copy import deepcopy
from dataclasses import asdict
import math
import time

from .audio_boundaries import audio_digest
from .core import normalize, uid
from .pipeline import clone_track, digest, track_from
from .review import char_count, metrics


def protected(cue):
    return cue.status=='manual' or cue.review_status=='reviewed' or bool(cue.translation)


def timing_issues(track,start,end):
    result=[]
    for i,cue in enumerate(track.segments):
        reasons=[]
        if not start<=cue.start<cue.end<=end:reasons.append('Invalid or out-of-range duration')
        if i and track.segments[i-1].end>cue.start:reasons.append('Overlapping previous cue')
        if reasons:result.append({'index':i,'cue_id':cue.id,'reasons':reasons})
    return result


def boundary_merge(track,index,rules,limit):
    """Attach a short zero-duration suffix at an existing end boundary.

    Up to 250 ms of explicit display hold may satisfy reading exposure; no new
    speech interval is inferred. This never changes protected/translated cues.
    """
    cues=track.segments;zero=cues[index]
    if index==0 or protected(zero) or zero.start!=zero.end or not 0<char_count(zero.text)<=4:return None
    if zero.text.lstrip().startswith(('-', '—', '–')) or any(c in zero.text for c in ':：'):return None
    previous=cues[index-1]
    if protected(previous) or previous.end!=zero.start or previous.start>=previous.end:return None
    if previous.start<0 or previous.end>limit or previous.end-previous.start>rules.max_ms:return None
    text=previous.text+zero.text
    if char_count(text)>rules.jp_line*rules.max_lines:return None
    rate=max(rules.jp_cps,metrics(previous.text,previous.end-previous.start)['cps'])
    required=max(rules.min_ms,math.ceil(char_count(text)*1000/rate))
    finish=max(previous.end,previous.start+required)
    next_limit=limit
    if index+1<len(cues):
        gap=max(0,cues[index+1].start-previous.end)
        next_limit=cues[index+1].start-min(rules.gap_ms,gap)
    ceiling=min(limit,previous.end+250,next_limit)
    if finish>ceiling or finish-previous.start>rules.max_ms:return None
    merged=deepcopy(previous);merged.id=uid();merged.parents=[previous.id,zero.id]
    merged.text=text;merged.end=finish;merged.source='asr-timing-review-boundary-merge';merged.review_status='unreviewed';merged.translation_key=''
    merged.notes=list(dict.fromkeys(previous.notes+zero.notes+['Timing review: zero-duration suffix merged at its shared boundary; original hypotheses retained.']))
    hold=finish-previous.end
    if hold:merged.notes.append(f'Timing review: {hold} ms display hold for reading; source boundary unchanged.')
    return merged,{'action':'boundary_suffix_merge','before':[asdict(previous),asdict(zero)],'after':[asdict(merged)],
        'source_end':previous.end,'display_hold_ms':hold,'scope':'Formal boundary/exposure repair; no independent speech verification'}


def retry_window(track,index,padding,start,end):
    target=track.segments[index]
    if protected(target) or target.start<start or target.start>end or abs(target.end-target.start)>30000:return None
    left=max(start,min(target.start,target.end)-padding);right=min(end,max(target.start,target.end)+padding)
    while True:
        indices=[i for i,c in enumerate(track.segments) if c.start<=right and c.end>=left]
        if not indices:return None
        if any(protected(track.segments[i]) for i in indices):return None
        a=min(left,*(track.segments[i].start for i in indices));b=max(right,*(track.segments[i].end for i in indices))
        if b-a>30000 or a<start or b>end:return None
        if (a,b)==(left,right):break
        left,right=a,b
    return {'start':left,'end':right,'indices':indices}


def retry_replacement(original,candidate,start,end):
    """Accept measured native bounds only when the complete text is retained."""
    if not candidate.segments or timing_issues(candidate,start,end):return None
    if any(protected(c) for c in original):return None
    source=''.join(c.text for c in original)
    if normalize(source)!=normalize(''.join(c.text for c in candidate.segments)):return None
    positions=[i for i,c in enumerate(source) for _ in normalize(c)]
    if not positions:return None
    if ''.join(normalize(c) for c in source)!=normalize(source):return None
    at=0;cursor=0;output=[]
    for i,cue in enumerate(candidate.segments):
        length=len(normalize(cue.text))
        if not length:return None
        at+=length
        if at>len(positions):return None
        if i<len(candidate.segments)-1 and at>=len(positions):return None
        if i<len(candidate.segments)-1 and positions[at]==positions[at-1]:return None
        cut=len(source) if i==len(candidate.segments)-1 else positions[at]
        restored=deepcopy(cue);restored.id=uid();restored.text=source[cursor:cut];cursor=cut
        if not restored.text.strip():return None
        restored.parents=[c.id for c in original];restored.translation_key='';restored.review_status='unreviewed'
        restored.source='asr-timing-review-audio-retry'
        restored.notes=list(dict.fromkeys([note for c in original for note in c.notes]+['Timing review: text preserved with measured local retry bounds.']))
        output.append(restored)
    if at!=len(positions) or ''.join(c.text for c in output)!=source:return None
    return output


def repair_timing(runner,folder,raw,audio):
    from .pipeline_worker import AsrQualityError,read_json,write_json
    original=track_from(raw['track']);options=runner.config['asr_timing_review']
    start=runner.config['start'];end=start+runner.config['duration'];item=runner.config['asr'][0]
    key=digest([1,raw,options,audio_digest(audio),item,runner.config.get('xxl_compute'),runner.config.get('xxl_device')])
    path=folder/'partial.json'
    if path.exists():
        state=read_json(path)
        if state['source']!=key:raise ValueError('Changed timing review source')
        if state.get('checkpoint_digest')!=digest({k:v for k,v in state.items() if k!='checkpoint_digest'}):raise ValueError('Changed timing review checkpoint')
    else:
        track=clone_track(original,'Pipeline • automatic ASR timing review')
        state={'source':key,'track':asdict(track),'changes':[],'attempts':[],'audio_targets':[]}
    def checkpoint():
        state['checkpoint_digest']=digest({k:v for k,v in state.items() if k!='checkpoint_digest'})
        write_json(path,state)
    checkpoint()
    track=track_from(state['track']);initial=timing_issues(original,start,end)
    while True:
        issues=timing_issues(track,start,end)
        if not issues:break
        index=issues[0]['index'];cue=track.segments[index]
        proposal=boundary_merge(track,index,runner.rules,end)
        if proposal:
            merged,change=proposal
            track.segments[index-1:index+1]=[merged];state['changes'].append(change)
            runner.event('phase',message='Timing review • repaired a zero-duration suffix at an existing boundary')
        else:
            targets=state.setdefault('audio_targets',[])
            if cue.id not in targets:
                if len(targets)>=options.get('max_targets',8):raise AsrQualityError('Timing review audio target budget exhausted; raw hypotheses retained')
                targets.append(cue.id);checkpoint()
            accepted=False;seen=set()
            for padding in (6000,12000):
                window=retry_window(track,index,padding,start,end)
                if not window or (window['start'],window['end']) in seen:continue
                seen.add((window['start'],window['end']))
                before=[track.segments[i] for i in window['indices']]
                identity=digest([key,window,[asdict(c) for c in before]])
                directory=folder/('retry-'+identity[:16]);directory.mkdir(exist_ok=True)
                receipt=directory/'receipt.json'
                if receipt.exists():
                    saved=read_json(receipt)
                    if saved['identity']!=identity or digest(saved['result'])!=saved['digest']:raise ValueError('Changed timing retry receipt')
                    if not (directory/'retry.wav').is_file() or audio_digest(directory/'retry.wav')!=saved['audio_sha256']:raise ValueError('Changed timing retry crop')
                    value=saved['result']
                else:
                    # Interrupted output never becomes evidence for a new call.
                    stale=list(directory.glob('*.srt'))+[p for p in (directory/'retry.json',directory/'transcript.json',directory/'engine.log') if p.exists()]
                    if stale:
                        archive=directory/'previous-uncommitted'/uid();archive.mkdir(parents=True)
                        for p in stale:p.replace(archive/p.name)
                    wav=directory/'retry.wav';partial=directory/'retry.partial.wav'
                    vocal=item['engine']==0 and runner.settings.whisper_vocal_extract=='mdx_kim2'
                    runner.call([runner.settings.ffmpeg,'-hide_banner','-nostdin','-y','-ss',str((window['start']-start)/1000),
                        '-i',str(audio),'-t',str((window['end']-window['start'])/1000),'-ac','2' if vocal else '1','-ar','44100' if vocal else '16000',
                        '-c:a','pcm_s16le',str(partial)],directory,'crop',120)
                    if not partial.exists() or partial.stat().st_size<=44:raise ValueError('Incomplete timing-review audio crop')
                    partial.replace(wav);began=time.monotonic()
                    runner.event('phase',message=f'Timing review • local audio retry {(window["end"]-window["start"])/1000:.1f} s')
                    try:
                        value=runner.retry_decode(directory,item,wav,window['start'],window['end']);value['usable']=True
                    except AsrQualityError as exc:
                        log=directory/'engine.log'
                        detail=log.read_text('utf8',errors='replace').lower() if log.exists() else str(exc).lower()
                        if any(s in detail for s in ('out of memory','allocation failed','falling back')):
                            raise RuntimeError('Device/memory failure during timing retry; see '+str(log)) from exc
                        value={'usable':False,'error':str(exc)}
                    except ValueError as exc:
                        log=directory/'engine.log'
                        detail=log.read_text('utf8',errors='replace').lower() if log.exists() else str(exc).lower()
                        if any(s in detail for s in ('out of memory','allocation failed','falling back')) or 'no speech detected' not in detail:raise
                        value={'usable':False,'error':str(exc)}
                    value['seconds']=round(time.monotonic()-began,3)
                    write_json(receipt,{'identity':identity,'result':value,'digest':digest(value),'audio_sha256':audio_digest(wav)})
                state['attempts'].append({'window':window,'receipt':str(receipt),'usable':value['usable']})
                replacement=retry_replacement(before,track_from(value['track']),window['start'],window['end']) if value['usable'] else None
                if replacement:
                    first,last=window['indices'][0],window['indices'][-1]
                    proposed=deepcopy(track);proposed.segments[first:last+1]=replacement
                    if len(timing_issues(proposed,start,end))>=len(issues):continue
                    state['changes'].append({'action':'text_preserving_audio_retry','before':[asdict(c) for c in before],
                        'after':[asdict(c) for c in replacement],'receipt':str(receipt),'display_hold_ms':0})
                    track=proposed;accepted=True;break
            if not accepted:
                state['track']=asdict(track);checkpoint()
                raise AsrQualityError('No supported automatic timing repair; original hypotheses and local attempts retained')
        state['track']=asdict(track);checkpoint()
    if ''.join(c.text for c in track.segments)!=''.join(c.text for c in original.segments):raise ValueError('Timing review changed source text')
    scores=raw.get('confidence',{})
    confidence={c.id:scores[c.parents[0]] for c in track.segments if len(c.parents)==1 and c.parents[0] in scores}
    return {**state,'confidence':confidence,'initial_issues':initial,'fixed_issues':len(initial),'raw_track':asdict(original),
        'scope':'Automatic timing review; source text and raw hypotheses preserved; display hold is not speech alignment'}

"""Final source alignment and phrase splitting using measured word boundaries.

The aligner cannot verify transcript correctness. Invalid or conflicting timing
keeps the input cue; no proportional or zero-duration timestamp repair is used.
"""
from copy import deepcopy
from dataclasses import asdict
import math
import re

from .adapters import validate_crisp_backend,validate_flags
from .core import normalize,uid
from .pipeline import clone_track,digest
from .review import char_count
from .audio_boundaries import audio_digest


def _milliseconds(value):
    if type(value) not in (float,int) or not math.isfinite(value):raise ValueError('Non-finite alignment time')
    return round(value*1000)


def aligned_words(cue,entry,offset,end):
    if normalize(entry.get('text',''))!=normalize(cue.text):raise ValueError('Alignment changed transcript text')
    start=_milliseconds(entry['start'])+offset;finish=_milliseconds(entry['end'])+offset
    if not offset<=start<finish<=end:raise ValueError('Invalid aligned cue bounds')
    raw=entry.get('words',[])
    if not isinstance(raw,list) or not raw or len(raw)>10000:raise ValueError('Missing aligned words')
    tokens=[]
    for word in raw:
        if not isinstance(word,dict) or not isinstance(word.get('word'),str):raise ValueError('Invalid aligned word')
        text=word['word']
        if not normalize(text):continue
        a=_milliseconds(word['start'])+offset;b=_milliseconds(word['end'])+offset
        if not offset<=a<=b<=end:raise ValueError('Invalid aligned word')
        if a<start-20 or b>finish+20:raise ValueError('Word outside aligned cue')
        tokens.append({'text':text,'start':a,'end':b})
    if not tokens or normalize(''.join(w['text'] for w in tokens))!=normalize(cue.text):raise ValueError('Incomplete aligned text coverage')
    if sum(w['start']==w['end'] for w in tokens)/len(tokens)>.35:raise ValueError('Excessive zero-duration alignment tokens')
    if any(a['end']>b['start'] for a,b in zip(tokens,tokens[1:])):raise ValueError('Overlapping aligned words')
    # Japanese particles/long vowels may have a zero-duration token at an
    # adjacent word's boundary. Coalesce text onto an actual measured interval,
    # never interpolate or invent a positive interval for that token.
    merged=[];pending='';pending_at=None
    for word in tokens:
        if word['start']==word['end']:
            if merged and abs(merged[-1]['end']-word['start'])<=20:merged[-1]['text']+=word['text']
            else:
                if pending_at is not None and abs(pending_at-word['start'])>20:raise ValueError('Unattached zero-duration word')
                pending+=word['text'];pending_at=word['start']
            continue
        if pending:
            # Only leading zero tokens at this same acoustic boundary are safe.
            if abs(word['start']-pending_at)>20:raise ValueError('Unattached zero-duration word')
            word=dict(word,text=pending+word['text']);pending='';pending_at=None
        merged.append(dict(word))
    if pending or not merged:raise ValueError('Unattached zero-duration word')
    # Coverage, raw character offsets and actual measured word times are kept.
    positions=[i for i,c in enumerate(cue.text) for _ in normalize(c)]
    at=0
    for word in merged:
        length=len(normalize(word['text']))
        word['text_start']=positions[at];at+=length;word['text_end']=positions[at-1]+1
    if at!=len(positions):raise ValueError('Alignment character map mismatch')
    return start,finish,merged


def _break_allowed(text,at,pause):
    if not 0<at<len(text) or text[at] in '、。，！？!?）」』】' or text[at-1] in '（「『【':return False
    if text[at-1].isascii() and text[at].isascii() and text[at-1].isalnum() and text[at].isalnum():return False
    if text[at-1] in '。！？!?、，,；;' or pause>=160:return True
    # Conservative script/particle boundary; do not cut a continuous kanji or
    # katakana compound just because the aligner emits one token per character.
    return text[at-1] in 'はがをにでとのもへやかねよ' and bool(re.match('[一-龯ァ-ヺ]',text[at]))


def split_aligned(cue,words,rules):
    if cue.translation:return None
    if char_count(cue.text)<=rules.jp_line*rules.max_lines and cue.end-cue.start<=rules.max_ms:return None
    points=[(0,cue.start,0)]
    for index,(left,right) in enumerate(zip(words,words[1:])):
        at=right['text_start']
        if _break_allowed(cue.text,at,right['start']-left['end']):
            points.append((at,left['end'],index+1))
    points.append((len(cue.text),cue.end,len(words)))
    states={0:(0,[])}
    for j in range(1,len(points)):
        best=None
        for i,(cost,path) in list(states.items()):
            if i>=j:continue
            a=points[i][0];b=points[j][0]
            begin=cue.start if i==0 else words[points[i][2]]['start']
            finish=cue.end if j==len(points)-1 else points[j][1]
            duration=finish-begin;count=char_count(cue.text[a:b])
            if duration<rules.min_ms or duration>rules.max_ms or not 0<count<=rules.jp_line*rules.max_lines:continue
            if count*1000/duration>max(rules.jp_cps,char_count(cue.text)*1000/(cue.end-cue.start))+.001:continue
            penalty=1+max(0,count*1000/duration-rules.jp_cps)*.25
            if j<len(points)-1 and cue.text[b-1] not in '。！？!?、，,；;':penalty+=.4
            proposal=(cost+penalty,path+[(a,b,begin,finish)])
            if best is None or proposal[0]<best[0]:best=proposal
        if best:states[j]=best
    if len(points)-1 not in states:return None
    parts=states[len(points)-1][1]
    if len(parts)<2 or ''.join(cue.text[a:b] for a,b,_,_ in parts)!=cue.text:return None
    return parts


def apply_alignment(base,document,offset,duration,rules,options):
    result=clone_track(base,'Pipeline • audio-aligned JP');records=[];candidates=[]
    if not isinstance(document,list) or len(document)!=len(base.segments):raise ValueError('Alignment cue count mismatch')
    max_shift=options.get('max_shift_ms',1500)
    for cue,entry in zip(base.segments,document):
        record={'cue_id':cue.id,'before':{'start':cue.start,'end':cue.end,'text':cue.text},'applied':False}
        try:
            if cue.status=='manual' or cue.review_status=='reviewed':raise ValueError('Protected manual/reviewed cue')
            if cue.end<=cue.start:raise ValueError('Invalid source cue duration')
            if not isinstance(entry,dict):raise ValueError('No usable alignment proposal')
            start,end,words=aligned_words(cue,entry,offset,offset+duration)
            if max(abs(start-cue.start),abs(end-cue.end))>max_shift:raise ValueError('Alignment exceeds maximum timing shift')
            speech_end=end
            max_rate=max(rules.jp_cps,char_count(cue.text)*1000/(cue.end-cue.start))
            minimum=min(rules.min_ms,cue.end-cue.start)
            required=max(minimum,math.ceil(char_count(cue.text)/max_rate*1000))
            # Subtitle display may linger briefly after the measured word end,
            # within its old exposure. Word timestamps themselves never change.
            end=max(end,min(start+required,cue.end,speech_end+600))
            if end-start<minimum or char_count(cue.text)*1000/(end-start)>max_rate+.001:
                raise ValueError('Alignment would worsen reading exposure')
            candidate=(start,end,words);record['proposal']={'start':start,'end':end,'words':words}
            record['proposal'].update(speech_end=speech_end,display_hold_ms=end-speech_end)
            record['reason']='Measured alignment candidate; not proof of audio accuracy'
        except (ValueError,KeyError,TypeError) as exc:
            candidate=None;record['reason']=str(exc)
        records.append(record);candidates.append(candidate)
    # Two states per cue choose a globally non-overlapping path. Retaining input
    # is always available, rather than clipping a neighbour or inventing a gap.
    states=[(0,-1,[])]
    for cue,candidate in zip(base.segments,candidates):
        following=[]
        choices=[(False,cue.start,cue.end)]+([(True,candidate[0],candidate[1])] if candidate else [])
        for selected,start,end in choices:
            compatible=[(cost+(0 if selected else 1),end,path+[selected]) for cost,previous,path in states if previous<=start]
            if compatible:following.append(min(compatible,key=lambda v:v[0]))
        states=following
        if not states:break
    selected=min(states,key=lambda v:v[0])[2] if states else [False]*len(base.segments)
    output=[]
    for source,target,candidate,record,take in zip(base.segments,result.segments,candidates,records,selected):
        if take:
            target.start,target.end=candidate[:2]
            parts=split_aligned(target,candidate[2],rules) if options.get('split',True) else None
            if parts:
                children=[]
                for a,b,start,end in parts:
                    child=deepcopy(target);child.id=uid();child.text=target.text[a:b];child.start=start;child.end=end
                    child.source='audio-aligned-split';child.translation_key='';child.review_status='unreviewed'
                    children.append(child)
            else:children=[target]
            if parts or (target.start,target.end)!=(source.start,source.end):
                record['applied']=True
                for child in children:
                    child.translation_key='';child.review_status='unreviewed'
                    if not parts:child.source='audio-forced-alignment'
            record['after']=[asdict(s) for s in children];output.extend(children)
        else:
            if candidate:record['reason']='Conflicting neighbour timing; original retained'
            if source.status!='manual' and source.review_status!='reviewed':target.notes.append('Alignment retained original timing: '+record['reason'])
            record['after']=[asdict(target)];output.append(target)
    result.segments=output
    return {'track':asdict(result),'records':records,'changes':[r for r in records if r['applied']],
            'retimed_cues':sum(r['applied'] for r in records),'split_cues':sum(len(r['after'])>1 for r in records),
            'scope':'Measured final-text alignment; invalid/protected cues retain source times; no transcript rewriting'}


def alignment_groups(base,start,end):
    groups=[];current=[]
    for index,cue in enumerate(base.segments):
        protected=cue.status=='manual' or cue.review_status=='reviewed' or not normalize(cue.text)
        if current and (protected or cue.end-base.segments[current[0]].start>25000):
            groups.append(current);current=[]
        if not protected and cue.end-cue.start<=25000:current.append(index)
    if current:groups.append(current)
    result=[]
    for indices in groups:
        first,last=indices[0],indices[-1]
        left=max(start,base.segments[first].start-400);right=min(end,base.segments[last].end+400)
        if first and (base.segments[first-1].status=='manual' or base.segments[first-1].review_status=='reviewed'):
            left=max(left,base.segments[first-1].end)
        if last+1<len(base.segments) and (base.segments[last+1].status=='manual' or base.segments[last+1].review_status=='reviewed'):
            right=min(right,base.segments[last+1].start)
        result.append({'indices':indices,'start':left,'end':right})
    return result


def align_final(runner,folder,base,audio):
    from .pipeline_worker import read_json,write_json
    options=runner.config['jp_alignment']
    source=digest([2,asdict(base),options,audio_digest(audio)])
    receipt=folder/'source.json'
    if receipt.exists() and read_json(receipt)['digest']!=source:raise ValueError('Changed final alignment source')
    write_json(receipt,{'digest':source,'audio_sha256':audio_digest(audio)})
    exe=runner.settings.crisp_exe
    validate_crisp_backend(runner.settings.crisp_gpu_backend,runner.call([exe,'--version'],folder,'version',20))
    help_text=runner.call([exe,'--help'],folder,'help',20)
    groups=alignment_groups(base,runner.config['start'],runner.config['start']+runner.config['duration'])
    assembled=[None]*len(base.segments);failures=[]
    for index,group in enumerate(groups):
        directory=folder/f'block-{index}';directory.mkdir(exist_ok=True)
        identity=digest([source,group]);path=directory/'result.json'
        if path.exists():
            cached=read_json(path)
            if cached['identity']!=identity or digest(cached['document'])!=cached['digest']:raise ValueError('Changed alignment block receipt')
            document=cached['document'];error=cached.get('error')
        else:
            wav=directory/'audio.wav';partial=directory/'audio.partial.wav'
            runner.call([runner.settings.ffmpeg,'-hide_banner','-nostdin','-y','-ss',str((group['start']-runner.config['start'])/1000),
                '-i',str(audio),'-t',str((group['end']-group['start'])/1000),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(partial)],directory,'crop',120)
            if not partial.exists() or partial.stat().st_size<=44:raise ValueError('Incomplete alignment audio crop')
            partial.replace(wav)
            transcript=directory/'input.json';write_json(transcript,[{'text':base.segments[i].text} for i in group['indices']])
            native=directory/'aligned.json'
            if native.exists():native.replace(directory/('uncommitted-'+uid()+'.json'))
            args=['--align-only','--aligner-model',runner.settings.crisp_aligner,'--file',str(wav),'--text-file',str(transcript),
                '--align-format','json','--align-granularity','segment','--align-output',str(native),
                '--gpu-backend',runner.settings.crisp_gpu_backend,'--cache-dir',str(folder/'native-cache')]
            validate_flags(help_text,args);document=None;error=None
            runner.event('phase',message=f'Final alignment • block {index+1}/{len(groups)} • {(group["end"]-group["start"])/1000:.1f} s')
            try:
                log=runner.call([exe,*args],directory,'engine',300)
                if any(t in log.lower() for t in ('out of memory','allocation failed','falling back')):raise RuntimeError('Final aligner device/memory failure')
                document=read_json(native)
            except RuntimeError as exc:
                engine_log=directory/'engine.log'
                detail=engine_log.read_text('utf8',errors='replace') if engine_log.exists() else str(exc)
                if any(t in detail.lower() for t in ('out of memory','allocation failed','falling back')):
                    raise RuntimeError('Final aligner device/memory failure; see '+str(engine_log)) from exc
                if 'alignment failed or produced no words' not in detail.lower():raise
                error=str(exc)
            except (ValueError,UnicodeError) as exc:error=str(exc)
            if not isinstance(document,list) or len(document)!=len(group['indices']):
                error=error or 'Alignment block cue count mismatch';document=None
            write_json(path,{'identity':identity,'document':document,'digest':digest(document),'error':error})
        if document is None:failures.append({'block':index,'reason':error})
        else:
            for cue_index,entry in zip(group['indices'],document):
                try:
                    item=deepcopy(entry);shift=group['start']-runner.config['start']
                    if not isinstance(item,dict):raise ValueError('Invalid alignment entry')
                    for row in [item,*item.get('words',[])]:
                        for key in ('start','end'):row[key]=(_milliseconds(row[key])+shift)/1000
                    assembled[cue_index]=item
                except (KeyError,TypeError,ValueError):pass
        runner.progress(index+1,len(groups))
    write_json(folder/'aligned.json',assembled)
    result=apply_alignment(base,assembled,runner.config['start'],runner.config['duration'],runner.rules,options)
    result.update(blocks=groups,block_failures=failures)
    return result

"""Recover gap phrases across ASR cue boundaries using separate text and timing evidence."""
from copy import deepcopy
from dataclasses import asdict
from difflib import SequenceMatcher
import math

from .audio_alignment import aligned_words
from .audio_boundaries import audio_digest, quiet_regions
from .core import Segment, normalize
from .pipeline import digest, file_identity
from .review import ReviewSettings, char_count
from .storage import check_space

POLICY='focused-coverage-v2-caption-endpoints-word-starts-interval-selection'


def character_map(text):
    return [i for i,char in enumerate(text) for _ in normalize(char)]


def fragment_confidence(attempt,cue,left,right):
    """Use token text coverage, not unreliable native timestamp interpolation."""
    for entry in attempt.get('document',{}).get('transcription',[]):
        if entry.get('text')!=cue['text']:continue
        tokens=entry.get('tokens',[])
        if normalize(''.join(t.get('text','') for t in tokens))!=normalize(cue['text']):break
        lo=len(normalize(cue['text'][:left]));hi=len(normalize(cue['text'][:right]));at=0;values=[]
        for token in tokens:
            length=len(normalize(token.get('text','')));count=max(0,min(at+length,hi)-max(at,lo));at+=length
            probability=token.get('p')
            if count:
                if type(probability) not in (int,float) or not math.isfinite(probability):return None
                values.extend([probability]*count)
        if len(values)==hi-lo and values:return sum(values)/len(values)
    return attempt.get('confidence',{}).get(cue['id'],{}).get('mean')


def fragment_candidates(base,attempt,window,start,end):
    """Keep entire gap lines and leading/trailing additions anchored by existing text.

    Bounds are search hints only. No overlapping cue is trimmed or exported;
    every nomination must pass focused decoding and standalone word alignment.
    """
    if not attempt.get('usable'):return []
    result=[]
    for cue in attempt.get('track',{}).get('segments',[]):
        text=normalize(cue['text']);positions=character_map(cue['text'])
        if len(text)<2:continue
        overlaps=[s for s in base.segments if cue['start']<s.end+200 and cue['end']>s.start-200]
        pieces=[]
        if not overlaps:pieces=[(0,len(cue['text']),cue['start'],cue['end'],'whole-gap')]
        else:
            first,last=overlaps[0],overlaps[-1]
            if cue['start']<first.start:
                blocks=SequenceMatcher(None,normalize(first.text),text,autojunk=False).get_matching_blocks()
                anchors=[b for b in blocks if b.a==0 and b.b>=2 and b.size>=4]
                if anchors:
                    anchor=max(anchors,key=lambda b:b.size)
                    pieces.append((0,positions[anchor.b],cue['start'],min(cue['end'],first.start-80),'anchored-prefix'))
            if cue['end']>last.end:
                existing=normalize(last.text)
                blocks=SequenceMatcher(None,existing,text,autojunk=False).get_matching_blocks()
                anchors=[b for b in blocks if b.a+b.size==len(existing) and b.size>=4 and b.b+b.size<len(text)-1]
                if anchors:
                    anchor=max(anchors,key=lambda b:b.size);at=anchor.b+anchor.size
                    pieces.append((positions[at],len(cue['text']),max(cue['start'],last.end+80),cue['end'],'anchored-suffix'))
        for lo,hi,a,b,kind in pieces:
            raw=cue['text'][lo:hi].strip()
            if not 2<=len(normalize(raw))<=80 or not start<=a<b<=end:continue
            if any(a<s.end and b>s.start for s in base.segments):continue
            result.append({'cue':{**deepcopy(cue),'start':a,'end':b,'text':raw},'window':window['id'],
                'confidence':fragment_confidence(attempt,cue,lo,hi),'source_cue':deepcopy(cue),
                'nomination':kind,'fragment_characters':[lo,hi],'source_directory':attempt.get('directory','')})
    return result


def combine_candidates(proposals):
    """Join duplicate overlap evidence without deleting genuine separate repetitions."""
    result=[]
    for proposal in sorted(proposals,key=lambda p:(p['cue']['start'],p['cue']['end'])):
        cue=proposal['cue']
        same=next((r for r in result if normalize(r['cue']['text'])==normalize(cue['text']) and
                   min(r['cue']['end'],cue['end'])>max(r['cue']['start'],cue['start'])),None)
        if same:
            same['sources'].append(deepcopy(proposal))
            same['cue']['start']=min(same['cue']['start'],cue['start']);same['cue']['end']=max(same['cue']['end'],cue['end'])
            values=[s['confidence'] for s in same['sources'] if type(s.get('confidence')) in (int,float) and math.isfinite(s['confidence'])]
            same['confidence']=max(values) if values else None
        else:result.append({**deepcopy(proposal),'sources':[deepcopy(proposal)]})
    for item in result:
        item['id']=digest([item['cue'],item['sources']])[:16];item['window']=item['id']
    return result


def text_contains(attempt,text):
    raw=attempt.get('text','');needle=normalize(text);surface=normalize(raw)
    if not attempt.get('usable') or not needle or surface.count(needle)!=1:return False
    at=surface.index(needle);positions=character_map(raw);lo=positions[at]
    if lo:
        previous=raw[lo-1];first=raw[lo]
        def script(char):
            if '\u3040'<=char<='\u309f':return 'hiragana'
            if '\u30a0'<=char<='\u30ff' or char=='ー':return 'katakana'
            if '\u3400'<=char<='\u9fff':return 'kanji'
            if char.isascii() and char.isalnum():return 'ascii'
        # Matching an ASR substring is insufficient when it begins in the
        # middle of a continuous word, e.g. ろうね inside だろうね.
        if normalize(previous) and script(previous)==script(first) is not None:return False
    return True


def alignment_input(text,phrase):
    """Retain all focused decode text as anchors; split only at verbatim phrase edges."""
    normalized=normalize(text);needle=normalize(phrase)
    if not needle or normalized.count(needle)!=1:raise ValueError('Missing or ambiguous focused phrase')
    positions=character_map(text);at=normalized.index(needle)
    lo=positions[at];hi=positions[at+len(needle)-1]+1
    items=[]
    if normalize(text[:lo]):items.append({'text':text[:lo]})
    index=len(items);items.append({'text':phrase})
    if normalize(text[hi:]):items.append({'text':text[hi:]})
    return items,index


def validate_insertion(base,phrase,entry,offset,end,rules):
    """Use measured word bounds inside a real gap; preserve every existing cue."""
    cue=Segment(offset,end,phrase)
    complete=True
    try:start,speech_end,words=aligned_words(cue,entry,offset,end)
    except ValueError as exc:
        if str(exc)!='Unattached zero-duration word':raise
        # Whole-caption insertion needs measured outer bounds, not a timestamp
        # for every internal particle. The strict parser has already checked
        # exact text coverage, finite/ordered bounds and <=35% zero tokens.
        # Retain internal zero times verbatim; never use this mode for splitting.
        raw=[w for w in entry['words'] if normalize(w['word'])]
        if not raw or any(w['start']>=w['end'] for w in (raw[0],raw[-1])):raise
        if abs(raw[0]['start']-entry['start'])>.02 or abs(raw[-1]['end']-entry['end'])>.02:raise
        start=offset+round(entry['start']*1000);speech_end=offset+round(entry['end']*1000)
        words=[{'text':w['word'],'start':offset+round(w['start']*1000),'end':offset+round(w['end']*1000)} for w in raw]
        complete=False
    if start<=offset+20 or speech_end>=end-20:raise ValueError('Alignment touches focused crop edge')
    if speech_end-start<120 or speech_end-start>15000:raise ValueError('Implausible missing-line exposure')
    if any(start<s.end+80 and speech_end>s.start-80 for s in base.segments):raise ValueError('Aligned phrase overlaps an existing cue')
    limit=min([end]+[s.start-80 for s in base.segments if s.start>=speech_end])
    required=max(rules.min_ms,math.ceil(char_count(phrase)/rules.jp_cps*1000))
    display_end=max(speech_end,min(start+required,speech_end+600,limit))
    return {'start':start,'end':display_end,'speech_end':speech_end,'words':words,'display_hold_ms':display_end-speech_end,
            'word_timing_complete':complete,'timing_basis':'aligned words' if complete else 'measured caption endpoints; internal token times incomplete'}


def search_focused(runner,folder,base,audio):
    from .asr_coverage import chunk_windows,recover_gaps
    from .pipeline_worker import read_json,write_json
    from .source_review_v3 import decode_batch
    options=runner.config['asr_coverage'];start=runner.config['start'];end=start+runner.config['duration']
    models=[dict(runner.config['asr'][0],vad=False),runner.config['retry_asr']['auxiliary']]
    third=runner.config['retry_asr'].get('third')
    if third:models.append(third)
    windows=chunk_windows(start,end,options.get('chunk_ms',30000),options.get('padding_ms',3000),quiet_regions(audio,start))
    source=digest([POLICY,asdict(base),audio_digest(audio),options,models,asdict(runner.settings),windows,
                   [file_identity(item['model']) for item in models],file_identity(runner.settings.crisp_aligner),
                   file_identity(runner.settings.crisp_exe)])
    identity_path=folder/'source.json'
    if identity_path.exists() and read_json(identity_path).get('source')!=source:raise ValueError('Changed focused coverage source')
    write_json(identity_path,{'source':source,'windows':windows,'version':2,'policy':POLICY})
    final_path=folder/'focused-result.json'
    # Validate individual receipts even when recovering an interrupted final stage.
    if final_path.exists():
        saved=read_json(final_path)
        if saved.get('source')!=source or saved.get('digest')!=digest(saved['result']):raise ValueError('Changed focused coverage result')
        for path,value in saved['receipts'].items():
            if digest(read_json(folder/path))!=value:raise ValueError('Changed focused coverage receipt')
        return saved['result']
    attempts={};focus_attempts={};peers={};peer_attempts={};fallbacks={};receipts={};failures=[];proposals=[]

    def collect(batch,item,label):
        values={};jobs=[]
        for w in batch:
            directory=folder/w['id']/label;directory.mkdir(parents=True,exist_ok=True)
            path=directory/'receipt.json';identity=digest([source,w,item,label]);receipts[str(path.relative_to(folder))]=None
            if path.exists():
                saved=read_json(path)
                if saved.get('identity')!=identity or saved.get('digest')!=digest(saved['result']):raise ValueError('Changed focused ASR receipt')
                values[w['id']]=saved['result'];continue
            wav=directory.parent/'window.wav'
            if not wav.exists():
                check_space(wav,(w['end']-w['start'])*32+1024**2,runner.settings.reserve_gib)
                partial=wav.with_suffix('.partial.wav')
                runner.call([runner.settings.ffmpeg,'-hide_banner','-nostdin','-y','-ss',str((w['start']-start)/1000),'-i',str(audio),
                    '-t',str((w['end']-w['start'])/1000),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(partial)],directory,'crop',120)
                if not partial.is_file() or partial.stat().st_size<=44:raise ValueError('Missing focused coverage crop')
                partial.replace(wav)
            jobs.append({**w,'folder':directory,'audio':wav,'receipt':path,'identity':identity})
        decoded=decode_batch(runner,folder/f'batch-{label}-{digest([j["identity"] for j in jobs])[:16]}',item,jobs,text_only=True)
        for job,value in zip(jobs,decoded):
            write_json(job['receipt'],{'identity':job['identity'],'result':value,'digest':digest(value)})
            values[job['id']]=value
        for key,value in values.items():
            if not value.get('usable'):failures.append({'window':key,'decoder':label,'error':value.get('error')})
        return values

    def clean(batch):
        for w in batch:
            wav=folder/w['id']/'window.wav'
            if wav.is_file():wav.unlink()

    for index in range(0,len(windows),8):
        batch=windows[index:index+8];runner.event('phase',message=f'Coverage scan • short chunks {index+1}–{index+len(batch)} / {len(windows)}')
        decoded=collect(batch,models[0],'scan');attempts.update(decoded)
        for w in batch:proposals.extend(fragment_candidates(base,decoded[w['id']],w,start,end))
        clean(batch);runner.progress(index+len(batch),len(windows))
    proposals=combine_candidates(proposals)
    jobs=[]
    for p in proposals:
        p['verification']={'version':2,'text_confirmed':False,'alignment_valid':False,'reason':'Insufficient original token confidence'}
        score=p.get('confidence')
        if type(score) not in (int,float) or not math.isfinite(score) or score<.8:continue
        left=max(start,p['cue']['start']-3000);right=min(end,p['cue']['end']+3000)
        if right-left>30000:
            p['verification']['reason']='Focused phrase exceeds the 30-second audio budget';continue
        jobs.append({'id':'focus-'+p['id'],'start':left,'end':right,'proposal':p['id']})
    lookup={p['id']:p for p in proposals};rules=ReviewSettings.load(runner.config['review_settings'])
    for index in range(0,len(jobs),8):
        batch=jobs[index:index+8];runner.event('phase',message=f'Coverage verification • focused phrases {index+1}–{index+len(batch)} / {len(jobs)}')
        primary=collect(batch,models[0],'focus-baseline');focus_attempts.update(primary)
        eligible=[w for w in batch if text_contains(primary[w['id']],lookup[w['proposal']]['cue']['text'])]
        second=collect(eligible,models[1],'focus-auxiliary');peer_attempts.update(second)
        missing=[w for w in eligible if not text_contains(second[w['id']],lookup[w['proposal']]['cue']['text'])]
        last=collect(missing,models[2],'focus-third') if len(models)>2 else {};fallbacks.update(last)
        for w in batch:
            p=lookup[w['proposal']];phrase=p['cue']['text'];first=primary[w['id']]
            peer=second.get(w['id'],{})
            if not text_contains(peer,phrase):peer=last.get(w['id'],peer)
            peers[p['window']]=peer
            verification=p['verification'];verification.update(focus=[w['start'],w['end']],
                baseline_directory=first.get('directory',''),peer_directory=peer.get('directory',''),
                baseline_model=models[0]['model'],peer_model=peer.get('model',''),
                baseline_text=first.get('text',''),peer_text=peer.get('text',''),reason='Focused audio decoders do not corroborate the phrase')
            if not text_contains(first,phrase) or not text_contains(peer,phrase):continue
            verification['text_confirmed']=True
            directory=folder/w['id']/'alignment';directory.mkdir(exist_ok=True)
            transcript,target=alignment_input(first['text'],phrase);path=directory/'receipt.json'
            identity=digest([source,w,transcript,target]);receipts[str(path.relative_to(folder))]=None
            if path.exists():
                saved=read_json(path)
                if saved.get('identity')!=identity or saved.get('digest')!=digest(saved['result']):raise ValueError('Changed coverage alignment receipt')
                aligned=saved['result']
            else:
                write_json(directory/'input.json',transcript)
                native=directory/'aligned.json'
                if native.exists():
                    from .core import uid
                    native.replace(directory/('uncommitted-'+uid()+'.json'))
                args=[runner.settings.crisp_exe,'--align-only','--aligner-model',runner.settings.crisp_aligner,
                    '--file',str(folder/w['id']/'window.wav'),'--text-file',str(directory/'input.json'),
                    '--align-format','json','--align-granularity','segment','--align-output',str(native),
                    '--gpu-backend',runner.settings.crisp_gpu_backend,'--cache-dir',str(folder/'native-cache')]
                aligned={'valid':False}
                try:
                    log=runner.call(args,directory,'engine',300)
                    if any(s in log.lower() for s in ('out of memory','allocation failed','falling back')):raise RuntimeError('Coverage aligner device/memory failure')
                    if not native.is_file():raise ValueError('Coverage aligner did not produce JSON')
                    document=read_json(native)
                    if not isinstance(document,list) or len(document)!=len(transcript):raise ValueError('Coverage alignment unit count mismatch')
                    bounds=validate_insertion(base,phrase,document[target],w['start'],w['end'],rules)
                    aligned.update(valid=True,bounds=bounds,document=document,target=target)
                except RuntimeError as exc:
                    log=(directory/'engine.log').read_text('utf8',errors='replace') if (directory/'engine.log').exists() else str(exc)
                    if any(s in log.lower() for s in ('out of memory','allocation failed','falling back')):raise
                    if 'alignment failed or produced no words' not in log.lower():raise
                    aligned['reason']=str(exc)
                except (ValueError,KeyError,TypeError,UnicodeError) as exc:aligned['reason']=str(exc)
                write_json(path,{'identity':identity,'result':aligned,'digest':digest(aligned)})
            verification.update(alignment=deepcopy(aligned),alignment_directory=str(directory),
                                alignment_valid=aligned['valid'],reason=aligned.get('reason','Separate text corroboration and measured gap alignment'))
            if aligned['valid']:
                p['unverified_cue']=deepcopy(p['cue']);p['cue'].update(start=aligned['bounds']['start'],end=aligned['bounds']['end'])
        clean(batch);runner.progress(index+len(batch),len(jobs))
    result=recover_gaps(base,proposals,peers,models[0]['model'],models[1]['model'])
    result.update(version=2,policy=POLICY,windows=windows,attempts=attempts,focus_attempts=focus_attempts,peers=peers,
                  peer_attempts=peer_attempts,fallbacks=fallbacks,failed_windows=failures,focus_windows=jobs)
    receipts={path:digest(read_json(folder/path)) for path in receipts}
    write_json(final_path,{'source':source,'result':result,'digest':digest(result),'receipts':receipts})
    return result

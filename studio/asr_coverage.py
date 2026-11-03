"""Short-context audio coverage search; never infer missing words with an LLM."""
from copy import deepcopy
from dataclasses import asdict
import math

from .audio_boundaries import audio_digest, quiet_regions
from .core import Segment, Track, normalize
from .pipeline import digest, file_identity
from .storage import check_space


def chunk_windows(start, end, chunk_ms=30000, padding_ms=3000, quiet=()):
    """Partition the complete interval, preferring nearby quiet core boundaries.

    Cores cover every millisecond. Decode windows include context on both sides;
    they are not subtitle boundaries, and no transcript is cut at a core edge.
    """
    result=[];left=start
    while left<end:
        right=min(end,left+chunk_ms)
        if right<end:
            choices=[(a+b)//2 for a,b in quiet
                     if left+chunk_ms//2 <= (a+b)//2 < end and abs((a+b)//2-right)<=2000]
            if choices:right=min(choices,key=lambda value:(abs(value-right),value))
        result.append({'id':f'{len(result):05d}','core_start':left,'core_end':right,
                       'start':max(start,left-padding_ms),'end':min(end,right+padding_ms)})
        left=right
    return result


def missing_candidates(base, attempt, window, start, end, margin=200):
    """Find whole decoded cues in gaps, including gaps before/after all subtitles."""
    if not attempt.get('usable'):return []
    candidates=[]
    for cue in attempt['track']['segments']:
        text=normalize(cue['text'])
        if len(text)<2 or not start<=cue['start']<cue['end']<=end:continue
        # Avoid nominations truncated at a physical crop edge. Overlapping
        # windows can supply the complete line; core boundaries never trim it.
        if window['start']>start and cue['start']<window['start']+margin:continue
        if window['end']<end and cue['end']>window['end']-margin:continue
        if any(cue['start']<s.end+margin and cue['end']>s.start-margin for s in base.segments):continue
        candidates.append({'cue':deepcopy(cue),'window':window['id'],
                           'confidence':attempt.get('confidence',{}).get(cue['id'],{}).get('mean')})
    return candidates


def _near(a,b):
    overlap=min(a['end'],b['end'])-max(a['start'],b['start'])
    return overlap>=.5*min(a['end']-a['start'],b['end']-b['start'])


def recover_gaps(base, proposals, peers, baseline_model, auxiliary_model):
    """Accept isolated verbatim lines corroborated by distinct audio decoders."""
    result=deepcopy(base);result.name='Pipeline • short-chunk coverage'
    # This is a new track; existing cue IDs, human work and exact bounds survive.
    result.id=Track('').id
    result.origin=deepcopy(base.origin);result.origin['coverage_parent']=base.id
    records=[]
    for proposal in proposals:
        cue=proposal['cue'];peer=peers.get(proposal['window'],{})
        matches=[s for s in peer.get('track',{}).get('segments',[])
                 if normalize(s['text'])==normalize(cue['text']) and _near(cue,s)
                 and abs(s['start']-cue['start'])<=750 and abs(s['end']-cue['end'])<=750]
        score=proposal['confidence']
        eligible=(peer.get('usable',False) and bool(matches)
                  and isinstance(score,(int,float)) and math.isfinite(score) and score>=.8
                  and str(baseline_model).replace('\\','/').casefold()!=str(auxiliary_model).replace('\\','/').casefold())
        records.append({**deepcopy(proposal),'peer_matches':deepcopy(matches),'applied':False,
                        'baseline_model':baseline_model,'corroborating_model':peer.get('model',auxiliary_model),
                        'peer_directory':peer.get('directory',''),
                        'eligible':eligible,'reason':'Unconfirmed missing-line hypothesis; listening required'})
    # Duplicate overlap nominations are one event. Conflicting wording/timing
    # never wins by iteration order or by an auxiliary majority.
    selected=[]
    for record in records:
        if not record['eligible']:continue
        cue=record['cue']
        conflicts=[r for r in records if r is not record and
                   cue['start']<r['cue']['end'] and cue['end']>r['cue']['start'] and
                   (normalize(cue['text'])!=normalize(r['cue']['text']) or not _near(cue,r['cue']))]
        if conflicts:
            record['reason']='Conflicting overlapping chunk hypotheses; listening required';continue
        if any(_near(cue,r['cue']) and normalize(cue['text'])==normalize(r['cue']['text']) for r in selected):
            record['reason']='Duplicate overlapping chunk hypothesis';continue
        added=Segment(cue['start'],cue['end'],cue['text'],source='asr-coverage-consensus',
                      parents=[cue['id']]+[s['id'] for s in record['peer_matches']],
                      notes=['Coverage: missing line corroborated by two audio models; listening required'])
        result.segments.append(added)
        record.update(applied=True,after=asdict(added),reason='Distinct audio models agree on an isolated missing line')
        selected.append(record)
    result.segments.sort(key=lambda cue:(cue.start,cue.end))
    return {'track':asdict(result),'candidates':records,'changes':[r for r in records if r['applied']],
            'unresolved':sum(not r['applied'] and not r['reason'].startswith('Duplicate') for r in records),
            'scope':'Audio-derived gap recovery; original cues/times retained. Agreement is not verified accuracy.'}


def search_coverage(runner, folder, base, audio):
    """Resumable bounded batches; no full-film duplicate WAVs or model downloads."""
    from .pipeline_worker import read_json, write_json
    from .source_review_v3 import decode_batch
    options=runner.config['asr_coverage'];start=runner.config['start'];end=start+runner.config['duration']
    baseline=dict(runner.config['asr'][0],vad=False)
    auxiliary=runner.config['retry_asr']['auxiliary']
    windows=chunk_windows(start,end,options.get('chunk_ms',30000),options.get('padding_ms',3000),quiet_regions(audio,start))
    third=runner.config['retry_asr'].get('third')
    source=digest([2,asdict(base),audio_digest(audio),options,baseline,auxiliary,third,windows,
                   asdict(runner.settings),file_identity(baseline['model']),file_identity(auxiliary['model']),
                   file_identity(third['model']) if third else None])
    checkpoint=folder/'source.json'
    if checkpoint.exists() and read_json(checkpoint).get('source')!=source:raise ValueError('Changed coverage source')
    write_json(checkpoint,{'source':source,'windows':windows})
    attempts={};peers={};peer_attempts={};fallbacks={};proposals=[]

    def collect(batch,item,label):
        values={};jobs=[]
        for w in batch:
            directory=folder/w['id']/label;directory.mkdir(parents=True,exist_ok=True)
            path=directory/'receipt.json';identity=digest([source,w,item])
            if path.exists():
                saved=read_json(path)
                if saved.get('identity')!=identity or saved.get('digest')!=digest(saved['result']):raise ValueError('Changed coverage receipt')
                values[w['id']]=saved['result'];continue
            wav=directory.parent/'window.wav'
            if not wav.exists():
                check_space(wav,(w['end']-w['start'])*32+1024**2,runner.settings.reserve_gib)
                partial=wav.with_suffix('.partial.wav')
                runner.call([runner.settings.ffmpeg,'-hide_banner','-nostdin','-y','-ss',str((w['start']-start)/1000),
                    '-i',str(audio),'-t',str((w['end']-w['start'])/1000),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(partial)],directory,'crop',120)
                if not partial.is_file() or partial.stat().st_size<=44:raise ValueError('Missing coverage crop')
                partial.replace(wav)
            jobs.append({**w,'folder':directory,'audio':wav,'receipt':path,'identity':identity})
        decoded=decode_batch(runner,folder/f'batch-{label}-{digest([j["identity"] for j in jobs])[:16]}',item,jobs)
        for job,value in zip(jobs,decoded):
            write_json(job['receipt'],{'identity':job['identity'],'result':value,'digest':digest(value)})
            values[job['id']]=value
        return values

    for index in range(0,len(windows),8):
        batch=windows[index:index+8]
        runner.event('phase',message=f'Short-chunk coverage • {index+1}–{index+len(batch)} / {len(windows)}')
        first=collect(batch,baseline,'baseline');attempts.update(first)
        targets=[]
        for w in batch:
            nominated=missing_candidates(base,first[w['id']],w,start,end)
            proposals.extend(nominated)
            if nominated:targets.append(w)
        second=collect(targets,auxiliary,'auxiliary');peer_attempts.update(second);peers.update(second)
        failed=[w for w in targets if not second[w['id']].get('usable')]
        if failed and third:
            last=collect(failed,third,'third');fallbacks.update(last)
            for key,value in last.items():
                if value.get('usable'):peers[key]=value
        # Only temporary crops are removed. Native hypotheses and receipts are
        # retained; at most eight short WAVs occupy disk at once.
        for w in batch:
            wav=folder/w['id']/'window.wav'
            if wav.is_file():wav.unlink()
        runner.progress(index+len(batch),len(windows))
    result=recover_gaps(base,proposals,peers,baseline['model'],auxiliary['model'])
    result.update(windows=windows,attempts=attempts,peers=peers,peer_attempts=peer_attempts,fallbacks=fallbacks,
                  failed_windows=[{'window':key,'decoder':label,'error':value.get('error')}
                      for label,items in [('baseline',attempts),('auxiliary',peer_attempts),('third',fallbacks)] for key,value in items.items() if not value.get('usable')])
    # Make replay deterministic even if an outer stage write was interrupted.
    final=folder/'coverage.json'
    if final.exists():
        saved=read_json(final)
        if saved.get('source')!=source or saved.get('digest')!=digest(saved['result']):raise ValueError('Changed coverage result')
        return saved['result']
    write_json(final,{'source':source,'result':result,'digest':digest(result)})
    return result

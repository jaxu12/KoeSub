"""Bounded short/wide context probes; repeated weights never become extra votes."""
from copy import deepcopy
from dataclasses import asdict

from .audio_boundaries import quiet_regions,context_window,audio_digest
from .asr_review import review_fragments
from .pipeline import clone_track,digest,track_from
from .source_review_v3 import decode_batch
from .core import uid


def candidate_cues(track,review,context=None):
    if len(track.segments)!=len(review['track']['segments']) or any(
        (a.start,a.end)!=(b['start'],b['end']) for a,b in zip(track.segments,review['track']['segments'])):
        raise ValueError('Adaptive review no longer matches source cue timing')
    unresolved={r['cue_id'] for r in review['fragments'] if not r['applied'] and
                len({a['normalized'] for a in r['alternatives'] if a['usable']})>1}
    raw_to_index={s['parents'][0]:i for i,s in enumerate(review['track']['segments'])}
    priorities={raw_to_index[k]:('asr_disagreement',0) for k in unresolved if k in raw_to_index}
    if context:
        review_to_index={s['id']:i for i,s in enumerate(review['track']['segments'])}
        for finding in context.get('flags',[]):
            index=review_to_index.get(finding['review_cue_id'])
            if index is not None and finding['status'] in ('suspicious','name'):
                priorities.setdefault(index,('context_suspicion',1))
    return [(index,signal) for index,(signal,priority) in sorted(priorities.items(),key=lambda p:(p[1][1],p[0]))
            if track.segments[index].status!='manual' and track.segments[index].review_status!='reviewed']


def adaptive_retry(runner,folder,base,review,audio,raw_confidence,context=None):
    from .pipeline_worker import read_json,write_json
    options=runner.config['adaptive_retry'];start=runner.config['start'];end=start+runner.config['duration']
    quiet=quiet_regions(audio,start)
    source=digest([asdict(base),review,context,options,audio_digest(audio)])
    receipt=folder/'source.json'
    if receipt.exists() and read_json(receipt)['digest']!=source:raise ValueError('Changed adaptive retry source')
    write_json(receipt,{'digest':source,'quiet_regions':quiet,'scope':'Acoustic energy boundary hints, not verified speech'})
    selected=candidate_cues(base,review,context);planned=[];deferred=[]
    for index,signal in selected:
        cue=base.segments[index]
        if len(planned)>=options.get('max_targets',4):deferred.append({'cue_id':cue.id,'reason':'Adaptive target budget'});continue
        variants=[]
        for name,padding in [('short',1000),('wide',6000)]:
            window=context_window(base,cue,padding,start,end,quiet)
            if window:variants.append(dict(window,variant=name))
        if len(variants)!=2 or (variants[0]['start'],variants[0]['end'])==(variants[1]['start'],variants[1]['end']):
            deferred.append({'cue_id':cue.id,'reason':'Two distinct protected-safe contexts unavailable'});continue
        left=min(v['start'] for v in variants);right=max(v['end'] for v in variants)
        before=[asdict(s) for s in base.segments if s.start<right and s.end>left]
        planned.append({'id':digest([cue.id,variants])[:16],'target_id':cue.id,'start':left,'end':right,
            'cue_ids':[s['id'] for s in before],'before':before,'suspects':[{'id':cue.id,'signals':[signal]}],
            'contexts':variants,'attempts':[]})
    items=[runner.config['asr'][0],runner.config['retry_asr']['auxiliary']]
    for profile_index,(model_index,context_name) in enumerate((m,c) for m in range(2) for c in ("short","wide")):
        item=dict(items[model_index],vad=True,vad_options={"speech_pad_ms":120 if context_name=="short" else 300,"min_silence_ms":100 if context_name=="short" else 250})
        jobs=[];ordered=[]
        for window in planned:
            for variant in window['contexts']:
                if variant['variant']!=context_name:continue
                directory=folder/window['id']/variant['variant']/str(model_index);directory.mkdir(parents=True,exist_ok=True)
                identity=digest([source,item,variant]);path=directory/'result.json'
                if path.exists():
                    saved=read_json(path)
                    if saved['identity']!=identity or digest(saved['result'])!=saved['digest']:raise ValueError('Changed adaptive ASR receipt')
                    window['attempts'].append(saved['result']);continue
                wav=directory/'audio.wav'
                crop_receipt=directory/'crop.json';crop_identity=digest([source,variant])
                if wav.exists() and crop_receipt.exists():
                    crop=read_json(crop_receipt)
                    if crop['identity']!=crop_identity or crop['sha256']!=audio_digest(wav):raise ValueError('Changed adaptive audio crop')
                elif wav.exists():wav.replace(directory/('uncommitted-audio-'+uid()+'.wav'))
                if not wav.is_file():
                    partial=directory/'audio.partial.wav'
                    runner.call([runner.settings.ffmpeg,'-hide_banner','-nostdin','-y','-ss',str((variant['start']-start)/1000),
                        '-i',str(audio),'-t',str((variant['end']-variant['start'])/1000),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(partial)],directory,'crop',120)
                    if not partial.exists() or partial.stat().st_size<=44:raise ValueError('Incomplete adaptive audio crop')
                    partial.replace(wav);write_json(crop_receipt,{'identity':crop_identity,'sha256':audio_digest(wav)})
                jobs.append({'audio':wav,'folder':directory,'start':variant['start'],'end':variant['end']})
                ordered.append((window,variant,path,identity))
        if jobs:
            runner.event('phase',message=f'Adaptive audio • {item["name"]} • {len(jobs)} short/wide clips')
            values=decode_batch(runner,folder/f'batch-{model_index}-{context_name}-{digest([j["start"] for j in jobs])[:12]}',item,jobs)
            for (window,variant,path,identity),value in zip(ordered,values):
                value.update(context_variant=variant['variant'],audio_range=[variant['start'],variant['end']])
                value['name']+=' • '+variant['variant']+' context'
                write_json(path,{'identity':identity,'result':value,'digest':digest(value)});window['attempts'].append(value)
        runner.progress(profile_index+1,4)
    # Stable order is essential after partial resume: baseline first, one short
    # and one wide attempt per distinct model. Four attempts are only two models.
    for window in planned:
        window['attempts'].sort(key=lambda a:(0 if a['model']==items[0]['model'] else 1,a['context_variant']!='short'))
    scores={cue.id:raw_confidence.get(review['track']['segments'][i]['parents'][0],{}) for i,cue in enumerate(base.segments)}
    result=review_fragments(base,planned,scores,items[0]['model'],version=2,context_consistency=True)
    result.update(windows=planned,deferred=deferred,source_review=deepcopy(review),
        context_consistency_required=True,
        decision_policy='adaptive-two-model-two-contexts-v1',
        scope='Four consistent audio hypotheses: short/wide contexts from two distinct model weights; no reference input')
    result['track']['name']='Pipeline • adaptive audio review'
    return result

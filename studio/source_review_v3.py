"""Bounded, model-grouped audio retries with a third decoder for unresolved windows."""
from dataclasses import asdict
from pathlib import Path
import time
import re

from .adapters import crisp_command, whisper_cpp_command, reazonspeech_command, validate_crisp_backend
from .asr_disagreement import disagreement_targets, reuse_scan
from .asr_retry import retry_windows, suspects
from .asr_review import review_fragments
from .pipeline import digest, track_from, clone_track
from .storage import Model
from .core import uid


def preserve_uncommitted_outputs(folder):
    """A cancelled native batch may leave raw files without a valid receipt.

    Archive those hypotheses before decoding again, so an input that fails to
    produce output cannot accidentally inherit an earlier attempt's SRT.
    """
    files=list(folder.glob('*.srt'))+[folder/name for name in ('transcript.json','engine.log','transport.json') if (folder/name).is_file()]
    if files:
        archive=folder/'previous-uncommitted'/uid();archive.mkdir(parents=True)
        for path in files:path.replace(archive/path.name)


def split_clip_logs(log,jobs):
    """Attribute warnings only when every ordered input has a duration marker.

    Unknown runtime log formats fail closed: the caller retains the complete
    log, so an ambiguous alignment warning rejects rather than clears a clip.
    """
    markers=list(re.finditer(r'^crispasr: audio: (\d+) samples \([\d.]+ s\) @ (\d+) Hz[^\n]*',log,re.M))
    if len(markers)!=len(jobs):return [log]*len(jobs)
    for marker,job in zip(markers,jobs):
        rate=int(marker[2])
        if rate<=0 or abs(int(marker[1])/rate*1000-(job['end']-job['start']))>100:
            return [log]*len(jobs)
    header=log[:markers[0].start()]
    return [header+log[m.start():markers[i+1].start() if i+1<len(markers) else len(log)]
            for i,m in enumerate(markers)]


def unresolved_windows(base, windows, confidence, model):
    review=review_fragments(base,windows,confidence,model,version=2)
    unresolved={r['window'] for r in review['fragments'] if not r['applied']
                and len({a['normalized'] for a in r['alternatives'] if a['usable']}) > 1}
    unresolved.update(w['id'] for w in windows if len([a for a in w['attempts'] if a.get('usable')]) < 2)
    protected={s.id for s in base.segments if s.status=='manual' or s.review_status=='reviewed'}
    return [w for w in windows if w['id'] in unresolved and not protected.intersection(w['cue_ids'])]


def decode_batch(runner, root, item, jobs):
    """One native process, sequential inputs, the same strict CLI output parser.

    Return a per-clip result; elapsed time is amortized, never presented as a
    separately measured clip latency. A device/OOM failure stops the pipeline.
    """
    from .pipeline_worker import AsrQualityError, write_json
    if not jobs: return []
    root.mkdir(parents=True,exist_ok=True)
    if item['engine'] not in (1,2,3): raise ValueError('Grouped retries require CrispASR')
    exe=runner.settings.crisp_exe
    validate_crisp_backend(runner.settings.crisp_gpu_backend,runner.call([exe,'--version'],root,'version',20))
    help_text=runner.call([exe,'--help'],root,'help',20)
    model=Model(item['name'],item['model'],item['kind'],Path(item['model']).stat().st_size)
    fn={1:crisp_command,2:whisper_cpp_command,3:reazonspeech_command}[item['engine']]
    first=jobs[0]
    args=fn(runner.settings,model,first['audio'],first['folder'],item['vad'],help_text)
    for flag in ('--file','--output-file'):
        at=args.index(flag);del args[at:at+2]
    for job in jobs:
        job['folder'].mkdir(parents=True,exist_ok=True)
        preserve_uncommitted_outputs(job['folder'])
        args+=['--file',str(job['audio'].resolve()),'--output-file',str((job['folder']/'transcript').resolve())]
    started=time.monotonic();failure=None
    try:
        log=runner.call([exe,*args],root,'engine',max(300,sum(j['end']-j['start'] for j in jobs)/1000*20))
    except RuntimeError as exc:
        detail=str(exc).lower()
        if 'word timestamps required' not in detail or any(s in detail for s in ('out of memory','allocation failed','falling back')): raise
        failure=str(exc);log=(root/'engine.log').read_text('utf8',errors='replace')
    elapsed=round(time.monotonic()-started,3)
    if any(s in log.lower() for s in ('out of memory','allocation failed','falling back')):
        raise ValueError('ASR reported a device or memory failure; pipeline stopped. See engine.log.')
    record={'mode':'grouped-cli','model':item['model'],'device':runner.settings.crisp_gpu_backend,
            'seconds':elapsed,'clips':len(jobs),'inputs':[str(j['audio']) for j in jobs],
            'failure':failure,'clip_seconds':'Amortized batch wall time, including model load; not individual latency'}
    write_json(root/'batch.json',record)
    values=[]
    for job,clip_log in zip(jobs,split_clip_logs(log,jobs)):
        (job['folder']/'engine.log').write_text(clip_log,encoding='utf8')
        write_json(job['folder']/'transport.json',{'mode':'grouped-cli','batch':str(root/'batch.json'),
            'engine_log':str(root/'engine.log'),'input':str(job['audio']),
            'range_start':job['start'],'range_end':job['end']})
        try:
            if not list(job['folder'].glob('*.srt')): raise AsrQualityError(failure or 'Batch did not produce this clip')
            value=runner.parse_asr(job['folder'],item,clip_log,job['start'],job['end']-job['start'])
            scores=list(value.get('confidence',{}).values())
            value.update(usable=True,mean_confidence=sum(s['mean'] for s in scores)/len(scores) if scores else None)
        except AsrQualityError as exc:
            value={'usable':False,'error':str(exc)}
        value.update(model=item['model'],name=item['name'],directory=str(job['folder']),
                     seconds=elapsed/len(jobs),timing_scope='amortized-batch',batch=str(root/'batch.json'))
        values.append(value)
    return values


def retry_grouped(runner, folder, base, audio, confidence, scan):
    from .pipeline_worker import read_json, write_json, AsrQualityError
    options=runner.config['retry_asr'];baseline=runner.config['asr'][0]
    primary={s['id'] for s in suspects(base,confidence)}
    targets=disagreement_targets(base,track_from(scan['track'])) if scan and scan.get('usable',True) else []
    windows,skipped=retry_windows(base,confidence,runner.config['start'],runner.config['start']+runner.config['duration'],
        options.get('padding_ms',3000),options.get('max_window_ms',30000),options.get('max_targets',12),targets)
    source=digest([asdict(base),scan,options])
    checkpoint=folder/'partial.json'
    if checkpoint.exists():
        state=read_json(checkpoint)
        if state.get('source')!=source: raise ValueError('Changed grouped retry source')
    else:
        state={'source':source,'windows':windows}
    # Reconstruct from immutable attempt receipts on every resume; the summary
    # checkpoint is never trusted as an independent source of hypotheses.
    for w in windows:
        w['attempts']=[]
        directory=folder/w['id'];directory.mkdir(exist_ok=True)
        wav=directory/'window.wav'
        if not wav.is_file():
            runner.call([runner.settings.ffmpeg,'-hide_banner','-nostdin','-y','-ss',str((w['start']-runner.config['start'])/1000),
                '-i',str(audio),'-t',str((w['end']-w['start'])/1000),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)],directory,'crop',120)
    models=[baseline]+([options['auxiliary']] if options.get('auxiliary') else [])

    def collect(item,index,selected):
        jobs=[]
        for w in selected:
            directory=folder/w['id']/f'attempt-{index}';directory.mkdir(exist_ok=True)
            path=directory/'result.json';identity=digest([source,w['start'],w['end'],item])
            if path.exists():
                saved=read_json(path)
                if saved.get('identity')!=identity or saved.get('digest')!=digest(saved['result']): raise ValueError('Changed grouped retry receipt')
                w['attempts'].append(saved['result']);continue
            value=reuse_scan(w,scan,item,runner.folder/'asr-scan') if index==1 and not primary.intersection(w['cue_ids']) else None
            job={'window':w,'folder':directory,'audio':folder/w['id']/'window.wav',
                 'start':w['start'],'end':w['end'],'identity':identity,'path':path}
            if value is None: jobs.append(job)
            else:
                write_json(path,{'identity':identity,'result':value,'digest':digest(value)});w['attempts'].append(value)
        if jobs:
            runner.event('phase',message=f'{item["name"]} • {len(jobs)} audio clips • grouped model load')
            if options.get('batch_retries',False):
                values=decode_batch(runner,folder/f'batch-{index}-{digest([j["identity"] for j in jobs])[:12]}',item,jobs)
            else:
                values=[]
                for j in jobs:
                    started=time.monotonic()
                    try:
                        value=runner.retry_decode(j['folder'],item,j['audio'],j['start'],j['end'])
                        scores=list(value.get('confidence',{}).values())
                        value.update(usable=True,mean_confidence=sum(s['mean'] for s in scores)/len(scores) if scores else None)
                    except AsrQualityError as exc: value={'usable':False,'error':str(exc)}
                    value.update(model=item['model'],name=item['name'],directory=str(j['folder']),seconds=time.monotonic()-started)
                    values.append(value)
            for j,value in zip(jobs,values):
                write_json(j['path'],{'identity':j['identity'],'result':value,'digest':digest(value)})
                j['window']['attempts'].append(value)
        write_json(checkpoint,{'source':source,'windows':windows})
        runner.progress(index+1,3 if options.get('third') else 2)
    for index,item in enumerate(models): collect(item,index,windows)
    pending=unresolved_windows(base,windows,confidence,baseline['model'])
    third=options.get('third')
    limit=options.get('third_max_targets',6)
    if third:
        collect(third,2,pending[:limit])
    # This intermediate track is deliberately unchanged. Phrase review performs
    # the bounded edits; no coarse whole-window timing replacement is allowed.
    return {'track':asdict(clone_track(base,'Pipeline • grouped audio evidence')),'windows':windows,
            'skipped':skipped,'changes':[],'disagreements':targets,'third_requested':len(pending),
            'third_processed':min(len(pending),limit) if third else 0,
            'third_deferred':[w['id'] for w in (pending[limit:] if third else pending)],
            'scope':'Audio-only grouped retries; third decoder only for unresolved windows; timestamps preserved'}

"""Full local-film CUDA trial with isolated Subtitle Edit reference comparison.

References are read for scoring only after production finishes. Private media,
transcripts and diagnostics stay in the output directory, outside the repository.
"""
import argparse
from bisect import bisect_right
from collections import Counter
from dataclasses import asdict
from difflib import SequenceMatcher
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import threading
import time

from studio.audio_boundaries import audio_digest
from studio.core import load_srt,Project,ProjectStore,now
from studio.evaluation_text import normalize_text
from studio.pipeline import create_run,digest,load_run,track_from
from studio.pipeline_worker import read_json,write_json,run_pipeline
from studio.storage import Settings,audio_metadata,check_space
from tools.gpu_telemetry import GpuTelemetry
from tools.verify_pipeline import audit_result
from tools.verify_long_whisper import LiveMonitor,memory_state,transcript_diagnostics


def exact_distance(left,right):
    """Exact unit-cost Levenshtein distance using arbitrary-width Myers vectors."""
    if len(left)>len(right):left,right=right,left
    size=len(left)
    if not size:return len(right)
    masks={}
    for i,c in enumerate(left):masks[c]=masks.get(c,0)|(1<<i)
    mask=(1<<size)-1;positive=mask;negative=0;last=1<<(size-1);distance=size
    for c in right:
        equal=masks.get(c,0);vertical=equal|negative
        horizontal=(((equal&positive)+positive)^positive)|equal
        add=negative|~(horizontal|positive);remove=positive&horizontal
        if add&last:distance+=1
        elif remove&last:distance-=1
        add=(add<<1)|1;remove<<=1
        positive=(remove|~(vertical|add))&mask;negative=(add&vertical)&mask
    return distance


def text_score(reference,hypothesis):
    a,b=normalize_text(reference),normalize_text(hypothesis)
    if not a:raise ValueError('Empty normalized comparison reference')
    edits=exact_distance(a,b)
    return {'edit_distance':edits,'reference_characters':len(a),'hypothesis_characters':len(b),'cer':edits/len(a),
        'algorithm':'Exact Levenshtein distance, Myers bit vectors; no edit-type counts are inferred from heuristic alignment'}


def matched_timing(reference,actual):
    refs={};counts=Counter(normalize_text(c.text) for c in actual.segments)
    for cue in reference.segments:refs.setdefault(normalize_text(cue.text),[]).append(cue)
    pairs=[]
    for cue in actual.segments:
        key=normalize_text(cue.text)
        if len(key)<6 or len(refs.get(key,[]))!=1 or counts[key]!=1:continue
        target=refs[key][0]
        pairs.append({'reference_start':target.start,'actual_start':cue.start,'reference_end':target.end,'actual_end':cue.end,
            'start_delta_ms':cue.start-target.start,'end_delta_ms':cue.end-target.end})
    result={'matched_cues':len(pairs),'reference_cues':len(reference.segments),'actual_cues':len(actual.segments),'pairs':pairs,
        'scope':'Unique exact complete-caption text matches; Subtitle Edit display times, not acoustic gold; unmatched cues excluded explicitly'}
    if pairs:
        for edge in ('start','end'):
            values=[abs(p[edge+'_delta_ms']) for p in pairs]
            result[edge]={'mean_absolute_ms':round(statistics.mean(values),2),'median_absolute_ms':statistics.median(values),
                'max_absolute_ms':max(values),'mean_signed_ms':round(statistics.mean(p[edge+'_delta_ms'] for p in pairs),2)}
    return result


def window_comparisons(reference,actual,duration,window_ms=600000):
    """Diagnostic time bins; caption midpoint assignment can amplify boundary differences."""
    if duration<=0 or window_ms<=0:raise ValueError('Positive film and window durations required')
    rows=[]
    for start in range(0,duration,window_ms):
        end=min(duration,start+window_ms);texts=[];counts=[]
        for track in (reference,actual):
            cues=[c for c in track.segments if start<=(c.start+c.end)/2<end]
            counts.append(len(cues));texts.append(normalize_text(''.join(c.text for c in cues)))
        a,b=texts;edits=exact_distance(a,b)
        rows.append({'start_ms':start,'end_ms':end,'reference_cues':counts[0],'actual_cues':counts[1],
            'reference_characters':len(a),'actual_characters':len(b),'edit_distance':edits,'cer':edits/len(a) if a else None})
    return {'scope':'Diagnostic bins assigned by whole-caption midpoint; boundary/segmentation shifts can increase distance. '
        'Not acoustic alignment or verified error labels; CER is undefined for an empty reference bin.',
        'excluded_reference_cues':len(reference.segments)-sum(r['reference_cues'] for r in rows),
        'excluded_actual_cues':len(actual.segments)-sum(r['actual_cues'] for r in rows),'windows':rows}


def comparison_examples(reference,actual,limit=20):
    """Listening locations from heuristic alignment; not exact edit operations."""
    if limit<1 or not reference.segments:return []
    ref='';positions=[]
    for cue in reference.segments:positions.append(len(ref));ref+=normalize_text(cue.text)
    hyp=''.join(normalize_text(c.text) for c in actual.segments);rows=[];last=-60000
    for tag,a,b,c,d in SequenceMatcher(None,ref,hyp,autojunk=False).get_opcodes():
        if tag=='equal':continue
        index=min(len(reference.segments)-1,max(0,bisect_right(positions,a)-1));cue=reference.segments[index]
        if cue.start-last<30000:continue
        rows.append({'reference_time_ms':cue.start,'alignment_kind':tag,'reference_excerpt':ref[max(0,a-12):min(len(ref),b+12)],
            'actual_excerpt':hyp[max(0,c-12):min(len(hyp),d+12)],'scope':'Heuristic text alignment for listening, not verified error classification'})
        last=cue.start
    if len(rows)<=limit:return rows
    indices=[round(i*(len(rows)-1)/(limit-1)) for i in range(limit)] if limit>1 else [0]
    return [rows[i] for i in indices]


def render_comparison_report(summary,comparison):
    """Human-readable comparison; generated reference agreement is not accuracy."""
    lines=['# KoeSub full-film comparison','',
        'The existing Subtitle Edit subtitles are an unverified ASR reference. '
        'Character distance measures disagreement, not independently measured transcription accuracy. '
        'Neither system is assumed correct. Reference labels were excluded from inference.','',
        f"Film duration: **{summary['media_seconds']/60:.2f} minutes**. "
        f"Fresh pipeline wall time: **{summary['wall_seconds']:.3f} seconds**. "
        f"Pipeline status: **{summary['status']}**.",'']
    if summary.get('scope'):lines.extend([summary['scope'],''])
    if summary.get('error'):
        lines.extend([f"Pipeline error: **{summary['error']['type']}** — {summary['error']['message']}",
            'Final export did not complete. The table scores retained completed ASR artifacts.',''])
    if summary.get('asr_failures'):
        lines.extend(['Rejected auxiliary ASR (pipeline continued):',''])
        lines.extend(f"- {item['name']}: {item['reason']}" for item in summary['asr_failures'])
        lines.append('')
    lines.extend(['| Track | Captions | Character edits / reference characters | Normalized CER | Invalid times | Overlaps | Fast reading |',
        '|---|---:|---:|---:|---:|---:|---:|'])
    ref=comparison['reference_technical']
    lines.append(f"| Subtitle Edit reference | {ref['cues']} | — | — | {len(ref['invalid_time_indices'])} | {len(ref['overlap_indices'])} | {ref['fast_reading']} |")
    for name,value in comparison['variants'].items():
        score=value['score'];technical=value['technical']
        lines.append(f"| {name} | {technical['cues']} | {score['edit_distance']} / {score['reference_characters']} | "
            f"{score['cer']:.2%} | {len(technical['invalid_time_indices'])} | {len(technical['overlap_indices'])} | {technical['fast_reading']} |")
    lines+=['','CER uses exact normalized character Levenshtein distance over the complete transcript. '
        'Punctuation, spacing and selected non-speech labels are normalized. '
        'Reading-speed warnings are diagnostics, not confirmed recognition errors.','',
        '| Stage | Seconds | Status |','|---|---:|---|']
    for stage in summary['stages']:lines.append(f"| {stage['id']} | {stage.get('seconds',0):.2f} | {stage['status']} |")
    lines+=['',f"Whole-GPU peak memory: **{summary['gpu_peak_mib']} MiB**, including desktop/other processes. "
        f"Owned engine PID observed by NVIDIA telemetry: **{summary['engine_pid_observed_on_nvidia']}**. "
        f"Peak baseline-engine RAM: **{summary['engine_peak_ram_mib']} MiB**; minimum available system RAM: **{summary['minimum_available_ram_mib']} MiB**.",'',
        f"Exact export audit: **{summary.get('exact_export_audit','not completed')}**. "
        f"Whole-pipeline replay unchanged: **{summary.get('resume_unchanged','not completed')}**. "
        f"Completed ASR checkpoints reused without work: **{summary.get('completed_asr_checkpoint_replay','not checked')}**. "
        f"Original media/reference unchanged: **{summary.get('source_files_unchanged','not checked')}**.",'',
        '## Timing comparison','',
        'Only unique, identical complete captions of at least six normalized characters are matched. '
        'Unmatched captions are excluded; these are differences from Subtitle Edit display times, not acoustic timing accuracy.','']
    for name,value in comparison['variants'].items():
        timing=value['timing']
        lines.append(f"- **{name}**: {timing['matched_cues']} matched captions / {timing['reference_cues']} reference / {timing['actual_cues']} actual.")
        if timing['matched_cues']:
            for edge in ('start','end'):
                item=timing[edge]
                lines.append(f"  - {edge.title()}: median absolute difference {item['median_absolute_ms']} ms; mean {item['mean_absolute_ms']} ms; maximum {item['max_absolute_ms']} ms.")
    lines+=['','Private listening locations in `comparison.json` use heuristic text alignment. '
        'They are suggestions for checking the audio, not verified error labels or exact edit-operation counts.','']
    if comparison.get('window_comparison'):
        windows=comparison['window_comparison']
        lines+=['## Temporal diagnostics','',windows['scope'],'',
            f"Excluded midpoint-outside-film captions: reference {windows['excluded_reference_cues']}, actual {windows['excluded_actual_cues']}.",'',
            '| Minutes | Reference characters | Actual characters | Character distance | CER |','|---|---:|---:|---:|---:|']
        for row in windows['windows']:
            cer=f"{row['cer']:.2%}" if row['cer'] is not None else 'undefined'
            lines.append(f"| {row['start_ms']/60000:.1f}–{row['end_ms']/60000:.1f} | {row['reference_characters']} | "
                f"{row['actual_characters']} | {row['edit_distance']} | {cer} |")
        lines.append('')
    return '\n'.join(lines)


class ResourceGuard:
    """Abort only this engine under sustained critical system-memory pressure."""
    def __init__(self,manifest,root):
        self.manifest=manifest;self.root=root;self.stop=threading.Event();self.abort=None
        self.thread=threading.Thread(target=self.run,daemon=True)
    def run(self):
        critical_since=None
        while not self.stop.wait(5):
            try:
                receipt=self.manifest.parent/'asr-0/engine-process.json'
                state=read_json(self.manifest)
                if not receipt.exists() or not any(s['id']=='asr-0' and s['status']=='running' for s in state['stages']):continue
                pid=read_json(receipt)['pid'];memory=memory_state(pid)
                critical=memory.get('available_ram_mib',99999)<192 and memory.get('engine_ram_mib',0)>4096
                critical_since=critical_since or time.monotonic() if critical else None
                reason=None
                if critical_since and time.monotonic()-critical_since>=20:reason='Sustained critical physical RAM availability below 192 MiB'
                if shutil.disk_usage(self.root).free<3*1024**3:reason='Output volume free space below 3 GiB'
                if reason:
                    self.abort={'pid':pid,'reason':reason,'memory':memory,'unix_time':time.time()}
                    write_json(self.root/'resource-abort.json',self.abort);os.kill(pid,9);return
            except (OSError,ValueError):continue
    def close(self):self.stop.set();self.thread.join(timeout=7)


def save_project(root,state,reference):
    config=state['config'];project=Project(name='KoeSub - full local film comparison',media=config['media'],duration=config['media_duration'])
    reference.name='Subtitle Edit reference - unverified ASR';project.add_track(reference);stages={}
    for stage in state['stages']:
        if stage['status']!='completed':continue
        value=read_json(stage['artifact'])
        if 'track' in value:
            track=track_from(value['track']);project.add_track(track);stages[stage['id']]=track.id
    if state.get('final_track'):project.active_track=state['final_track']
    retry=config.get('retry_asr',{})
    project.pipeline_prefs={'transcription_only':True,'asr':config['asr'],'asr_count':1,
        'retry_clips':retry.get('enabled',False),'jp_context_review':config.get('jp_context_review',False),
        'asr_coverage':config.get('asr_coverage',{}).get('enabled',False),
        'coverage_seconds':config.get('asr_coverage',{}).get('chunk_ms',30000)//1000,
        'adaptive_audio':config.get('adaptive_retry',{}).get('enabled',False),
        'align_audio':config.get('jp_alignment',{}).get('enabled',False),'start':0,'length':0,
        'scan_first':retry.get('scan_first',False),'batch_retries':retry.get('batch_retries',False),
        'retry_limit':retry.get('max_targets',12),'third_limit':retry.get('third_max_targets',6),
        'retry_aux_model':(retry.get('auxiliary') or {}).get('model'),
        'retry_third_model':(retry.get('third') or {}).get('model'),
        'judge_model':config.get('judge_model',''),'backend':config.get('backend','embedded')}
    project.jobs=[{'type':'pipeline','id':state['id'],'created':now(),'manifest':str(root/'run/manifest.json'),
        'status':state['status'],'stage_tracks':stages,'track_hashes':{}}]
    pointer=root/'ui/last_project.json'
    if not pointer.exists():
        path=root/'ui/projects'/project.active.id/'project.sqlite';ProjectStore(path).save(project,'full local film comparison')
        write_json(pointer,{'path':str(path)})


def compare_results(root):
    protocol=read_json(root/'protocol.json');state=load_run(root/'run/manifest.json')
    if audio_digest(protocol['reference'])!=protocol['reference_sha256']:raise ValueError('Changed comparison reference')
    reference=load_srt(Path(protocol['reference']));tracks={}
    for stage in state['stages']:
        if stage['status']=='completed':
            value=read_json(stage['artifact'])
            if digest(value)!=stage['digest']:raise ValueError('Changed completed result')
            if 'track' in value:tracks[stage['id']]=track_from(value['track'])
    results={}
    text=''.join(c.text for c in reference.segments)
    for key,track in tracks.items():
        results[key]={'score':text_score(text,''.join(c.text for c in track.segments)),
            'technical':transcript_diagnostics(track,state['config']['duration']),'timing':matched_timing(reference,track)}
    selected='jp-layout' if 'jp-layout' in tracks else 'asr-0'
    actual=tracks.get(selected);summary={'variants':results,'production_status':state['status'],'comparison_stage':selected,
        'reference_technical':transcript_diagnostics(reference,state['config']['duration']),
        'reference_origin':'User states these subtitles were generated in Subtitle Edit; not independently verified against audio',
        'limitation':'Reference agreement and timing differences, not independent transcription or translation accuracy'}
    if actual:
        summary['listening_examples']=comparison_examples(reference,actual)
        summary['window_comparison']=window_comparisons(reference,actual,state['config']['duration'])
    write_json(root/'comparison.json',summary);save_project(root,state,reference)
    return summary


def film_config(media,duration,settings,root,full_jp=False):
    """Select the existing frozen full-JP policy or native Subtitle Edit preset."""
    if full_jp:
        from tools.benchmark_current_pipeline import production_config
        if settings.crisp_gpu_backend!='cuda' or settings.llm_device!='cuda':
            raise ValueError('Full Japanese film trial requires CUDA for ASR and the local review model')
        sample={'id':'full-local-film','audio':str(media.resolve()),'audio_sha256':audio_digest(media),'source_range_ms':[0,duration]}
        config=production_config(sample,settings,root/'exports')
        config.pop('benchmark_audio_sha256',None)  # The source is a movie; its hash is frozen in protocol.json.
        config.update(asr_timing_review={'enabled':True,'max_targets':8,'display_fallback':True},
            asr_coverage={'enabled':True,'version':2,'chunk_ms':30000,'padding_ms':3000},
            decision_batch_size=4,film_context=False,xxl_device='cuda',xxl_compute='float16')
        return config
    model=settings.use_subtitle_edit_whisper()
    return {'media':str(media.resolve()),'media_duration':duration,'start':0,'duration':duration,'audio_track':0,
        'asr':[{'engine':0,'name':model.name,'model':str(model),'kind':'Whisper / CTranslate2','vad':True}],
        'translations':[],'transcription_only':True,'source_review_version':None,'retry_asr':{'enabled':False},'adaptive_retry':{'enabled':False},
        'asr_timing_review':{'enabled':True,'max_targets':8},'jp_alignment':{'enabled':False},'backend':'embedded','judge_model':'',
        'review':'rules','review_settings':{},'settings':asdict(settings),'xxl_device':'cuda','xxl_compute':'float16',
        'readability_repair':True,'export_srt':True,'export_format':'srt','output_dir':str(root/'exports')}


def verify(media,reference,root,full_jp=False):
    root.mkdir(parents=True,exist_ok=True);settings=Settings.load();settings.cache_dir=str(root/'cache')
    probe=subprocess.run([settings.ffmpeg,'-hide_banner','-i',str(media)],capture_output=True,encoding='utf8',errors='replace',timeout=60)
    duration,streams=audio_metadata(probe.stderr)
    if duration<=1800000:raise ValueError('This test requires a film longer than thirty minutes')
    check_space(root,duration*177+2*1024**3,settings.reserve_gib)
    config=film_config(media,duration,settings,root,full_jp)
    policy={'production':{str(p):audio_digest(p) for p in sorted(Path('studio').glob('*.py'))},'media':str(media.resolve()),
        'media_sha256':audio_digest(media),'reference':str(reference.resolve()),'reference_sha256':audio_digest(reference),
        'duration_ms':duration,'audio_streams':streams,'reference_used_for_inference':False,
        'mode':'full-jp' if full_jp else 'native-xxl'}
    receipt=root/'protocol.json'
    if receipt.exists() and read_json(receipt)!=policy:raise ValueError('Changed frozen film-comparison inputs or policy')
    write_json(receipt,policy);manifest=root/'run/manifest.json'
    if manifest.exists():raise ValueError('Use a new output directory to preserve the existing measured experiment')
    create_run(config,manifest.parent)
    pointer=Path('data/last_project.json');before=pointer.read_bytes() if pointer.exists() else None
    telemetry=GpuTelemetry(manifest,root/'gpu.json',capture_processes=True);live=LiveMonitor(manifest,root/'live.json');guard=ResourceGuard(manifest,root)
    started=time.monotonic();telemetry.start();live.thread.start();guard.thread.start();error=None
    try:run_pipeline(manifest,lambda kind,**data:print(data['message'],flush=True) if kind=='phase' else None)
    except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
    finally:guard.close();live.close();gpu=telemetry.close()
    state=read_json(manifest);engine=manifest.parent/'asr-0/engine-process.json';pid=read_json(engine)['pid'] if engine.exists() else None
    summary={'status':state['status'],'error':error,'wall_seconds':round(time.monotonic()-started,3),'media_seconds':duration/1000,
        'stages':state['stages'],'gpu_peak_mib':max((s['memory_used_mib'] for s in gpu['samples']),default=None),'gpu_errors':gpu['errors'],
        'engine_pid_observed_on_nvidia':any(p['pid']==pid for p in gpu.get('compute_processes',[])),
        'engine_peak_ram_mib':max((s.get('engine_peak_ram_mib',0) for s in live.samples),default=None),
        'minimum_available_ram_mib':min((s['available_ram_mib'] for s in live.samples if 'available_ram_mib' in s),default=None),
        'resource_abort':guard.abort,'main_project_unchanged':(pointer.read_bytes() if pointer.exists() else None)==before,
        'asr_failures':state.get('asr_failures',[]),
        'scope':'Fresh full-film native pipeline; comparison labels used after completion; not independently audited audio accuracy'}
    write_json(root/'run-summary.json',summary)
    if full_jp:
        from tools.benchmark_current_pipeline import gpu_evidence
        summary['gpu_stage_evidence']=gpu_evidence(manifest.parent,gpu)
        summary['scope']='Fresh full-film Japanese production pipeline: auxiliary scan, retries, source/context review, adaptive audio and alignment; no translation or independently audited accuracy'
        write_json(root/'run-summary.json',summary)
    if error:
        summary['source_files_unchanged']=audio_digest(media)==policy['media_sha256'] and audio_digest(reference)==policy['reference_sha256']
        write_json(root/'run-summary.json',summary)
        result=compare_results(root)
        (root/'comparison.md').write_text(render_comparison_report(summary,result),encoding='utf8')
        raise RuntimeError('Full-film experiment failed; original evidence and completed-ASR comparison retained: '+str(root/'run-summary.json'))
    try:audit_result(manifest);summary['exact_export_audit']=True
    except AssertionError as exc:summary.update(exact_export_audit=False,export_audit_error=str(exc))
    write_json(root/'run-summary.json',summary)
    result=compare_results(root)
    snapshot=[(s['id'],s['digest'],s['seconds']) for s in state['stages']]
    processes={str(p):audio_digest(p) for p in manifest.parent.rglob('engine-process.json')}
    run_pipeline(manifest,lambda *a,**k:None);resumed=read_json(manifest)
    summary['resume_unchanged']=snapshot==[(s['id'],s['digest'],s['seconds']) for s in resumed['stages']] and processes=={str(p):audio_digest(p) for p in manifest.parent.rglob('engine-process.json')}
    summary['source_files_unchanged']=audio_digest(media)==policy['media_sha256'] and audio_digest(reference)==policy['reference_sha256']
    write_json(root/'run-summary.json',summary)
    (root/'comparison.md').write_text(render_comparison_report(summary,result),encoding='utf8')
    print('FULL FILM COMPLETE',summary['wall_seconds'],'seconds',flush=True)
    print('REFERENCE AGREEMENT',result['variants']['jp-layout']['score'],flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--media',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--full-jp',action='store_true',help='Full Japanese pipeline with auxiliary scan, third ASR, context review, adaptive audio and alignment; no translation')
    args=parser.parse_args();verify(args.media,args.reference,args.output,args.full_jp)


if __name__=='__main__':main()

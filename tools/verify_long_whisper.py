"""Run a bounded long native Whisper/MDX test with live resource diagnostics.

Use only existing local assets. Private audio, hypotheses and native logs stay
in the output cache. Timing validity and repeat flags are not accuracy labels.
"""
import argparse
from collections import Counter
import ctypes
from dataclasses import asdict
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
import wave

from studio.audio_boundaries import audio_digest
from studio.core import load_srt, Project, ProjectStore, now
from studio.evaluation_text import normalize_text
from studio.pipeline import create_run, digest, load_run, track_from
from studio.pipeline_worker import read_json, write_json, run_pipeline
from studio.review import metrics, ReviewSettings
from studio.storage import Settings, check_space
from tools.gpu_telemetry import GpuTelemetry
from tools.verify_pipeline import audit_result


def memory_state(pid=None):
    """Windows system availability and owned engine peak working set, in MiB."""
    if os.name != 'nt': return {}
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in
            ('total_physical','available_physical','total_page','available_page','total_virtual','available_virtual','extended')]
    value=Memory();value.length=ctypes.sizeof(value)
    result={}
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    if kernel.GlobalMemoryStatusEx(ctypes.byref(value)):
        result={'available_ram_mib':round(value.available_physical/1024**2),'total_ram_mib':round(value.total_physical/1024**2)}
    if pid:
        class Counters(ctypes.Structure):
            _fields_=[('size',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in
                ('peak_working_set','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x0410,False,pid)
        if handle:
            try:
                counters=Counters();counters.size=ctypes.sizeof(counters)
                api=ctypes.WinDLL('psapi').GetProcessMemoryInfo
                api.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
                if api(handle,ctypes.byref(counters),counters.size):
                    result.update(engine_ram_mib=round(counters.working_set/1024**2),engine_peak_ram_mib=round(counters.peak_working_set/1024**2))
            finally:kernel.CloseHandle(handle)
    return result


def transcript_diagnostics(track,duration):
    cues=track.segments;rules=ReviewSettings()
    invalid=[i for i,c in enumerate(cues) if not 0<=c.start<c.end<=duration]
    overlaps=[i for i,(a,b) in enumerate(zip(cues,cues[1:])) if a.end>b.start]
    counts=Counter(normalize_text(c.text) for c in cues if normalize_text(c.text))
    runs=[];at=0
    while at<len(cues):
        key=normalize_text(cues[at].text);end=at+1
        while end<len(cues) and normalize_text(cues[end].text)==key:end+=1
        if len(key)>=3 and end-at>=4:runs.append({'first_cue':at,'count':end-at,'start':cues[at].start,'end':cues[end-1].end})
        at=end
    gaps=[{'start':a.end,'end':b.start,'duration_ms':b.start-a.end} for a,b in zip(cues,cues[1:]) if b.start-a.end>=20000]
    return {'cues':len(cues),'invalid_time_indices':invalid,'zero_duration_cues':sum(c.end==c.start for c in cues),
        'overlap_indices':overlaps,'first_cue_ms':cues[0].start if cues else None,'last_cue_ms':cues[-1].end if cues else None,
        'fast_reading':sum(metrics(c.text,c.end-c.start)['cps']>rules.jp_cps for c in cues if c.end>c.start),
        'overlong':sum(c.end-c.start>rules.max_ms for c in cues),'consecutive_repeat_runs':runs,
        'frequent_exact_cues':sum(count>=10 for count in counts.values()),'long_gaps':gaps,
        'scope':'Technical/heuristic diagnostics; repeats and gaps may be natural; no reference or semantic error score'}


def progress_tail(path):
    if not path.exists():return []
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-24000));text=stream.read().decode('utf8',errors='replace')
    # Progress summaries only: never echo private transcript lines to the chat.
    lines=[line.strip() for line in re.split(r'[\r\n]+',text) if '-->' not in line and re.search(
        r'^\s*(?:MDX |Standalone |Operation finished|Starting |Transcrib|ERROR:|WARNING:)|\d+%\s*[|]',line)]
    return lines[-2:]


def native_confidence_diagnostics(document):
    """Native r245.4 threshold diagnostics, never an audio truth verdict."""
    segments=document.get('segments',[]) if isinstance(document,dict) else []
    if not isinstance(segments,list):raise ValueError('Native segments must be a list')
    result={'segments':len(segments),'field_coverage':{k:0 for k in ('avg_logprob','compression_ratio','no_speech_prob')},
        'low_logprob':[],'high_compression':[],'high_no_speech':[],'silence_candidates':[],
        'scope':'Model self-assessment at native default thresholds; split cues may share decoder metadata; not independently verified error labels'}
    for i,segment in enumerate(segments):
        values={k:v for k,v in segment.items() if k in result['field_coverage'] and type(v) in (float,int) and math.isfinite(v)}
        for key in values:result['field_coverage'][key]+=1
        low='avg_logprob' in values and values['avg_logprob'] < -1.0
        quiet='no_speech_prob' in values and values['no_speech_prob'] > .6
        if low:result['low_logprob'].append(i)
        if quiet:result['high_no_speech'].append(i)
        if values.get('compression_ratio',0)>2.4:result['high_compression'].append(i)
        if low and quiet:result['silence_candidates'].append(i)
    return result


class LiveMonitor:
    def __init__(self,manifest,output):
        self.manifest=manifest;self.output=output;self.stop=threading.Event();self.samples=[];self.errors=[]
        self.thread=threading.Thread(target=self.run,daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                state=read_json(self.manifest);process=self.manifest.parent/'asr-0/engine-process.json'
                pid=read_json(process)['pid'] if process.exists() else None
                sample={'unix_time':time.time(),'stage':next((s['id'] for s in state['stages'] if s['status']=='running'),state['status']),
                    'engine_pid':pid,**memory_state(pid),'progress':progress_tail(self.manifest.parent/'asr-0/engine.log')}
                self.samples.append(sample);write_json(self.output,{'latest':sample,'samples':self.samples,'errors':self.errors})
            except Exception as exc:self.errors.append(str(exc))
            self.stop.wait(5)

    def close(self):self.stop.set();self.thread.join(timeout=7)


def save_project(root,state,historical,name='KoeSub - 30 minute native Whisper test'):
    config=state['config'];project=Project(name=name,media=config['media'],duration=config['media_duration'])
    if historical:project.add_track(historical)
    stages={}
    for stage in state['stages']:
        if stage['status']!='completed':continue
        value=read_json(stage['artifact'])
        if 'track' in value:
            track=track_from(value['track']);project.add_track(track);stages[stage['id']]=track.id
    project.active_track=state['final_track']
    project.pipeline_prefs={'transcription_only':True,'asr':config['asr'],'asr_count':1,'retry_clips':False,'jp_context_review':False,
        'adaptive_audio':False,'align_audio':False,'start':0,'length':config['duration']/1000}
    project.jobs=[{'type':'pipeline','id':state['id'],'created':now(),'manifest':str(root/'run/manifest.json'),
        'status':state['status'],'stage_tracks':stages,'track_hashes':{}}]
    pointer=root/'ui/last_project.json'
    if not pointer.exists():
        path=root/'ui/projects'/project.active.id/'project.sqlite';ProjectStore(path).save(project,'long native Whisper verification')
        write_json(pointer,{'path':str(path)})


def verify(root,source,seconds):
    if seconds<60 or seconds>1800:raise ValueError('Choose 60–1800 seconds for this bounded test')
    root.mkdir(parents=True,exist_ok=True);check_space(root,int(seconds*177000)+1024**3,2)
    settings=Settings.load();model=settings.use_subtitle_edit_whisper();settings.cache_dir=str(root/'cache')
    original=read_json(source);audio=Path(read_json(source.parent/'audio/result.json')['audio'])
    with wave.open(str(audio),'rb') as w:
        duration=round(w.getnframes()/w.getframerate()*1000);source_format={'rate':w.getframerate(),'channels':w.getnchannels()}
    length=round(seconds*1000)
    if length>duration:raise ValueError('Cached source is shorter than the chosen interval')
    config={'media':str(audio),'media_duration':duration,'start':0,'duration':length,'audio_track':0,
        'asr':[{'engine':0,'name':model.name,'model':str(model),'kind':'Whisper / CTranslate2','vad':True}],
        'translations':[],'transcription_only':True,'source_review_version':None,'retry_asr':{'enabled':False},'adaptive_retry':{'enabled':False},
        'asr_timing_review':{'enabled':True,'max_targets':8},
        'jp_alignment':{'enabled':False},'backend':'embedded','judge_model':'','review':'rules','review_settings':{},'settings':asdict(settings),
        'xxl_device':'cuda','xxl_compute':'float16','readability_repair':True,'export_srt':True,'export_format':'srt','output_dir':str(root/'exports')}
    protocol={'production':{str(p):audio_digest(p) for p in sorted(Path('studio').glob('*.py'))},'source_manifest':str(source),
        'source_audio_sha256':audio_digest(audio),'source_format':source_format,'range_ms':[0,length],
        'limitation':'Cached 16 kHz mono input when original movie is unavailable; stereo conversion cannot recover original channels. No complete reference transcript.'}
    receipt=root/'protocol.json'
    if receipt.exists() and read_json(receipt)!=protocol:raise ValueError('Changed frozen long-test policy/input')
    write_json(receipt,protocol);manifest=root/'run/manifest.json'
    if not manifest.exists():create_run(config,manifest.parent)
    elif load_run(manifest)['config']!=config:raise ValueError('Changed long-test configuration')
    initial=read_json(manifest);replayed=[s['id'] for s in initial['stages'] if s['status']=='completed']
    if (root/'summary.json').exists() and initial['status']=='failed':
        raise RuntimeError('Recorded long-test failure retained; use a new output directory to retry inference')
    if len(replayed)==len(initial['stages']) and (root/'summary.json').exists():
        audit_result(manifest)
        print('CACHED AUDIT: completed long-test artifacts verified; original measurements and telemetry retained',flush=True)
        return read_json(root/'summary.json')
    pointer=Path('data/last_project.json');before=pointer.read_bytes() if pointer.exists() else None
    gpu=GpuTelemetry(manifest,root/'gpu.json',capture_processes=True);live=LiveMonitor(manifest,root/'live.json')
    started=time.monotonic();gpu.start();live.thread.start();error=None
    try:run_pipeline(manifest,lambda kind,**d:print(d['message'],flush=True) if kind=='phase' else None)
    except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
    finally:live.close();telemetry=gpu.close()
    state=read_json(manifest);result={'manifest':str(manifest),'wall_seconds':round(time.monotonic()-started,3),'replayed_stages':replayed,
        'status':state['status'],'error':error,'stages':state['stages'],'source_format':source_format,
        'gpu_peak_mib':max((s['memory_used_mib'] for s in telemetry['samples']),default=None),'gpu_errors':telemetry['errors'],
        'minimum_available_ram_mib':min((s['available_ram_mib'] for s in live.samples if 'available_ram_mib' in s),default=None),
        'engine_peak_ram_mib':max((s['engine_peak_ram_mib'] for s in live.samples if 'engine_peak_ram_mib' in s),default=None),
        'monitor_errors':live.errors,'scope':'Long source-only integration and technical diagnostics; no transcription accuracy claim'}
    engine_receipt=manifest.parent/'asr-0/engine-process.json'
    pid=read_json(engine_receipt)['pid'] if engine_receipt.exists() else None
    result['engine_pid_observed_on_nvidia']=pid is not None and any(p['pid']==pid for p in telemetry.get('compute_processes',[]))
    native_files=list((manifest.parent/'asr-0').glob('*.srt'))
    if len(native_files)==1:result['raw_native']=transcript_diagnostics(load_srt(native_files[0]),length)
    native_documents=[read_json(p) for p in (manifest.parent/'asr-0').glob('*.json')]
    native_documents=[v for v in native_documents if isinstance(v,dict) and 'segments' in v]
    if len(native_documents)==1:result['native_confidence']=native_confidence_diagnostics(native_documents[0])
    historical=None;old=list((source.parent/'asr-0').glob('*.srt'))
    if len(old)==1:
        historical=load_srt(old[0]);historical.segments=[c for c in historical.segments if 0<=c.start<=c.end<=length]
        historical.name='Historical whisper.cpp raw hypotheses - includes invalid times'
        result['historical_diagnostics']=transcript_diagnostics(historical,length)
    if not error:
        try:audit_result(manifest);result['exact_export_audit']=True
        except AssertionError as exc:result.update(exact_export_audit=False,export_audit_error=str(exc))
        final=track_from(read_json(manifest.parent/'jp-layout/result.json')['track']);result['final']=transcript_diagnostics(final,length)
        snapshot=[(s['id'],s['digest'],s['seconds']) for s in state['stages']]
        native_before={str(p):audio_digest(p) for p in manifest.parent.rglob('engine-process.json')}
        run_pipeline(manifest,lambda *a,**k:None);resumed=read_json(manifest)
        result['resume_unchanged']=snapshot==[(s['id'],s['digest'],s['seconds']) for s in resumed['stages']] and native_before=={str(p):audio_digest(p) for p in manifest.parent.rglob('engine-process.json')}
        save_project(root,state,historical)
    result['main_project_unchanged']=(pointer.read_bytes() if pointer.exists() else None)==before
    result['production_policy_unchanged']=protocol['production']=={str(p):audio_digest(p) for p in sorted(Path('studio').glob('*.py'))}
    write_json(root/'summary.json',result)
    print('LONG TEST',result['status'],result['wall_seconds'],'seconds; summary:',root/'summary.json',flush=True)
    if error:raise RuntimeError('Long native test failed; retained diagnostics: '+str(root/'summary.json'))


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-manifest',type=Path,required=True);parser.add_argument('--seconds',type=int,default=1800)
    args=parser.parse_args();verify(args.output,args.source_manifest,args.seconds)


if __name__=='__main__':main()

"""Summarize completed full-video timings, readability flags and GPU evidence without inference."""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

from studio.core import atomic_text
from studio.pipeline import track_from
from studio.pipeline_worker import read_json
from studio.review import ReviewSettings,review_track


def quality(track,rules,duration):
    rows=review_track(track,rules,duration)
    return {'cues':len(track.segments),'warning_cues':sum(bool(r['issues']) for r in rows),
            'english_too_fast':sum((r['en']['cps'] or 0)>rules.en_cps for r in rows),
            'japanese_too_fast':sum((r['jp']['cps'] or 0)>rules.jp_cps for r in rows),
            'cues_with_overlap':sum(any('Nakładanie' in issue for issue in r['issues']) for r in rows),
            'ai_flagged':sum(any(n.startswith('AI:') for n in s.notes) for s in track.segments)}


def summarize(folder):
    timing=read_json(folder/'timings.json')
    state=read_json(timing['manifest']);rules=ReviewSettings.load(state['config']['review_settings'])
    path=Path(timing['manifest']).parent
    result={'timings':timing,'backend':{'asr':state['config']['settings']['crisp_gpu_backend'],
                                      'llm':state['config']['settings']['llm_device']},
            'quality':{},'gpu_evidence':{}}
    tracks={}
    for key in ('asr-0','asr-1','asr-2','merge-1','merge-2','choose-en','semantic','repair','verify','layout'):
        if not (path/key/'result.json').exists():
            continue
        data=read_json(path/key/'result.json')
        if 'track' not in data:
            result['quality'][key]={'rejected':True,'failure':data.get('asr_failure')}
            continue
        track=track_from(data['track']);tracks[key]=track
        result['quality'][key]=quality(track,rules,state['config']['media_duration'])
    result['translation_changes_by_repair']=sum(a.translation!=b.translation for a,b in zip(tracks['semantic'].segments,tracks['repair'].segments))
    for key in ('asr-0','asr-1','asr-2'):
        if not (path/key/'engine.log').exists():
            continue
        log=(path/key/'engine.log').read_text('utf8',errors='replace')
        result['gpu_evidence'][key]=[line for line in log.splitlines() if any(t in line for t in ('CUDA','Vulkan','use gpu','GPU backend','transcribed'))][:12]
    log_path=next((log for stage in state['stages'] if not stage['id'].startswith('asr-')
                   for log in (path/stage['id']).rglob('engine.log')),None)
    if log_path is None: log_path=next((path/'native-sessions').glob('*/engine.log'),None)
    if log_path:
        result['gpu_evidence']['llm']={'path':str(log_path),'lines':[s for s in log_path.read_text('utf8',errors='replace').splitlines() if 'system_info' in s]}
    if (folder/'gpu-telemetry.json').exists():
        telemetry=read_json(folder/'gpu-telemetry.json')
        result['telemetry_summary']=telemetry['summary'];result['telemetry_errors']=telemetry['errors']
    loads=[]
    calls={}
    for stage in state['stages']:
        native_calls=list((path/stage['id']).rglob('command.json'))
        if native_calls: calls[stage['id']]=len(native_calls)
        for command in native_calls:
            log=command.with_name('engine.log')
            if log.exists():
                match=re.search(r'load time\s*=\s*([\d.]+) ms',log.read_text('utf8',errors='replace'))
                if match: loads.append(float(match[1])/1000)
    result['native_llm_calls']=calls
    result['warm_session_calls']={stage['id']:len(list((path/stage['id']).rglob('transport.json')))
                                  for stage in state['stages'] if list((path/stage['id']).rglob('transport.json'))}
    result['native_sessions']=[read_json(f) for f in (path/'native-sessions').glob('*/session.json')]
    result['model_load_time_from_logs']={'scope':'Stage-local decision/review calls; translation batches may use the shared embedded-translation cache',
                                         'calls_with_measurement':len(loads),'total_seconds':round(sum(loads),3),
                                         'median_seconds':round(statistics.median(loads),3) if loads else None}
    final=tracks['layout'];rows=review_track(final,rules,state['config']['media_duration'])
    result['flagged_examples']=[{'index':i+1,'start':s.start,'end':s.end,'jp':s.text,'en':s.translation,'issues':r['issues']}
                                for i,(s,r) in enumerate(zip(final.segments,rows)) if r['issues']]
    return result


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folders',nargs='+',type=Path);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result={str(folder):summarize(folder) for folder in args.folders}
    atomic_text(args.out,json.dumps(result,ensure_ascii=False,indent=2))
    for folder,item in result.items():
        print(folder,'seconds:',item['timings']['wall_seconds'],'final:',item['quality']['layout'],
              'EN changes:',item['translation_changes_by_repair'],flush=True)
    print('Summary:',args.out)


if __name__=='__main__': main()

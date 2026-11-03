"""Frozen real-audio omission probes and no-speech controls using existing local assets."""
import argparse
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
import time
from types import MethodType,SimpleNamespace

from studio.asr_coverage import search_coverage
from studio.audio_boundaries import audio_digest
from studio.core import Track
from studio.evaluation_text import normalize_text
from studio.pipeline_worker import PipelineRunner,read_json,write_json
from studio.storage import Settings
from tools.benchmark_asr_fusion import cuda_evidence
from tools.compare_local_film import exact_distance
from tools.gpu_telemetry import GpuTelemetry

CASES=('fleurs-validation-33','fleurs-validation-34','fleurs-validation-35','silence','noise-only')


def verify(bank,output):
    if output.exists():raise ValueError('Use a fresh control output directory')
    output.mkdir(parents=True)
    policy={str(p):audio_digest(p) for p in sorted(Path('studio').glob('*.py'))}
    source_hashes={};inputs=[]
    for name in CASES:
        manifest=bank/'runs'/name/'manifest.json';source=read_json(manifest)
        audio=Path(read_json(manifest.parent/'audio/result.json')['audio'])
        source_hashes[str(manifest)]=audio_digest(manifest);source_hashes[str(audio)]=audio_digest(audio)
        inputs.append({'id':name,'source':source,'audio':audio})
    write_json(output/'protocol.json',{'production':policy,'source_hashes':source_hashes,
        'cases':list(CASES),'selection':'Three fixed published FLEURS clips, all baseline cues omitted; existing silence/noise controls',
        'labels_sha256':audio_digest(bank/'labels.json'),'labels_used_for_inference':False})
    rows=[]
    for item in inputs:
        name=item['id'];root=output/name;root.mkdir()
        config=deepcopy(item['source']['config']);settings=Settings(**config['settings'])
        if settings.crisp_gpu_backend!='cuda':raise ValueError('CUDA is required')
        settings.cache_dir=str(root/'cache')
        config.update(asr_coverage={'enabled':True,'version':2,'chunk_ms':30000,'padding_ms':3000},settings=asdict(settings))
        state={'status':'running','stages':[{'id':'asr-coverage','status':'running'}]}
        manifest=root/'probe.json';write_json(manifest,state)
        runner=SimpleNamespace(config=config,settings=settings,folder=root,
            event=lambda kind,**data:print(name,data.get('message',''),flush=True),progress=lambda *a:None)
        runner.call=MethodType(PipelineRunner.call,runner)
        folder=root/'coverage';folder.mkdir();telemetry=GpuTelemetry(manifest,root/'gpu.json',capture_processes=True)
        started=time.monotonic();telemetry.start()
        baseline=Track('Controlled empty baseline')
        try:result=search_coverage(runner,folder,baseline,item['audio'])
        except Exception as exc:
            state.update(status='failed',error=str(exc));state['stages'][0]['status']='failed';write_json(manifest,state)
            raise
        finally:gpu=telemetry.close()
        seconds=round(time.monotonic()-started,3);write_json(root/'result.json',result)
        processes={str(p):audio_digest(p) for p in folder.rglob('engine-process.json')}
        assert search_coverage(runner,folder,baseline,item['audio'])==result
        assert processes=={str(p):audio_digest(p) for p in folder.rglob('engine-process.json')}
        logs={str(p.relative_to(root)):cuda_evidence(p.read_text('utf8',errors='replace'))
              for p in folder.rglob('engine.log') if p.parent.name!='alignment'}
        aligners=[read_json(p)['pid'] for p in folder.glob('*/alignment/engine-process.json')]
        observed={p['pid'] for p in gpu.get('compute_processes',[])}
        rows.append({'id':name,'seconds':seconds,'candidates':len(result['candidates']),'added':len(result['changes']),
            'failed_outputs':len(result['failed_windows']),'text':''.join(s['text'] for s in result['track']['segments']),
            'cuda_logs':logs,'alignment_pids':aligners,'alignment_pids_observed':[p for p in aligners if p in observed],
            'gpu_errors':gpu['errors'],'scope':'Fresh coverage; empty baseline is a controlled omission, not a natural ASR error'})
        rows[-1]['replay_identical_no_new_processes']=True
        state.update(status='completed');state['stages'][0]['status']='completed';write_json(manifest,state)
        print(name,seconds,'seconds',rows[-1]['added'],'added',flush=True)
    assert policy=={str(p):audio_digest(p) for p in sorted(Path('studio').glob('*.py'))}
    assert all(audio_digest(Path(path))==value for path,value in source_hashes.items())
    labels=read_json(bank/'labels.json')
    for row in rows:
        reference=normalize_text(labels[row['id']]['reference_jp']);text=normalize_text(row['text'])
        row.update(reference_characters=len(reference),emitted_characters=len(text),edits=exact_distance(reference,text),
                   empty_baseline_edits=len(reference))
    summary={'cases':rows,'source_files_unchanged':True,'production_unchanged':True,
        'scope':'Controlled complete-omission recovery against published FLEURS references and no-speech controls; not independently listened natural-error quality'}
    write_json(output/'summary.json',summary)
    print('CONTROL SUMMARY',[(r['id'],r['added'],r['edits'],r['reference_characters']) for r in rows],flush=True)
    return summary


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--bank',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();verify(args.bank,args.output)

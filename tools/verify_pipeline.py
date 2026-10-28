"""Real one-click Qt pipeline: two GPU ASRs, two native translations, full review and SRT."""
import os
import time
import sys
import argparse
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtWidgets import QApplication
from studio import ui
from studio.core import Project, ProjectStore, load_srt
from studio.pipeline import digest, load_run, track_from
from studio.pipeline_worker import read_json


def audit_result(manifest):
    """Re-read on-disk results, rather than trust successful process exit alone."""
    state=load_run(manifest)
    if state['config'].get('benchmark_scope')=='asr-only':
        raise ValueError('This is an ASR-only benchmark; audit its comparison.json instead of full-pipeline exports')
    assert state['status'] in {'completed','needs_review'},state['status']
    for stage in state['stages']:
        assert stage['status']=='completed',stage
        assert digest(read_json(stage['artifact']))==stage['digest'],stage['id']
    jp_only=state['config'].get('transcription_only',False)
    final=track_from(read_json(next(s['artifact'] for s in state['stages'] if s['id']==('jp-layout' if jp_only else 'layout')))['track'])
    assert final.id==state['final_track'] and final.segments
    assert all(0<=s.start<s.end<=state['config']['media_duration'] and s.text.strip() and (jp_only or s.translation.strip())
               for s in final.segments)
    paths={Path(p).name:Path(p) for p in state['exports']}
    for name,english in ([('Japanese.srt',False)] if jp_only else [('Japanese.srt',False),('English.srt',True)]):
        recovered=load_srt(paths[name])
        expected=[(s.start,s.end,s.translation if english else s.text) for s in final.segments]
        assert [(s.start,s.end,s.text) for s in recovered.segments]==expected,name
    report=read_json(paths['report.json'])
    assert report['track']==final.id and report['status']==state['status']
    assert len(report['review'])==len(final.segments)
    assert report['warnings']==state['warnings']==sum(bool(r['issues']) for r in report['review'])
    assert not report['blocked_exports'],report['blocked_exports']
    print(f'On-disk checkpoint digests, {"JP" if jp_only else "JP/EN"} SRT roundtrip, bounds and report: OK; warnings: {state["warnings"]}',flush=True)
    return state


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    if '--audit' in sys.argv:
        audit_result(sys.argv[sys.argv.index('--audit')+1])
        return
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media',type=Path)
    parser.add_argument('--data-dir',type=Path,default=Path('D:/models/.cache/verification-pipeline-ui'))
    parser.add_argument('--full',action='store_true')
    parser.add_argument('--seconds',type=float,default=20)
    parser.add_argument('--start',type=float,default=0)
    gpu=parser.add_mutually_exclusive_group()
    gpu.add_argument('--cuda',action='store_true')
    gpu.add_argument('--vulkan',action='store_true')
    parser.add_argument('--timeout',type=float,default=3600)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--balanced',action='store_true')
    parser.add_argument('--whisper-fallback',action='store_true',
                        help='Two Whisper passes with/without VAD when Qwen alignment fails; same local weights')
    parser.add_argument('--single-whisper',action='store_true',
                        help='Use only the valid Whisper + VAD path, retaining full translation/review stages')
    parser.add_argument('--three-asr',action='store_true',help='Whisper Large V3, Qwen and Kotoba comparison preset')
    parser.add_argument('--jp-only',action='store_true',help='Large V3 baseline and audio retries, without translation or LLM')
    parser.add_argument('--retry-limit',type=int,default=12)
    args=parser.parse_args()
    ui.DATA = args.data_dir
    audio = args.media or Path('D:/models/.cache/verification-japanese/japanese20.wav')
    assert audio.is_file()
    app = QApplication([])
    app.setStyle('Fusion'); app.setStyleSheet(ui.STYLE); ui.setup_fonts(app)
    window = ui.Window()
    if args.cuda or args.vulkan:
        if args.cuda:
            runtimes=read_json('D:/models/.runtime/cuda-runtimes.json')
        else:
            import subprocess
            crisp='D:/models/.runtime/crispasr-v0.8.45-vulkan/crispasr-windows-x86_64-vulkan/crispasr.exe'
            version=subprocess.run([crisp,'--version'],capture_output=True,text=True,timeout=20,check=True)
            runtimes={'crisp':{'executable':crisp,'probe':version.stdout+version.stderr},
                      'llama':{'executable':'D:/models/.runtime/llama-b11935-vulkan/llama-completion.exe'}}
        backend='cuda' if args.cuda else 'vulkan'
        if window.backend_probe is not None:
            probe=window.backend_probe
            window.backend_probe=None
            probe.kill();probe.waitForFinished(5000)
        window.settings.crisp_exe=runtimes['crisp']['executable']
        window.settings.crisp_gpu_backend=backend
        window.settings.llm_exe=runtimes['llama']['executable']
        window.settings.llm_device=backend
        window.crisp_device.setCurrentText(backend)
        window.apply_crisp_backends(runtimes['crisp']['probe'])
        window.llm_device_combo.setCurrentIndex(window.llm_device_combo.findData(backend))
    failures = []
    window.fail = lambda error: failures.append(str(error))
    resume = args.resume
    probe_seconds=0
    if not resume:
        window.project = Project(name='Pipeline • '+audio.stem)
        window.store = None
        if args.media:
            started=time.monotonic()
            window.import_media_path(audio)
            until=time.monotonic()+40
            while window.busy and time.monotonic()<until:
                app.processEvents();time.sleep(.025)
            assert not window.busy and not failures,failures
            assert window.project.duration>0
            probe_seconds=time.monotonic()-started
        else:
            window.project.media=str(audio)
            window.project.duration=20000
            window.changed('pipeline hardware verification')
    panel = window.pipeline_panel
    if args.cuda or args.vulkan or args.whisper_fallback or args.single_whisper:
        original_config=panel.config
        def diagnostic_config(run_id):
            config=original_config(run_id)
            config['diagnostic_logging']=True
            if args.whisper_fallback or args.single_whisper:
                import copy
                whisper=next(item for item in config['asr'] if item['engine']==2)
                config['asr']=[{**copy.deepcopy(whisper),'vad':vad} for vad in ((True,) if args.single_whisper else (True,False))]
                config['benchmark_fallback']=('Qwen alignment and Whisper without VAD failed; only Whisper + VAD'
                    if args.single_whisper else 'Qwen alignment failed; two Whisper passes with/without VAD, same weights')
            return config
        panel.config=diagnostic_config
    panel.apply_preset(5 if args.jp_only else 4 if args.three_asr else 0 if args.balanced else 2)
    if args.jp_only:panel.retry_limit.setValue(args.retry_limit)
    if args.single_whisper:
        panel.asr_count.setValue(1)
        panel.vad[0].setChecked(True)
    panel.length.setValue(0 if args.full else args.seconds)
    panel.start.setValue(args.start)
    panel.pause.setChecked(False)
    window.tabs.setCurrentWidget(panel)
    window.show()
    app.processEvents()
    started=time.monotonic()
    panel.resume_run() if resume else panel.start_run()
    assert window.busy and not failures,failures
    from .gpu_telemetry import GpuTelemetry
    telemetry=GpuTelemetry(window.job['manifest'],ui.DATA/'gpu-telemetry.json')
    telemetry.start()
    deadline = time.monotonic()+args.timeout
    last_stage = None
    while window.busy and time.monotonic()<deadline:
        app.processEvents()
        if window.job:
            state = read_json(window.job['manifest'])
            current = next((s['label'] for s in state['stages'] if s['status']=='running'),None)
            if current and current!=last_stage:
                print(current,flush=True)
                last_stage=current
        time.sleep(.05)
    if window.busy:
        window.runner.cancel()
        until=time.monotonic()+20
        while window.busy and time.monotonic()<until:
            app.processEvents();time.sleep(.025)
        telemetry.close()
        raise AssertionError('Pipeline hardware test timed out; cancellation requested')
    telemetry.close()
    assert not failures,failures
    assert window.job['status'] in {'completed','needs_review'},window.job
    state = read_json(window.job['manifest'])
    assert all(s['status']=='completed' for s in state['stages']),state
    assert window.project.active.id==state['final_track']
    jp_only=window.job and read_json(window.job['manifest'])['config'].get('transcription_only',False)
    assert all(s.text and (jp_only or s.translation) for s in window.project.active.segments)
    saved = ProjectStore(window.store.path).load()
    assert saved.active.id==state['final_track']
    assert all(Path(p).is_file() for p in state['exports'])
    assert len([p for p in state['exports'] if p.endswith('.srt')])==(1 if jp_only else 2)
    audit_result(window.job['manifest'])
    from studio.core import atomic_text
    import json
    from studio.review import ReviewSettings,review_track
    timing={'manifest':window.job['manifest'],'project':str(window.store.path),
            'media':str(audio.resolve()),'media_seconds':state['config']['duration']/1000,
            'probe_seconds':round(probe_seconds,3),'wall_seconds':round(time.monotonic()-started,3),
            'status':state['status'],'warnings':state['warnings'],
            'backend':{'asr':state['config']['settings']['crisp_gpu_backend'],'llm':state['config']['settings']['llm_device']},
            'stages':[{'id':s['id'],'label':s['label'],'seconds':s.get('seconds',0)} for s in state['stages']],
            'tracks':[{'id':t.id,'name':t.name,'cues':len(t.segments),
                       'warnings':sum(bool(row['issues']) for row in review_track(t,ReviewSettings.load(saved.review_settings),saved.duration))}
                      for t in saved.tracks]}
    atomic_text(ui.DATA/'timings.json',json.dumps(timing,ensure_ascii=False,indent=2))
    print('Timings:',ui.DATA/'timings.json',flush=True)
    app.processEvents()
    window.grab().save(str(ui.DATA/'pipeline-preview.png'))
    print('Qt -> Large V3 baseline -> targeted audio retries -> JP SRT (no translation/LLM): OK' if jp_only else
          f'Qt -> {len(state["config"]["asr"])} ASR -> {len(state["config"]["translations"])} EN -> EN selection -> full AI review -> SRT: OK',flush=True)
    print('Manifest:',window.job['manifest'],flush=True)
    print('Tracks:',len(saved.tracks),'final cues:',len(saved.active.segments),flush=True)
    window.close()


if __name__=='__main__':
    main()

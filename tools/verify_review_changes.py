"""Real CUDA check of automatic review edits/undo, optionally whole-film context on the full benchmark."""
import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtWidgets import QApplication
from studio import ui
from studio.ai_review import request_json
from studio.context_review import overview,coherence
from studio.core import Project,ProjectStore,Segment,Track,atomic_text
from studio.pipeline_worker import read_json
from studio.storage import Settings


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--whole',action='store_true')
    args=parser.parse_args()
    ui.DATA=Path('D:/models/.cache/verification-review-changes');ui.DATA.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);window=ui.Window();failures=[];window.fail=lambda error:failures.append(str(error))
    window.project=Project(name='Review • controlled incorrect English');window.store=None
    window.project.add_track(Track('JP / EN',[
        Segment(0,3000,'私は田中です。',translation='My name is Suzuki.',status='machine'),
        Segment(3500,6500,'今日は月曜日です。',translation='Today is Friday.',status='machine'),
        Segment(7000,10000,'明日は学校へ行きます。',translation='Tomorrow I will go to school.',status='machine'),
        Segment(10500,12000,'はい。',translation='My own wording.',status='manual')]))
    original=[s.translation for s in window.project.active.segments]
    window.changed('review hardware verification');panel=window.ai_review_panel
    panel.mode.setCurrentIndex(panel.mode.findData('full'));panel.auto_apply.setChecked(True);panel.film_context.setChecked(True)
    window.tabs.setCurrentWidget(panel);window.show();app.processEvents()
    started=time.monotonic();panel.start();deadline=time.monotonic()+300
    while window.busy and time.monotonic()<deadline: app.processEvents();time.sleep(.025)
    assert not window.busy and not failures,failures
    applied=window.job.get('applied_changes',0)
    assert applied>=1,window.project.ai_reviews
    assert window.project.active.segments[-1].translation==original[-1]
    assert all(s.review_status=='unreviewed' for s in window.project.active.segments)
    saved=ProjectStore(window.store.path).load()
    assert any(a!=s.translation for a,s in zip(original,saved.active.segments))
    panel.filter.setCurrentIndex(panel.filter.findData('accepted'));app.processEvents()
    window.grab().save(str(ui.DATA/'automatic-review.png'))
    job=dict(window.job);window.undo();assert [s.translation for s in window.project.active.segments]==original
    window.redo();assert window.project.active.segments[0].translation!=original[0] or window.project.active.segments[1].translation!=original[1]
    atomic_text(ui.DATA/'automatic-result.json',json.dumps({'applied':applied,'seconds':round(time.monotonic()-started,2),
                'before':original,'after':[s.translation for s in window.project.active.segments],
                'job':job,'undo_redo':'passed','manual_english_preserved':True},ensure_ascii=False,indent=2))
    print('Real review automatic edits:',applied,'manual EN preserved; SQLite + undo/redo: OK',flush=True)
    window.close()
    if args.whole:
        settings=Settings.load();timing=read_json('D:/models/.cache/benchmark-easy-cuda-full/timings.json')
        project=ProjectStore(Path(timing['project'])).load();track=project.active
        spec={'backend':'embedded','model_path':settings.llm_model,'executable':settings.llm_exe,
              'device':settings.llm_device,'context_length':settings.llm_context,'cache_dir':settings.cache_dir,'reserve_gib':2}
        request=lambda instruction,payload,schema,folder:request_json(spec,instruction,payload,schema,folder)
        emit=lambda kind,**data:print(data['message'],flush=True) if kind=='phase' else None
        started=time.monotonic()
        context=overview(track,request,ui.DATA/'whole/context',emit=emit)
        consistency=coherence(track,context['overview'],request,ui.DATA/'whole/coherence',emit=emit)
        atomic_text(ui.DATA/'whole-result.json',json.dumps({'source_project':timing['project'],'cues':len(track.segments),
                    'seconds':round(time.monotonic()-started,2),'context':context,'coherence':consistency},ensure_ascii=False,indent=2))
        print('Whole-film text context:',len(track.segments),'cues; issues:',sum(v!='ok' for v in consistency['decisions'].values()),flush=True)
        print(context['overview'],flush=True)


if __name__=='__main__': main()

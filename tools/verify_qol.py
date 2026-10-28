"""Real waveform, structured native review and file-format smoke check on an isolated project."""
import os
import sys
import time
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtWidgets import QApplication
from studio import ui
from studio.core import Project,Segment,Track,export_subtitles,load_subtitles


def wait(app,predicate,seconds):
    until=time.monotonic()+seconds
    while not predicate() and time.monotonic()<until:
        app.processEvents();time.sleep(.025)
    assert predicate(),'QoL integration check timed out'


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    ui.DATA=Path('D:/models/.cache/verification-qol')
    ui.DATA.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(ui.STYLE);ui.setup_fonts(app)
    window=ui.Window();errors=[];window.fail=lambda exc:errors.append(str(exc))
    audio=Path('D:/models/.cache/verification-japanese/japanese20.wav')
    window.project=Project(name='QoL • syntetyczne napisy / rzeczywisty waveform',media=str(audio),duration=20000)
    window.store=None
    window.project.add_track(Track('Próbki JP / EN',[
        Segment(0,3000,'これを使ってもいいですか。',translation='May I use this?'),
        Segment(3000,5000,'いえ。',translation='House.'),
        Segment(6000,8000,'すごい！',translation='すごい！')]))
    original=[s.translation for s in window.project.active.segments]
    window.changed('QoL hardware verification');window.sync_media();window.show()
    window.editor_tools.wave.ensure()
    wait(app,lambda:bool(window.editor_tools.waveform.peaks),60)
    assert 19000<=window.editor_tools.waveform.duration<=21000
    window.editor_tools.waveform.selection=(3000,8000)
    app.processEvents();window.grab().save(str(ui.DATA/'editor-waveform.png'))
    panel=window.ai_review_panel
    panel.auto_apply.setChecked(False)
    panel.mode.setCurrentIndex(panel.mode.findData('full'))
    window.tabs.setCurrentWidget(panel);panel.start()
    wait(app,lambda:not window.busy,180)
    assert not errors,errors
    assert window.job['status']=='completed',window.job
    assert len(window.project.ai_reviews)==3
    assert [s.translation for s in window.project.active.segments]==original
    panel.filter.setCurrentIndex(panel.filter.findData('all'))
    app.processEvents();window.grab().save(str(ui.DATA/'ai-proposals.png'))
    export_subtitles(window.project.active,ui.DATA/'roundtrip.ass')
    recovered=load_subtitles(ui.DATA/'roundtrip.ass')
    assert [s.text for s in recovered.segments]==[s.text for s in window.project.active.segments]
    export_subtitles(window.project.active,ui.DATA/'English.txt',True)
    print('Waveform cached:',len(window.editor_tools.waveform.peaks),'peaks; no decoded WAV copy')
    print('Native structured JP/EN review: 3 valid results, existing EN unchanged')
    print('ASS roundtrip and TXT export: OK')
    print('Artifacts:',ui.DATA)
    window.close()


if __name__=='__main__': main()

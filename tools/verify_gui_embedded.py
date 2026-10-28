"""Real Qt -> worker -> native GGUF -> SQLite and cancellation integration check."""
import os
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtWidgets import QApplication
from studio import ui
from studio.core import Project,ProjectStore,load_srt


def wait(app,predicate,seconds):
    until=time.monotonic()+seconds
    while not predicate() and time.monotonic()<until:
        app.processEvents()
        time.sleep(.02)
    assert predicate(),'UI integration check timed out'


def short_project():
    project=Project(name='Embedded GUI verification')
    track=load_srt(Path('D:/models/.cache/verification-japanese/transcript.srt'))
    track.segments=track.segments[:2]
    project.add_track(track)
    return project


def main():
    ui.DATA=Path('D:/models/.cache/verification-gui-embedded')
    app=QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(ui.STYLE)
    ui.setup_fonts(app)
    window=ui.Window()
    errors=[]
    window.fail=lambda error:errors.append(str(error))
    window.project=short_project()
    window.changed('test native GUI')
    window.tabs.setCurrentIndex(3)
    window.show()
    app.processEvents()
    assert window.translation_backend.currentData()=='embedded'
    assert window.asr_engine.currentIndex()==2
    window.start_translation()
    wait(app,lambda:not window.busy,90)
    assert not errors,errors
    assert window.job['status']=='completed'
    assert window.progress.value()==window.progress.maximum()
    assert all(s.translation for s in window.project.active.segments)
    saved=ProjectStore(window.store.path).load()
    assert all(s.translation for s in saved.active.segments)
    app.processEvents()
    window.grab().save(str(ui.DATA/'embedded-preview.png'))
    print('Qt native translation -> saved SQLite: OK',flush=True)
    window.project=short_project()
    window.changed('test native cancellation')
    window.start_translation()
    wait(app,lambda:window.busy,5)
    until=time.monotonic()+1.0
    while time.monotonic()<until:
        app.processEvents()
        time.sleep(.02)
    window.runner.cancel()
    wait(app,lambda:not window.busy,15)
    assert window.job['status']=='cancelled',window.job
    assert not errors,errors
    print('Qt cancellation and saved job status: OK',flush=True)
    window.close()


if __name__=='__main__':
    main()

import os
import time
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from studio import ui
from studio.editing_ui import CleanupDialog,ShiftDialog
from studio.review import ReviewSettings


def main():
    ui.DATA=Path('D:/models/.cache/verification-qol')
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(ui.STYLE);ui.setup_fonts(app)
    window=ui.Window();window.show();window.editor_tools.wave.ensure()
    until=time.monotonic()+15
    while not window.editor_tools.waveform.peaks and time.monotonic()<until:
        app.processEvents();time.sleep(.02)
    window.tabs.setCurrentIndex(0);app.processEvents();window.grab().save(str(ui.DATA/'editor-waveform.png'))
    window.tabs.setCurrentWidget(window.ai_review_panel)
    app.processEvents();window.grab().save(str(ui.DATA/'ai-proposals.png'))
    dialog=CleanupDialog(window,window.project.active,ReviewSettings(),window.project.duration)
    dialog.merge.setChecked(True);dialog.timing.setChecked(True);dialog.show();app.processEvents()
    dialog.grab().save(str(ui.DATA/'cleanup-preview.png'));dialog.close()
    shift=ShiftDialog(window,window.project.active,[0],window.player.position())
    shift.offset.setValue(500);shift.show();app.processEvents();shift.grab().save(str(ui.DATA/'shift-preview.png'));shift.close()
    window.resize(960,700);app.processEvents()
    assert window.height()==700 and window.centralWidget().verticalScrollBar().maximum()>0
    window.grab().save(str(ui.DATA/'compact-window.png'))
    window.close()


if __name__=='__main__': main()

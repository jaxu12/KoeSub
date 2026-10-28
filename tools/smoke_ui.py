"""Manual integration smoke test using a synthetic video; no model downloads."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from studio import ui
from studio.core import load_srt
from studio.storage import ROOT


def wait(app, predicate, seconds):
    deadline = time.monotonic()+seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.02)
    assert predicate(), 'Timed out'


def main():
    ui.DATA = ROOT/'data'/'smoke'/'gui'
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(ui.STYLE)
    ui.setup_fonts(app)
    window = ui.Window()
    errors = []
    window.fail = lambda error: errors.append(str(error))
    window.show()
    window.audio.setMuted(True)
    window.import_media_path(ROOT/'data'/'smoke'/'video.mp4')
    wait(app, lambda: not window.busy, 20)
    assert window.audio_combo.count() == 1
    assert window.project.duration > 6000
    window.project.add_track(load_srt(ROOT/'data'/'smoke'/'speech.srt'))
    window.changed('smoke import')
    window.player.play()
    wait(app, lambda: window.player.position() > 1500, 15)
    assert window.player.error() == QMediaPlayer.Error.NoError, window.player.errorString()
    window.player.pause()
    app.processEvents()
    window.grab().save(str(ROOT/'data'/'smoke'/'video-preview.png'))
    assert not errors, errors
    print('Video playback, audio-track probe, position updates, subtitle preview and project save: OK')
    window.close()


if __name__ == '__main__':
    main()

"""Hardware integration check for runtime capability selection and Whisper ASR."""
import os
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from studio import ui
from studio.core import Project, ProjectStore


def wait(app, predicate, seconds):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.02)
    assert predicate(), 'ASR GUI integration check timed out'


def main():
    ui.DATA = Path('D:/models/.cache/verification-gui-asr-backend')
    audio = Path('D:/models/.cache/audio-bd92b24f202327b540788e79.wav')
    assert audio.is_file(), 'Requires previously extracted Japanese audio'
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(ui.STYLE)
    ui.setup_fonts(app)
    window = ui.Window()
    errors = []
    window.fail = lambda error: errors.append(str(error))
    window.show()
    wait(app, lambda: window.backend_probe is None, 10)
    assert window.crisp_device.currentText() == 'vulkan'
    assert not window.crisp_device.model().item(window.crisp_device.findText('cuda')).isEnabled()
    window.project = Project(name='ASR backend verification', media=str(audio), duration=60000)
    window.changed('hardware verification')
    window.asr_engine.setCurrentIndex(2)
    window.asr_length.setValue(60)
    window.tabs.setCurrentIndex(1)
    window.start_asr()
    wait(app, lambda: not window.busy, 120)
    assert not errors, errors
    assert window.job['status'] == 'completed', window.job
    assert window.job['crisp_gpu_backend'] == 'vulkan'
    assert window.project.active.segments
    recovered = ProjectStore(window.store.path).load()
    assert recovered.active.segments
    folder = Path(window.job['output'])
    assert 'cpu,vulkan' in (folder/'engine-version.txt').read_text('utf8')
    log = (folder/'engine.log').read_text('utf8')
    assert 'using Vulkan0 backend' in log
    assert 'falling back' not in log
    window.tabs.setCurrentIndex(1)
    app.processEvents()
    window.grab().save(str(ui.DATA/'backend-preview.png'))
    print('Qt capabilities -> Vulkan -> Whisper -> SQLite: OK', flush=True)
    print('Segments:', len(recovered.active.segments), flush=True)
    print('Run:', folder, flush=True)
    window.close()


if __name__ == '__main__':
    main()

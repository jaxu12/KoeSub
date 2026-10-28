"""Check the actual saved CUDA defaults in a fresh isolated Qt window, without loading weights."""
import os
import time
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from studio import ui


def main():
    ui.DATA=Path('D:/models/.cache/verification-cuda-startup')
    app=QApplication([])
    window=ui.Window()
    until=time.monotonic()+8
    while window.backend_probe is not None and time.monotonic()<until:
        app.processEvents();time.sleep(.02)
    assert window.backend_probe is None
    assert window.settings.crisp_gpu_backend=='cuda'
    assert window.crisp_device.currentText()=='cuda'
    assert window.crisp_device.model().item(window.crisp_device.findText('cuda')).isEnabled()
    assert not window.crisp_device.model().item(window.crisp_device.findText('vulkan')).isEnabled()
    assert window.settings.llm_device==window.llm_device_combo.currentData()=='cuda'
    assert window.pipeline_panel.backend.currentData()=='embedded'
    print('Saved defaults -> Qt -> ASR CUDA enabled / LLM CUDA selected: OK',flush=True)
    window.close()


if __name__=='__main__': main()

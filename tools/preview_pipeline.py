"""Show the completed hardware verification project in an offscreen screenshot."""
import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from studio import ui


def main():
    ui.DATA = Path('D:/models/.cache/verification-pipeline-ui')
    app = QApplication([])
    app.setStyle('Fusion'); app.setStyleSheet(ui.STYLE); ui.setup_fonts(app)
    window = ui.Window()
    window.tabs.setCurrentWidget(window.pipeline_panel)
    window.show()
    app.processEvents()
    window.grab().save(str(ui.DATA/'pipeline-preview.png'))
    window.close()


if __name__=='__main__':
    main()

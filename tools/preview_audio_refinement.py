"""Render saved adaptive hypothesis and final timing comparisons without inference."""
import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from studio import ui


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('data_dir',type=Path);args=parser.parse_args()
    ui.DATA=args.data_dir.resolve()
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(ui.STYLE);ui.setup_fonts(app)
    window=ui.Window();window.resize(1180,900);window.tabs.setCurrentWidget(window.pipeline_panel);window.show();app.processEvents()
    panel=window.pipeline_panel
    panel.show_alignment_results();app.processEvents()
    path=ui.DATA/'timing-preview.png'
    if not panel.alignment_dialog.grab().save(str(path)):raise ValueError('Could not save timing preview')
    panel.alignment_dialog.close()
    panel.show_adaptive_results();app.processEvents()
    other=ui.DATA/'adaptive-preview.png'
    if not panel.adaptive_dialog.grab().save(str(other)):raise ValueError('Could not save adaptive preview')
    print(path);print(other)
    panel.adaptive_dialog.close();window.close();app.processEvents()


if __name__=='__main__':main()

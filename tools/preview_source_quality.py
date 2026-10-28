"""Render the offline quality workbench and optionally smoke-test clip playback.

Playback is an integration check, never a human reference audit.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer

from studio import ui
from studio.core import atomic_text
from studio.evaluation_text import score_text


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('study',type=Path)
    parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--audio-smoke',action='store_true');args=parser.parse_args()
    args.data_dir.mkdir(parents=True,exist_ok=True);ui.DATA=args.data_dir.resolve()
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(ui.STYLE);ui.setup_fonts(app)
    window=ui.Window();window.resize(1180,900);panel=window.evaluation_panel;panel.load_study(args.study)
    window.tabs.setCurrentWidget(panel);window.show();app.processEvents()
    selected=next((i for i,c in enumerate(panel.study['cases']) if c['variants']['baseline']['available'] and
        score_text(c['reference'],c['variants']['baseline']['text'])['edit_distance']),0)
    panel.cases.setCurrentIndex(selected);app.processEvents();before=args.study.read_bytes();position=None
    if args.audio_smoke:
        panel.play_clip();started=time.monotonic()
        while time.monotonic()-started<5:
            app.processEvents()
            if panel.player.error()!=QMediaPlayer.Error.NoError:raise ValueError(panel.player.errorString())
            if panel.player.position()>250:break
            time.sleep(.02)
        position=panel.player.position();panel.player.stop()
        if not position:raise ValueError('Audio playback did not advance')
    output=args.data_dir/'source-quality-preview.png'
    if not window.grab().save(str(output)):raise ValueError('Could not render quality preview')
    assert args.study.read_bytes()==before
    result={'cases':len(panel.study['cases']),'selected':panel.case()['id'],'playback_position_ms':position,
        'study_unchanged':True,'scope':'UI and playback integration only; no reference audit or semantic assessment performed'}
    atomic_text(args.data_dir/'ui-verification.json',json.dumps(result,indent=2))
    print(output);print(result);window.close();app.processEvents()


if __name__=='__main__':main()

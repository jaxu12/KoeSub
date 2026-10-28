"""Render the source-review dialog for a saved comparison project."""
import argparse
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication, QTableWidget
from studio import ui


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir',type=Path)
    args=parser.parse_args();ui.DATA=args.data_dir.resolve()
    app=QApplication([])
    app.setStyle('Fusion');app.setStyleSheet(ui.STYLE);ui.setup_fonts(app)
    window=ui.Window();window.tabs.setCurrentWidget(window.pipeline_panel);window.show();app.processEvents()
    window.pipeline_panel.show_retry_results();app.processEvents()
    dialog=window.pipeline_panel.retry_dialog
    table=dialog.findChild(QTableWidget)
    for row in range(table.rowCount()):
        if table.item(row,1).text()=='を得ても':
            table.selectRow(row);table.scrollToItem(table.item(max(0,row-1),0),QTableWidget.ScrollHint.PositionAtTop)
            break
    app.processEvents()
    output=ui.DATA/'source-review-preview.png'
    if not dialog.grab().save(str(output)): raise ValueError('Nie zapisano podglądu')
    print(output)
    dialog.close();window.close();app.processEvents()


if __name__=='__main__': main()

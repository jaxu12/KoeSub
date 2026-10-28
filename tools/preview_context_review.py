"""Render saved review/context results without running models."""
import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from studio import ui


def main():
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(ui.STYLE);ui.setup_fonts(app)
    target=Path('D:/models/.cache/verification-review-changes')
    ui.DATA=target
    window=ui.Window();window.show();panel=window.ai_review_panel
    panel.filter.setCurrentIndex(panel.filter.findData('accepted'));window.tabs.setCurrentWidget(panel)
    app.processEvents();window.grab().save(str(target/'automatic-review.png'))
    assert panel.table.rowCount()==2
    assert any(panel.table.item(i,3).text()!=panel.table.item(i,4).text() for i in range(panel.table.rowCount()))
    window.close()
    ui.DATA=Path('D:/models/.cache/verification-context-review')
    window=ui.Window();window.show();window.tabs.setCurrentWidget(window.pipeline_panel)
    app.processEvents();window.grab().save(str(target/'pipeline-context.png'))
    assert 'poprawiono EN: 4' in window.pipeline_panel.summary.text()
    window.resize(960,700);app.processEvents()
    assert window.centralWidget().verticalScrollBar().maximum()>0
    window.close()
    print('Saved context, before/after table, repair counter and small-window scroll: OK')


if __name__=='__main__': main()

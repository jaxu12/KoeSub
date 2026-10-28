"""Render review and split preview without modifying the user's current project."""
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from studio import ui
from studio.core import Project, Segment, Track
from studio.review import ReviewSettings
from studio.review_ui import SplitPreviewDialog


def main():
    folder = Path(__file__).resolve().parents[1]/'data'/'review-preview'
    ui.DATA = folder
    folder.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(ui.STYLE)
    ui.setup_fonts(app)
    window = ui.Window()
    window.project = Project(name='Review • przykłady kontrolne', duration=20000)
    segments = [Segment(1000, 3000, 'はい。', translation='Yes.'),
                Segment(4000, 10000, '今日は晴れです。明日は雨です。',
                        translation='The forecast says it is sunny today. Tomorrow the rain will return, so bring an umbrella.'),
                Segment(10040, 10600, '本当にそう思いますか。', translation='Do you really think that is going to work?'),
                Segment(10500, 14000, 'そうですね。', translation='That sounds right.'),
                Segment(18000, 22000, 'もう終わりです。', translation='This is the end.')]
    window.project.add_track(Track('Próbki JP / EN', segments))
    window.changed('review visual verification')
    window.tabs.setCurrentWidget(window.quality_page)
    window.show()
    app.processEvents()
    window.grab().save(str(folder/'review.png'))
    dialog = SplitPreviewDialog(window, segments[1], ReviewSettings())
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(folder/'split.png'))
    assert dialog.parts and all(s.translation for s in dialog.parts)
    dialog.close()
    window.tabs.setCurrentIndex(0)
    window.segments_table.selectRow(1)
    app.processEvents()
    window.grab().save(str(folder/'editor.png'))
    window.close()
    print('Review, split preview and editor renders:', folder)


if __name__ == '__main__':
    main()

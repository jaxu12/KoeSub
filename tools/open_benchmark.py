"""Open an isolated benchmark project in the native editor without changing the main project pointer."""
import argparse
from pathlib import Path

from PySide6.QtWidgets import QApplication
from studio import ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir', type=Path)
    parser.add_argument('--title', default='KoeSub • benchmark results')
    parser.add_argument('--source-review',action='store_true',help='Open the saved JP phrase comparison')
    parser.add_argument('--evaluation',type=Path,help='Open an offline source-quality listening study')
    parser.add_argument('--timing',action='store_true',help='Open final audio alignment changes')
    args = parser.parse_args()
    if not (args.data_dir / 'last_project.json').is_file():
        parser.error('Benchmark project does not exist')
    ui.DATA = args.data_dir
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(ui.STYLE)
    ui.setup_fonts(app)
    window = ui.Window()
    window.setWindowTitle(args.title)
    window.show()
    if args.source_review:
        window.tabs.setCurrentWidget(window.pipeline_panel)
        window.pipeline_panel.show_retry_results()
    if args.evaluation:
        window.evaluation_panel.load_study(args.evaluation)
        window.tabs.setCurrentWidget(window.evaluation_panel)
    if args.timing:
        window.tabs.setCurrentWidget(window.pipeline_panel)
        window.pipeline_panel.show_alignment_results()
    app.exec()


if __name__ == '__main__':
    main()

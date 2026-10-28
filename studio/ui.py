from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QProcess, QProcessEnvironment, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QFontDatabase, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from .adapters import (crisp_backends, crisp_command, validate_crisp_backend,
                       whisper_command, whisper_cpp_command)
from .core import (Project, ProjectStore, Segment, Track, atomic_text, compare_tracks, export_srt,
                   invalidate, issues_for, load_srt, merge_segments, now, parse_time, split_segment,
                   time_text, uid)
from .llm_worker import PROMPT
from .review import ReviewSettings, metrics, reflow_english, review_track
from .review_ui import ReviewOptionsDialog, SplitPreviewDialog
from .pipeline_ui import PipelinePanel
from .editor_tools import EditorTools
from .core import export_subtitles, load_subtitles
from .ai_review_ui import AIReviewPanel
from .evaluation_ui import EvaluationPanel
from .storage import (DATA, ROOT, Settings, audio_cache_path, audio_metadata, check_space,
                      discover_models, existing_parent, offline_env)

STYLE = """
QWidget { background: #12151d; color: #e6eaf3; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: #12151d; }
QLabel#title { font-size: 25px; font-weight: 700; }
QLabel#muted { color: #96a1b8; }
QLabel#badge { color: #91ebc9; background: #16362e; border-radius: 9px; padding: 6px 12px; }
QLabel#subtitle { background: #202633; color: #ffffff; font-size: 18px; padding: 12px; border-radius: 6px; }
QPushButton { background: #262d3e; border: 1px solid #353e54; padding: 8px 13px; border-radius: 6px; }
QPushButton:hover { background: #36405a; border-color: #8493bd; }
QPushButton:disabled { color: #626b7d; background: #1a1f2b; }
QPushButton#primary { background: #7864d9; border-color: #9987ee; color: white; font-weight: 600; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
 background: #1b2130; border: 1px solid #343d52; border-radius: 5px; padding: 6px; selection-background-color: #6551b7; }
QComboBox::drop-down { width: 22px; border: 0; }
QTabWidget::pane { border: 1px solid #30384b; border-radius: 6px; }
QTabBar::tab { background: #1a202d; color: #aab4cb; padding: 11px 19px; margin-right: 3px; }
QTabBar::tab:selected { background: #303047; color: #ddd4ff; border-bottom: 2px solid #9f8cf0; }
QTableWidget { background: #171c27; alternate-background-color: #1d2432; border: 1px solid #30384b; gridline-color: #2a3346; }
QTableWidget::item { padding: 6px; }
QTableWidget::item:selected { background: #393353; color: #ffffff; }
QHeaderView::section { background: #232a3a; color: #acb8d2; border: 0; padding: 9px; }
QGroupBox { border: 1px solid #30384b; border-radius: 7px; margin-top: 12px; padding: 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QProgressBar { border: 0; border-radius: 4px; background: #242c3e; text-align: center; min-height: 16px; }
QProgressBar::chunk { background: #7864d9; border-radius: 4px; }
QSplitter::handle { background: #252d3d; }
QMenuBar, QMenu { background: #1b2130; }
QStatusBar { color: #95a4be; }
QToolTip { background: #30384b; color: white; border: 1px solid #7e70b4; }
"""


def button(text, callback, primary=False):
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    b.clicked.connect(callback)
    return b


def label(text, muted=False):
    value = QLabel(text)
    value.setWordWrap(True)
    if muted:
        value.setObjectName("muted")
    return value


def table(headers):
    result = QTableWidget(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.setAlternatingRowColors(True)
    result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    result.verticalHeader().setVisible(False)
    result.horizontalHeader().setStretchLastSection(True)
    result.setWordWrap(True)
    return result


class ProcessRunner(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.process = None
        self.cancelled = False
        self.output = ""
        self.pending = b""
        self.timed_out=False
        self.elapsed_started=0
        self.elapsed_timer=QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self.tick)
        self.hide()

    def start(self, executable, args, callback, *, json_lines=False, cwd=None, timeout_seconds=None):
        if self.process is not None:
            raise ValueError("Inne zadanie jest już uruchomione.")
        process = self.process = QProcess(self)
        self.cancelled = False
        self.timed_out=False
        self.elapsed_started=time.monotonic()
        self.elapsed_timer.start();self.tick()
        self.output, self.pending = "", b""
        env = QProcessEnvironment.systemEnvironment()
        for key, value in offline_env().items():
            env.insert(key, value)
        if cwd:
            temp_folder = Path(self.owner.settings.cache_dir) / "runtime-temp" / Path(cwd).name
            temp_folder.mkdir(parents=True, exist_ok=True)
            env.insert("TEMP", str(temp_folder.resolve()))
            env.insert("TMP", str(temp_folder.resolve()))
        process.setProcessEnvironment(env)
        process.setWorkingDirectory(str(ROOT))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.owner.set_busy(True)

        def read():
            raw = bytes(process.readAllStandardOutput())
            self.output = (self.output + raw.decode("utf-8", errors="replace"))[-2_000_000:]
            if json_lines:
                self.pending += raw
                while b"\n" in self.pending:
                    line, self.pending = self.pending.split(b"\n", 1)
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeError):
                        self.owner.log(line.decode("utf-8", errors="replace"))
                    else:
                        self.owner.guarded(lambda: self.owner.worker_message(message))
            else:
                self.owner.log(raw.decode("utf-8", errors="replace").strip())

        finished = False

        def finish(code, status=None):
            nonlocal finished
            if finished:
                return
            finished = True
            read()
            output, cancelled = self.output, self.cancelled
            if self.timed_out:
                code=-124
                output+='\nPrzekroczono limit czasu procesu. Zapisane wyniki zachowano.'
                self.owner.worker_error=output.splitlines()[-1]
            self.elapsed_timer.stop();self.tick()
            self.process = None
            process.deleteLater()
            self.owner.set_busy(False)
            try:
                callback(code, output, cancelled)
            except Exception as exc:
                self.owner.fail(exc)

        def error(error):
            if error == QProcess.ProcessError.FailedToStart:
                self.output += "\n" + process.errorString()
                finish(-1)

        process.readyReadStandardOutput.connect(read)
        process.finished.connect(finish)
        process.errorOccurred.connect(error)
        self.owner.log("Uruchamiam: " + subprocess.list2cmdline([str(executable), *args]))
        process.start(str(executable), [str(a) for a in args])
        if timeout_seconds is not None:
            def timeout():
                if self.process is process:
                    self.timed_out=True
                    self.owner.log('Limit czasu procesu • zatrzymywanie drzewa zadania')
                    self.stop_process(process)
            QTimer.singleShot(max(1,round(timeout_seconds*1000)),timeout)

    def tick(self):
        elapsed=round(time.monotonic()-self.elapsed_started)
        self.owner.elapsed_label.setText(f'{elapsed//60}:{elapsed%60:02}')

    def cancel(self):
        process = self.process
        if process is None:
            return
        self.cancelled = True
        self.stop_process(process)

    def stop_process(self,process):
        pid = process.processId()
        if os.name == "nt" and pid:
            # Terminate this job's process tree, including a possible ASR child process.
            QProcess.startDetached("taskkill", ["/PID", str(pid), "/T", "/F"])
        process.terminate()
        QTimer.singleShot(2000, lambda: process.kill() if self.process is process else None)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KoeSub • local prototype")
        self.resize(1450, 1000)
        self.settings = Settings.load()
        self.project = Project()
        self.store = None
        self.undo_stack, self.redo_stack = [], []
        self.loading = False
        self.busy = False
        self.models = []
        self.groups = []
        self.job = None
        self.seek_end = None
        self.worker_error = ""
        self.backend_probe = None
        self.runner = ProcessRunner(self)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.build()
        self.editor_tools=EditorTools(self,DATA)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.tracksChanged.connect(self.media_tracks_changed)
        self.player.errorOccurred.connect(lambda *_: self.log("Odtwarzacz: " + self.player.errorString()))
        self.autosave = QTimer(self)
        self.autosave.setInterval(10000)
        self.autosave.timeout.connect(lambda: self.guarded(self.save))
        self.autosave.start()
        self.scan_models()
        if not Path(self.settings.whisper_exe).is_file() and Path(self.settings.crisp_exe).is_file():
            self.asr_engine.setCurrentIndex(2 if any(m.kind=="Whisper / GGML" for m in self.models) else 1)
        recent = DATA / "last_project.json"
        try:
            path = Path(json.loads(recent.read_text("utf-8"))["path"])
            self.open_project_path(path)
        except Exception as exc:
            if recent.exists():
                self.log("Nie otwarto ostatniego projektu: " + str(exc))
            self.refresh()
        self.statusBar().showMessage("Gotowy • modele lokalne • pobieranie wyłączone")

    def build(self):
        root = QWidget()
        viewport=QScrollArea()
        viewport.setWidgetResizable(True);viewport.setFrameShape(QFrame.Shape.NoFrame);viewport.setWidget(root)
        self.setCentralWidget(viewport)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 16, 22, 14)
        header = QHBoxLayout()
        title = label("KoeSub")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        badge = label("●  LOKALNIE  /  BEZ POBIERANIA")
        badge.setObjectName("badge")
        header.addWidget(badge)
        layout.addLayout(header)
        self.project_label = label("Nowy projekt • zaimportuj film lub napisy", True)
        layout.addWidget(self.project_label)
        toolbar = QHBoxLayout()
        actions = [("Nowy projekt", self.new_project), ("Otwórz projekt", self.open_project),
                   ("Zapisz jako…", self.save_as), ("Importuj film / audio", self.import_media),
                   ("Importuj SRT", self.import_srt), ("Przykład", self.demo)]
        self.mutating = []
        for text, callback in actions:
            b = button(text, callback)
            toolbar.addWidget(b)
            self.mutating.append(b)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.build_editor()
        self.build_asr()
        self.build_comparison()
        self.build_translation()
        self.build_models()
        self.build_quality_review()
        self.pipeline_panel = PipelinePanel(self)
        self.tabs.addTab(self.pipeline_panel, 'Zrób wszystko')
        self.ai_review_panel=AIReviewPanel(self)
        self.tabs.addTab(self.ai_review_panel,'Propozycje AI')
        self.evaluation_panel=EvaluationPanel(self)
        self.tabs.addTab(self.evaluation_panel,'Source quality')
        progress = QHBoxLayout()
        self.progress_label = label("Gotowy", True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.cancel_button = button("Anuluj zadanie", self.runner.cancel)
        self.cancel_button.setEnabled(False)
        progress.addWidget(self.progress_label, 2)
        progress.addWidget(self.progress, 2)
        self.elapsed_label=label('0:00',True)
        self.elapsed_label.setToolTip('Czas bieżącego procesu')
        progress.addWidget(self.elapsed_label)
        progress.addWidget(self.cancel_button)
        layout.addLayout(progress)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(1200)
        self.logs.setMaximumHeight(90)
        self.logs.setPlaceholderText("Logi przetwarzania i diagnostyka pojawią się tutaj.")
        layout.addWidget(self.logs)
        for name, shortcut, fn in (("Zapisz", "Ctrl+S", lambda:self.guarded(lambda:(self.editor_tools.commit(),self.save()))), ("Cofnij", "Ctrl+Z", self.undo),
                                   ("Ponów", "Ctrl+Y", self.redo)):
            action = QAction(name, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(fn)
            self.addAction(action)

    def build_editor(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        bar.addWidget(label("Ścieżka JP"))
        self.track_combo = QComboBox()
        self.track_combo.currentIndexChanged.connect(self.select_track)
        bar.addWidget(self.track_combo, 1)
        for text, callback in (("Cofnij", self.undo), ("Ponów", self.redo),
                               ("Eksport JP.srt", lambda: self.export(False)),
                               ("Eksport EN.srt", lambda: self.export(True))):
            b = button(text, callback)
            bar.addWidget(b)
            self.mutating.append(b)
        layout.addLayout(bar)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        media_layout = self.media_layout = QVBoxLayout(left)
        media_layout.setContentsMargins(0, 0, 8, 0)
        self.video = QVideoWidget()
        self.video.setMinimumSize(380, 160)
        self.video.setStyleSheet("background: black; border-radius: 6px;")
        self.player.setVideoOutput(self.video)
        media_layout.addWidget(self.video, 1)
        self.subtitle = label("Podgląd napisów • otwórz film i wybierz ścieżkę")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setMinimumHeight(50)
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        media_layout.addWidget(self.subtitle)
        playback = QHBoxLayout()
        playback.addWidget(button("▶ / Ⅱ", self.play_pause))
        playback.addWidget(button("Odsłuch napisu", self.play_segment))
        self.preview_en = QCheckBox("Podgląd EN")
        self.preview_en.toggled.connect(lambda: self.position_changed(self.player.position()))
        playback.addWidget(self.preview_en)
        playback.addStretch()
        media_layout.addLayout(playback)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.sliderMoved.connect(self.seek_to)
        media_layout.addWidget(self.seek)
        self.time_label = label("00:00:00,000 / 00:00:00,000", True)
        media_layout.addWidget(self.time_label)
        self.media_info = label("Film pozostaje w oryginalnej lokalizacji. Import nie kopiuje materiału.", True)
        media_layout.addWidget(self.media_info)
        media_layout.addWidget(label("Ścieżka dźwiękowa"))
        self.audio_combo = QComboBox()
        self.audio_combo.currentIndexChanged.connect(self.select_audio)
        media_layout.addWidget(self.audio_combo)
        splitter.addWidget(left)
        edit = QWidget()
        editor = self.editor_layout = QVBoxLayout(edit)
        editor.setContentsMargins(8, 0, 0, 0)
        self.segments_table = table(["#", "Początek", "Koniec", "Japoński", "Angielski", "Kontrola"])
        for i, width in enumerate((45, 120, 120, 220, 220, 180)):
            self.segments_table.setColumnWidth(i, width)
        self.segments_table.itemSelectionChanged.connect(self.selection_changed)
        self.segments_table.cellDoubleClicked.connect(lambda *_: self.play_segment())
        editor.addWidget(self.segments_table, 1)
        form = self.timestamp_layout = QHBoxLayout()
        self.start_edit, self.end_edit = QLineEdit(), QLineEdit()
        form.addWidget(label("Od"))
        form.addWidget(self.start_edit)
        form.addWidget(label("Do"))
        form.addWidget(self.end_edit)
        editor.addLayout(form)
        row = QHBoxLayout()
        self.jp_edit, self.en_edit = QTextEdit(), QTextEdit()
        self.jp_edit.setAcceptRichText(False)
        self.en_edit.setAcceptRichText(False)
        self.jp_edit.setPlaceholderText("Tekst japoński / źródłowy")
        self.en_edit.setPlaceholderText("Tłumaczenie angielskie")
        self.jp_edit.setMaximumHeight(75)
        self.en_edit.setMaximumHeight(75)
        row.addWidget(self.jp_edit)
        row.addWidget(self.en_edit)
        editor.addLayout(row)
        self.issue_label = label("Wybierz napis, aby edytować tekst i czasy.", True)
        self.issue_label.setTextFormat(Qt.TextFormat.PlainText)
        self.issue_label.setMaximumHeight(45)
        editor.addWidget(self.issue_label)
        controls = QHBoxLayout()
        for text, fn in (("Zastosuj", self.apply_edit), ("Dodaj", self.add_segment),
                         ("Usuń", self.delete_segments), ("Scal wybrane", self.merge_selected),
                         ("Podgląd podziału…", self.split_selected)):
            b = button(text, fn, text == "Zastosuj")
            controls.addWidget(b)
            self.mutating.append(b)
        editor.addLayout(controls)
        row = QHBoxLayout()
        row.addWidget(label("Edycja zapisuje się przy zmianie napisu lub Ctrl+Enter. Podział ma podgląd JP / EN. F1: skróty.", True), 1)
        row.addWidget(button('Review czasu / wierszy', lambda: self.tabs.setCurrentWidget(self.quality_page)))
        editor.addLayout(row)
        splitter.addWidget(edit)
        splitter.setSizes([420, 920])
        layout.addWidget(splitter, 1)
        self.tabs.addTab(page, "Edytor")

    def build_asr(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Transkrypcja z istniejących modeli", False))
        layout.addWidget(label("Silniki są uruchamiane ze wskazanego folderu narzędzi. Model ani film nie są kopiowane. "
                               "Wynik tworzy nową ścieżkę; wcześniejsze napisy pozostają dostępne.", True))
        box = QGroupBox("Ustawienia ASR • japoński")
        form = QFormLayout(box)
        self.asr_engine = QComboBox()
        self.asr_engine.addItems(["Whisper • Faster Whisper XXL (opcjonalny)", "Qwen3-ASR • CrispASR",
                                 "Whisper • whisper.cpp / GPU"])
        self.asr_engine.currentIndexChanged.connect(self.update_asr_models)
        self.asr_model = QComboBox()
        self.compute = QComboBox()
        self.compute.addItems(["float16", "int8_float16", "float32"])
        self.device = QComboBox()
        self.device.addItems(["cuda", "cpu"])
        self.crisp_device = QComboBox()
        self.crisp_device.addItems(["cuda", "vulkan", "cpu"])
        self.crisp_device.setCurrentText(self.settings.crisp_gpu_backend)
        self.vad = QCheckBox("Włącz VAD (lokalny model)")
        self.vad.setChecked(True)
        self.asr_start = QDoubleSpinBox()
        self.asr_start.setDecimals(3)
        self.asr_start.setRange(0, 86400)
        self.asr_start.setSuffix(" s")
        self.asr_length = QDoubleSpinBox()
        self.asr_length.setDecimals(3)
        self.asr_length.setRange(0, 86400)
        self.asr_length.setValue(60)
        self.asr_length.setSuffix(" s; 0 = do końca")
        form.addRow("Silnik", self.asr_engine)
        form.addRow("Lokalny model", self.asr_model)
        form.addRow("Faster Whisper XXL: precyzja", self.compute)
        form.addRow("Faster Whisper XXL: urządzenie", self.device)
        form.addRow("Qwen / whisper.cpp: GPU", self.crisp_device)
        self.backend_label = label("Backendy silnika: sprawdzanie…", True)
        form.addRow(self.backend_label)
        form.addRow("Wykrywanie mowy", self.vad)
        form.addRow("Początek testu / fragmentu", self.asr_start)
        form.addRow("Długość", self.asr_length)
        layout.addWidget(box)
        self.asr_button = button("Uruchom transkrypcję", self.start_asr, True)
        self.mutating.append(self.asr_button)
        layout.addWidget(self.asr_button)
        layout.addWidget(label("Na początek ustawiony jest test 60 sekund. Czasy wyniku zostaną przesunięte "
                               "do pozycji w oryginalnym filmie. Pełny film: długość 0. "
                               "Przed ASR zwolnij VRAM zajęty przez modele w LM Studio.", True))
        layout.addWidget(label("Faster Whisper XXL: standard_asia, beam=5, temperature=0, word timestamps, "
                               "condition_on_previous_text=False. Crisp: max-len=50, split-on-punct, "
                               "suppress-nst, frequency-penalty=0.2, lokalny aligner, jeśli dostępny. "
                               "Whisper.cpp: beam=5, podział przy interpunkcji, limit 32 znaków; "
                               "ten backend ma własne parametry segmentacji. "
                               "Dokładne polecenie i zgodność flag są zapisywane w logach.", True))
        layout.addStretch()
        self.tabs.addTab(page, "Transkrypcja")

    def build_comparison(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Porównaj dwie ścieżki JP. Grupy uwzględniają wspólny czas oraz podział 1:N i N:1. "
                               "Podobieństwo tekstu nie potwierdza poprawności względem nagrania.", True))
        row = QHBoxLayout()
        self.compare_a, self.compare_b = QComboBox(), QComboBox()
        row.addWidget(self.compare_a, 1)
        row.addWidget(self.compare_b, 1)
        row.addWidget(button("Porównaj", self.compare))
        layout.addLayout(row)
        self.comparison_table = table(["Czas", "Ścieżka A", "Ścieżka B", "Podobieństwo", "Typ"])
        self.comparison_table.setColumnWidth(0, 130)
        self.comparison_table.setColumnWidth(1, 380)
        self.comparison_table.setColumnWidth(2, 380)
        self.comparison_table.itemSelectionChanged.connect(self.comparison_selected)
        layout.addWidget(self.comparison_table, 1)
        self.comparison_detail = QPlainTextEdit()
        self.comparison_detail.setReadOnly(True)
        self.comparison_detail.setMaximumHeight(140)
        layout.addWidget(self.comparison_detail)
        row = QHBoxLayout()
        for text, fn in (("Odsłuch grupy", self.play_comparison), ("Wybierz A", lambda: self.choose_variant("a")),
                         ("Wybierz B", lambda: self.choose_variant("b")), ("Utwórz ścieżkę z wyboru", self.build_selected_track)):
            b = button(text, fn)
            row.addWidget(b)
            self.mutating.append(b)
        layout.addLayout(row)
        layout.addWidget(label("Każdą grupę wybierz ręcznie. Utworzenie ścieżki wymaga decyzji dla wszystkich grup.", True))
        self.tabs.addTab(page, "Porównanie ASR")

    def build_translation(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Tłumaczenie JA → EN"))
        row = QHBoxLayout()
        row.addWidget(label("Tryb tłumaczenia"))
        self.translation_backend = QComboBox()
        self.translation_backend.addItem("Wbudowany • lokalny GGUF", "embedded")
        self.translation_backend.addItem("LM Studio • opcjonalny serwer", "lmstudio")
        self.translation_backend.setCurrentIndex(max(0,self.translation_backend.findData(self.settings.translation_backend)))
        row.addWidget(self.translation_backend,1)
        layout.addLayout(row)
        self.native_panel = QGroupBox("Lokalny model • automatyczne ładowanie i zwalnianie pamięci")
        native = QVBoxLayout(self.native_panel)
        row = QHBoxLayout()
        self.local_llm_combo = QComboBox()
        row.addWidget(self.local_llm_combo,1)
        choose = button("Wybierz GGUF…",self.choose_local_llm)
        row.addWidget(choose)
        self.mutating.append(choose)
        native.addLayout(row)
        row = QHBoxLayout()
        self.llm_device_combo = QComboBox()
        self.llm_device_combo.addItem("GPU • Vulkan","vulkan")
        self.llm_device_combo.addItem("GPU • CUDA (NVIDIA)","cuda")
        self.llm_device_combo.addItem("CPU","cpu")
        self.llm_device_combo.setCurrentIndex(max(0,self.llm_device_combo.findData(self.settings.llm_device)))
        self.llm_batch = QSpinBox()
        self.llm_batch.setRange(1,12)
        self.llm_batch.setValue(self.settings.llm_batch_size)
        self.llm_context = QComboBox()
        for size in (2048,4096,8192):
            self.llm_context.addItem(str(size),size)
        self.llm_context.setCurrentIndex(max(0,self.llm_context.findData(self.settings.llm_context)))
        row.addWidget(label("Urządzenie"))
        row.addWidget(self.llm_device_combo)
        row.addWidget(label("Napisy w partii"))
        row.addWidget(self.llm_batch)
        row.addWidget(label("Kontekst (tokeny)"))
        row.addWidget(self.llm_context)
        native.addLayout(row)
        native.addWidget(label("Profil Qwen3 Instruct: model pracuje bezpośrednio w aplikacji. "
                               "Wyniki są zapisywane po każdej partii; anulowanie zwalnia pamięć modelu.",True))
        layout.addWidget(self.native_panel)
        self.server_panel = QGroupBox("Opcjonalne połączenie z LM Studio")
        server_layout = QVBoxLayout(self.server_panel)
        row = QHBoxLayout()
        self.lm_url = QLineEdit(self.settings.lm_url)
        self.llm_combo = QComboBox()
        self.llm_combo.setMinimumWidth(350)
        self.connect_button = button("Sprawdź serwer / modele", self.fetch_llm_models)
        self.mutating.append(self.connect_button)
        row.addWidget(self.lm_url)
        row.addWidget(self.connect_button)
        row.addWidget(self.llm_combo, 1)
        server_layout.addLayout(row)
        server_layout.addWidget(label("W tym trybie wybierasz model udostępniony przez uruchomione LM Studio. "
                                      "Dla Qwen3.5 wyłącz thinking w ustawieniach modelu. TranslateGemma wymaga osobnego adaptera.",True))
        layout.addWidget(self.server_panel)
        self.translation_backend.currentIndexChanged.connect(self.translation_mode_changed)
        self.translation_mode_changed()
        self.prompt = QPlainTextEdit(PROMPT)
        self.prompt.setFixedHeight(86)
        layout.addWidget(label("Instrukcja tłumaczenia (zapisywana z zadaniem)"))
        layout.addWidget(self.prompt)
        self.translation_button = button("Tłumacz / wznów aktywną ścieżkę", self.start_translation, True)
        self.mutating.append(self.translation_button)
        layout.addWidget(self.translation_button)
        layout.addWidget(label("Każda odpowiedź musi przejść walidację JSON i ID. Postęp jest zapisywany po każdym napisie. "
                               "Ręczne tłumaczenia pozostają zachowane. Zmiana JP oznacza wcześniejsze EN do kontroli. "
                               "Anulowanie pozostawia zakończone wyniki w projekcie. "
                               "Na początek zalecany jest Qwen3-4B-Instruct-2507.", True))
        self.review_table = table(["#", "JP", "EN", "Uwagi statyczne"])
        self.review_table.setMinimumHeight(140)
        self.review_table.setColumnWidth(0, 50)
        self.review_table.setColumnWidth(1, 340)
        self.review_table.setColumnWidth(2, 400)
        self.review_table.cellDoubleClicked.connect(self.review_selected)
        layout.addWidget(self.review_table, 1)
        layout.addWidget(label("Kontrola w prototypie: czasy, powtórzenia, możliwe odmowy, japońskie znaki w EN "
                               "i długość. Ocena znaczenia przez osobny model AI nie jest jeszcze zaimplementowana. "
                               "Dwuklik przenosi do edycji napisu.", True))
        self.tabs.addTab(page, "Tłumaczenie i kontrola")

    def build_models(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Modele i miejsce na dysku"))
        layout.addWidget(label("Modele są używane przez odwołanie do istniejącego pliku. "
                               "Aplikacja nie pobiera, nie kopiuje i nie usuwa modeli. "
                               "GGUF i modele CTranslate2 to różne formaty; wybór ASR pokazuje tylko zgodny typ.", True))
        row = QHBoxLayout()
        for text, fn in (("Ustawienia folderów", self.configure), ("Dodaj folder modeli", self.add_model_root),
                         ("Odśwież wykrywanie", self.scan_models), ("Otwórz cache", self.open_cache)):
            b = button(text, fn)
            row.addWidget(b)
            self.mutating.append(b)
        layout.addLayout(row)
        self.disk_label = label("", True)
        layout.addWidget(self.disk_label)
        self.models_table = table(["Model", "Typ", "Rozmiar", "Oryginalna lokalizacja"])
        self.models_table.setColumnWidth(0, 370)
        self.models_table.setColumnWidth(1, 180)
        self.models_table.setColumnWidth(2, 100)
        self.models_table.cellDoubleClicked.connect(self.open_model_folder)
        layout.addWidget(self.models_table, 1)
        self.paths_label = label("", True)
        self.paths_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.paths_label)
        self.tabs.addTab(page, "Modele i dysk")

    def log(self, text):
        if text:
            self.logs.appendPlainText(str(text))

    def build_quality_review(self):
        self.quality_page = QWidget()
        layout = QVBoxLayout(self.quality_page)
        layout.addWidget(label('Review czytelności • aktywna ścieżka'))
        layout.addWidget(label('Kontrola czasu wyświetlania, tempa czytania, wierszy, nakładania i przerw. '
                               'Podział tekstu wymaga sprawdzenia odsłuchem; nie potwierdza synchronizacji z mową.', True))
        repair_button=button('Sprawdź i popraw EN przez AI',self.review_and_repair)
        self.mutating.append(repair_button);layout.addWidget(repair_button)
        row = QHBoxLayout()
        self.quality_only_issues = QCheckBox('Tylko ostrzeżenia')
        self.quality_only_issues.setChecked(True)
        self.quality_only_issues.toggled.connect(self.refresh_quality)
        row.addWidget(self.quality_only_issues)
        self.quality_summary = label('', True)
        row.addWidget(self.quality_summary, 1)
        limits = button('Limity review…', self.configure_review)
        self.mutating.append(limits)
        row.addWidget(limits)
        layout.addLayout(row)
        self.quality_limits = label('', True)
        layout.addWidget(self.quality_limits)
        self.quality_table = table(['#', 'Czas', 'Czas trwania', 'JP zn./s', 'EN zn./s',
                                    'Wiersze JP / EN', 'Najdłuższy JP / EN', 'Uwagi'])
        for i, width in enumerate((45, 220, 100, 85, 85, 110, 135, 350)):
            self.quality_table.setColumnWidth(i, width)
        self.quality_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.quality_table.itemSelectionChanged.connect(self.quality_selection_changed)
        self.quality_table.cellDoubleClicked.connect(lambda *_: self.open_quality_editor())
        layout.addWidget(self.quality_table, 1)
        self.quality_detail = QPlainTextEdit()
        self.quality_detail.setReadOnly(True)
        self.quality_detail.setMaximumHeight(165)
        layout.addWidget(self.quality_detail)
        row = QHBoxLayout()
        for text, action in [('Otwórz w edytorze', self.open_quality_editor),
                             ('Odsłuch', self.play_quality), ('Podgląd podziału…', self.split_quality),
                             ('Podgląd wierszy EN…', self.reflow_quality)]:
            b = button(text, action)
            self.mutating.append(b)
            row.addWidget(b)
        layout.addLayout(row)
        self.tabs.addTab(self.quality_page, 'Review napisów')

    def review_and_repair(self):
        panel=self.ai_review_panel
        panel.auto_apply.setChecked(True)
        panel.mode.setCurrentIndex(panel.mode.findData('full'))
        self.tabs.setCurrentWidget(panel)
        panel.start()

    def refresh_quality(self):
        if not hasattr(self, 'quality_table'):
            return
        settings = ReviewSettings.load(self.project.review_settings)
        self.quality_rows = review_track(self.project.active, settings, self.project.duration)
        self.quality_limits.setText(f'EN ≤ {settings.en_cps:g} zn./s, {settings.en_line} znaków/wiersz • '
                                   f'JP ≤ {settings.jp_cps:g} zn./s, {settings.jp_line} znaków/wiersz • '
                                   f'maks. {settings.max_lines} wiersze • {settings.min_ms/1000:.3f}–{settings.max_ms/1000:g} s • '
                                   f'min. przerwa {settings.gap_ms} ms (styk 0 ms dozwolony)')
        flagged = sum(bool(r['issues']) for r in self.quality_rows)
        self.quality_summary.setText(f'{flagged} / {len(self.quality_rows)} napisów z ostrzeżeniami')
        selected = self.quality_index()
        self.quality_indices = [r['index'] for r in self.quality_rows
                                if r['issues'] or not self.quality_only_issues.isChecked()]
        self.quality_table.blockSignals(True)
        self.quality_table.clearContents()
        self.quality_table.setRowCount(len(self.quality_indices))
        for table_row, index in enumerate(self.quality_indices):
            r, s = self.quality_rows[index], self.project.active.segments[index]
            cps = lambda m: f'{m["cps"]:.1f}' if m['cps'] is not None else '—'
            values = [str(index+1), time_text(s.start)+' → '+time_text(s.end), f'{r["duration"]/1000:.3f} s',
                      cps(r['jp']), cps(r['en']) if s.translation else '—',
                      f'{r["jp"]["lines"]} / {r["en"]["lines"]}', f'{r["jp"]["line"]} / {r["en"]["line"]}',
                      '; '.join(r['issues']) or 'Bez ostrzeżeń']
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if r['issues'] and col == 7:
                    item.setForeground(QColor('#f0c780'))
                self.quality_table.setItem(table_row, col, item)
            self.quality_table.setRowHeight(table_row, 62)
        self.quality_table.blockSignals(False)
        if self.quality_indices:
            self.quality_table.selectRow(self.quality_indices.index(selected) if selected in self.quality_indices else 0)
        self.quality_selection_changed()

    def quality_index(self):
        row = self.quality_table.currentRow()
        indices = getattr(self, 'quality_indices', [])
        return indices[row] if 0 <= row < len(indices) else None

    def quality_selection_changed(self):
        index = self.quality_index()
        if index is None or not self.project.active or index >= len(self.project.active.segments):
            self.quality_detail.setPlainText('Brak napisów do wyświetlenia. Wyłącz filtr lub wybierz inną ścieżkę.')
            return
        r, s = self.quality_rows[index], self.project.active.segments[index]
        self.quality_detail.setPlainText(f'#{index+1} • JP: {s.text}\nEN: {s.translation or "Brak EN"}\n\n'
                                         + ('; '.join(r['issues']) or 'Bez ostrzeżeń') + '\n\n' + r['advice'])

    def configure_review(self):
        if self.busy:
            return
        self.guarded(self.editor_tools.commit)
        if self.editor_tools.dirty: return
        dialog = ReviewOptionsDialog(self, ReviewSettings.load(self.project.review_settings))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.checkpoint()
            self.project.review_settings = dialog.values()
            self.guarded(lambda: self.changed('review limits'))

    def open_quality_editor(self):
        index = self.quality_index()
        if index is not None:
            self.review_selected(index, 0)

    def play_quality(self):
        index = self.quality_index()
        if index is not None and self.project.active:
            s = self.project.active.segments[index]
            self.play_interval(s.start, s.end)

    def play_interval(self, start, end):
        if self.project.media:
            self.seek_end = end
            self.player.setPosition(start)
            self.player.play()

    def split_quality(self):
        index = self.quality_index()
        if index is not None:
            self.guarded(lambda: self.preview_split(index))

    def preview_split(self, index, from_editor=False):
        if self.busy or not self.project.active:
            return
        self.editor_tools.commit(False)
        segment = self.project.active.segments[index]
        dialog = SplitPreviewDialog(self, segment, ReviewSettings.load(self.project.review_settings),
                                    self.play_interval if self.project.media else None)
        if from_editor:
            before = self.jp_edit.toPlainText().encode('utf-16-le')[:self.jp_edit.textCursor().position()*2]
            position = len(before.decode('utf-16-le', errors='ignore'))
            if 0 < position < len(segment.text):
                dialog.jp_point.setValue(position)
            if segment.start < self.player.position() < segment.end:
                dialog.at.setValue(self.player.position()/1000)
        dialog.finished.connect(lambda *_: self.player.pause())
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.parts:
            self.checkpoint()
            self.invalidate_translations()
            self.project.active.segments[index:index+1] = dialog.parts
            self.changed('split subtitles with preview')

    def reflow_quality(self):
        if self.busy or not self.project.active:
            return
        self.guarded(self.editor_tools.commit)
        if self.editor_tools.dirty: return
        index = self.quality_index()
        if index is None:
            return
        segment = self.project.active.segments[index]
        if not segment.translation:
            self.log('Brak EN do podziału na wiersze.')
            return
        settings = ReviewSettings.load(self.project.review_settings)
        proposed = reflow_english(segment.translation, settings.en_line)
        dialog = QDialog(self)
        dialog.setWindowTitle('Podgląd wierszy EN • bez zmiany czasu')
        dialog.resize(750, 430)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(f'Limit: {settings.en_line} znaków/wiersz, {settings.max_lines} wiersze. '
                               'Zmieniają się wyłącznie białe znaki; tempo czytania pozostaje do kontroli.'))
        before = label('Przed:\n' + segment.translation)
        before.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(before)
        after = QPlainTextEdit(proposed)
        after.setReadOnly(True)
        layout.addWidget(after)
        m = metrics(proposed, segment.end-segment.start)
        layout.addWidget(label('Układ mieści się w limitach.' if m['line'] <= settings.en_line and m['lines'] <= settings.max_lines
                               else 'Tekst nadal przekracza limit. Rozważ skrócenie lub podział na osobne napisy.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and proposed != segment.translation:
            self.checkpoint()
            segment.translation, segment.translation_key, segment.status = proposed, '', 'manual'
            self.guarded(lambda: self.changed('reflow English lines'))

    def fail(self, error):
        message = str(error)
        self.log("BŁĄD: " + message)
        if self.job and self.job.get("status") == "running":
            self.job.update(status="failed", error=message, finished=now())
            try:
                self.save()
            except Exception as save_error:
                self.log("Nie zapisano błędu zadania: " + str(save_error))
        self.progress_label.setText("Błąd — szczegóły w logach")
        QMessageBox.warning(self, "Nie udało się wykonać operacji", message)

    def guarded(self, fn):
        try:
            return fn()
        except Exception as exc:
            self.fail(exc)

    def set_busy(self, value):
        self.busy = value
        self.cancel_button.setEnabled(value)
        for b in self.mutating:
            b.setEnabled(not value)
        for widget in (self.track_combo, self.asr_engine, self.asr_model, self.compute, self.device, self.crisp_device,
                       self.vad, self.asr_start, self.asr_length, self.jp_edit, self.en_edit,
                       self.start_edit, self.end_edit, self.compare_a, self.compare_b, self.lm_url,
                       self.prompt, self.llm_combo, self.audio_combo,self.translation_backend,
                       self.local_llm_combo,self.llm_device_combo,self.llm_batch,self.llm_context):
            widget.setEnabled(not value)
        if value:
            self.progress.setRange(0, 0)
        elif self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self.update_asr_controls()
        self.pipeline_panel.set_busy(value)
        self.ai_review_panel.set_busy(value)
        if hasattr(self,'editor_tools'):
            self.editor_tools.bookmark.setEnabled(not value)
            self.editor_tools.reviewed.setEnabled(not value)
            if value: self.editor_tools.wave.stop()
            else: self.editor_tools.wave.schedule()

    def checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.project.to_dict()))
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def changed(self, reason="edit"):
        self.save(reason=reason)
        self.groups = []
        self.comparison_table.setRowCount(0)
        self.comparison_detail.clear()
        self.refresh()

    def invalidate_translations(self):
        # Context influences translation. Any JP text/structure edit invalidates this track's review.
        if self.project.active:
            for s in self.project.active.segments:
                invalidate(s)

    def save(self, checked=False, reason="autosave"):
        try:
            if self.store is None:
                if not self.project.tracks and not self.project.media:
                    return
                self.store = ProjectStore(DATA / "projects" / uid() / "project.sqlite")
            check_space(self.store.path.parent, 256*1024, 0.02)
            self.store.save(self.project, reason)
            atomic_text(DATA / "last_project.json", json.dumps({"path": str(self.store.path.resolve())}))
            self.statusBar().showMessage("Zapisano: " + str(self.store.path), 5000)
        except Exception as exc:
            self.log("BŁĄD ZAPISU: " + str(exc))
            self.statusBar().showMessage("Błąd zapisu — " + str(exc))
            # Do not silently continue a costly job without durable results.
            if self.busy:
                self.runner.cancel()
            raise

    def new_project(self):
        if self.busy:
            return
        self.guarded(self._new_project)

    def _new_project(self):
        self.editor_tools.commit()
        self.save()
        self.player.stop()
        self.player.setSource(QUrl())
        self.project, self.store = Project(), None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.audio_combo.clear()
        self.changed()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Otwórz projekt", str(DATA), "Projekt SQLite (*.sqlite)")
        if path:
            self.guarded(lambda: self.open_project_path(Path(path)))

    def open_project_path(self, path):
        if self.busy: return
        self.editor_tools.commit()
        store = ProjectStore(path)
        project = store.load()
        self.save()
        self.player.stop()
        self.project, self.store = project, store
        interrupted = False
        for job in project.jobs:
            if job.get("status") == "running":
                job["status"] = "interrupted"
                interrupted = True
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.player.setSource(QUrl.fromLocalFile(project.media) if project.media else QUrl())
        self.audio_combo.clear()
        self.refresh()
        if interrupted:
            self.save(reason="recovered interrupted job")
            self.log("Przerwane zadanie: zachowano zapisane wyniki. Tłumaczenie można wznowić.")
        atomic_text(DATA / "last_project.json", json.dumps({"path": str(path.resolve())}))
        self.editor_tools.remember_project()
        self.editor_tools.wave.schedule()

    def save_as(self):
        if self.busy: return
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz projekt jako", "project.sqlite", "Projekt (*.sqlite)")
        if path:
            def operation():
                self.editor_tools.commit()
                destination = Path(path)
                new_store = ProjectStore(destination)
                new_store.save(self.project, "save as")
                self.store = new_store
                self.save()
                self.refresh()
                self.editor_tools.remember_project()
            self.guarded(operation)

    def demo(self):
        def operation():
            self._new_project()
            self.project.name = "Przykład • japoński dialog"
            self.project.add_track(load_srt(ROOT / "samples" / "japanese_a.srt"))
            self.project.add_track(load_srt(ROOT / "samples" / "japanese_b.srt"))
            self.project.active_track = self.project.tracks[0].id
            self.changed("demo")
        self.guarded(operation)

    def import_media(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importuj film lub audio", "",
                    "Media (*.mp4 *.mkv *.avi *.mov *.webm *.wav *.flac *.mp3 *.m4a *.ogg);;Wszystkie (*)")
        if path:
            self.guarded(lambda: self.import_media_path(Path(path)))

    def import_media_path(self, path: Path):
        if self.busy: return
        self.editor_tools.commit()
        if not path.is_file():
            raise ValueError("Nie znaleziono materiału.")
        if self.project.media and Path(self.project.media).resolve()!=path.resolve() and self.project.tracks:
            self._new_project()
        self.checkpoint()
        self.project.media = str(path.resolve())
        self.project.name = path.stem
        self.project.audio_track = 0
        self.project.duration = 0
        self.audio_combo.clear()
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self.changed("import media")
        if self.settings.ffmpeg and Path(self.settings.ffmpeg).is_file():
            self.progress_label.setText("Odczyt ścieżek audio…")
            self.runner.start(self.settings.ffmpeg, ["-hide_banner", "-i", str(path)], self.probed,timeout_seconds=30)

    def probed(self, code, output, cancelled):
        if code==-124: raise ValueError(output[-1800:])
        if cancelled:
            self.progress_label.setText("Anulowano odczyt metadanych")
            return
        duration, tracks = audio_metadata(output)
        self.project.duration = duration or self.project.duration
        self.audio_combo.blockSignals(True)
        self.audio_combo.clear()
        for i, name in enumerate(tracks):
            self.audio_combo.addItem(f"{i+1}: {name}", i)
        self.audio_combo.setCurrentIndex(min(self.project.audio_track, len(tracks)-1))
        self.audio_combo.blockSignals(False)
        self.media_info.setText(f"{Path(self.project.media).name}\n{time_text(self.project.duration)} • ścieżki audio: {len(tracks)}")
        if not tracks:
            self.log("Nie wykryto ścieżki audio. Sprawdź format i log FFmpeg.")
        self.progress_label.setText("Gotowy")
        self.save()

    def media_tracks_changed(self):
        # Qt's ordinal audio-track indices match FFmpeg's 0:a:N mapping.
        tracks = self.player.audioTracks()
        if tracks and self.audio_combo.count() != len(tracks):
            self.audio_combo.blockSignals(True)
            self.audio_combo.clear()
            for i, metadata in enumerate(tracks):
                title = metadata.stringValue(QMediaMetaData.Key.Title)
                language = metadata.stringValue(QMediaMetaData.Key.Language)
                self.audio_combo.addItem(f"{i+1}: {language} {title}".strip(), i)
            self.audio_combo.setCurrentIndex(min(self.project.audio_track, len(tracks)-1))
            self.audio_combo.blockSignals(False)
        if tracks:
            self.player.setActiveAudioTrack(min(self.project.audio_track, len(tracks)-1))

    def select_audio(self, index):
        if self.loading or index < 0 or self.busy:
            return
        self.project.audio_track = index
        self.player.setActiveAudioTrack(index)
        self.guarded(self.save)
        self.editor_tools.wave.schedule()

    def import_srt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importuj napisy • ASS/SSA: tekst i czasy", "", "Napisy (*.srt *.ass *.ssa)")
        if path:
            self.guarded(lambda:self.import_subtitle_path(Path(path)))

    def import_subtitle_path(self,path):
        if self.busy: return
        self.editor_tools.commit()
        try:
            track=load_subtitles(path)
        except UnicodeDecodeError:
            reply=QMessageBox.question(self,'Kodowanie','Plik nie jest UTF-8. Spróbować japońskiego CP932?')
            if reply!=QMessageBox.StandardButton.Yes: return
            track=load_subtitles(path,'cp932')
        self.checkpoint();self.project.add_track(track);self.changed('import subtitles')

    def export(self, english):
        if self.project.active is None:
            return
        if self.busy: return
        path, _ = QFileDialog.getSaveFileName(self, "Eksportuj napisy • ASS/SSA: styl domyślny", "English.srt" if english else "Japanese.srt", "SRT (*.srt);;ASS (*.ass);;SSA (*.ssa);;Tekst z czasami (*.txt)")
        if path:
            def operation():
                self.editor_tools.commit()
                export_subtitles(self.project.active, Path(path), english)
                self.log("Wyeksportowano i zapisano: " + path)
            self.guarded(operation)

    def refresh(self):
        self.loading = True
        self.project_label.setText(f"{self.project.name} • {len(self.project.tracks)} ścieżki • " +
                                  (str(self.store.path) if self.store else "projekt zapisuje się automatycznie po imporcie"))
        selected_a, selected_b = self.compare_a.currentData(), self.compare_b.currentData()
        for combo in (self.track_combo, self.compare_a, self.compare_b):
            combo.blockSignals(True)
            combo.clear()
            for track in self.project.tracks:
                combo.addItem(f"{track.name} ({len(track.segments)})", track.id)
        self.track_combo.setCurrentIndex(self.track_combo.findData(self.project.active_track))
        self.compare_a.setCurrentIndex(max(0, self.compare_a.findData(selected_a)))
        self.compare_b.setCurrentIndex(max(0, self.compare_b.findData(selected_b)) if selected_b else min(1, self.compare_b.count()-1))
        for combo in (self.track_combo, self.compare_a, self.compare_b):
            combo.blockSignals(False)
        segments = self.project.active.segments if self.project.active else []
        old_row = self.segments_table.currentRow()
        self.segments_table.blockSignals(True)
        self.segments_table.setRowCount(len(segments))
        self.review_table.setRowCount(len(segments))
        self.refresh_quality()
        for i, s in enumerate(segments):
            issues = self.quality_rows[i]['issues']
            status = ('★ ' if s.bookmarked else '')+('Sprawdzony • ' if s.review_status=='reviewed' else '')+("; ".join(issues) or ("EN zapisane" if s.translation else "Bez EN"))
            values = [str(i+1), time_text(s.start), time_text(s.end), s.text, s.translation, status]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if issues and j == 5:
                    item.setForeground(QColor("#f0c780"))
                self.segments_table.setItem(i, j, item)
            for j, value in enumerate((str(i+1), s.text, s.translation, status)):
                self.review_table.setItem(i, j, QTableWidgetItem(value))
            self.segments_table.setRowHeight(i, 53)
            self.review_table.setRowHeight(i, 55)
        self.segments_table.blockSignals(False)
        self.loading = False
        if segments:
            self.segments_table.selectRow(max(0, min(old_row, len(segments)-1)))
        else:
            self.jp_edit.clear()
            self.en_edit.clear()
            self.start_edit.clear()
            self.end_edit.clear()
        self.selection_changed()
        self.editor_tools.apply_filter()
        self.editor_tools.waveform.segments=segments
        self.editor_tools.waveform.update()
        self.editor_tools.sync_wave()
        self.position_changed(self.player.position())
        self.pipeline_panel.sync_project()
        self.ai_review_panel.refresh()

    def select_track(self, index):
        if self.loading or self.busy:
            return
        def work():
            self.editor_tools.commit(False)
            self.project.active_track = self.track_combo.currentData() or ""
            self.changed('select track')
        self.guarded(work)

    def selected_rows(self):
        return sorted({idx.row() for idx in self.segments_table.selectionModel().selectedRows()})

    def current_segment(self):
        row = self.segments_table.currentRow()
        track = self.project.active
        return track.segments[row] if track and 0 <= row < len(track.segments) else None

    def selection_changed(self):
        if self.loading:
            return
        if not self.editor_tools.before_selection(): return
        s = self.current_segment()
        if s:
            self.start_edit.setText(time_text(s.start))
            self.end_edit.setText(time_text(s.end))
            self.jp_edit.setPlainText(s.text)
            self.en_edit.setPlainText(s.translation)
            row = self.segments_table.currentRow()
            warnings = self.quality_rows[row]['issues'] if row < len(self.quality_rows) else issues_for(s)
            self.issue_label.setText(" • ".join(warnings) or "Brak ostrzeżeń reguł statycznych; znaczenie wymaga oceny.")
            self.issue_label.setToolTip(self.issue_label.text())
        self.editor_tools.loaded(s)

    def apply_edit(self):
        if self.busy:
            return
        self.guarded(self.editor_tools.commit)

    def add_segment(self):
        if self.busy:
            return
        def operation():
            self.editor_tools.commit(False)
            self.checkpoint()
            if self.project.active is None:
                self.project.add_track(Track("Ręczne napisy"))
            self.invalidate_translations()
            start = self.player.position()
            self.project.active.segments.append(Segment(start, start+2000, "Nowa wypowiedź"))
            self.project.active.segments.sort(key=lambda s: s.start)
            self.changed("add subtitle")
        self.guarded(operation)

    def delete_segments(self):
        if self.busy or not self.project.active:
            return
        rows = self.selected_rows()
        if rows:
            def work():
                self.editor_tools.commit(False)
                self.checkpoint()
                self.invalidate_translations()
                for row in reversed(rows): del self.project.active.segments[row]
                self.changed('delete subtitle')
            self.guarded(work)

    def merge_selected(self):
        if self.busy or not self.project.active:
            return
        def operation():
            self.editor_tools.commit(False)
            rows = self.selected_rows()
            if len(rows) < 2 or rows != list(range(rows[0], rows[-1]+1)):
                raise ValueError("Zaznacz co najmniej dwa sąsiednie wiersze (Shift / Ctrl).")
            result = merge_segments([self.project.active.segments[i] for i in rows])
            answer = QMessageBox.question(self, "Podgląd scalenia", f"{time_text(result.start)} → {time_text(result.end)}\n\n{result.text}\n\nScalić te napisy?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.checkpoint()
            self.invalidate_translations()
            self.project.active.segments[rows[0]:rows[-1]+1] = [result]
            self.changed("merge subtitles")
        self.guarded(operation)

    def split_selected(self):
        if self.busy or not self.project.active:
            return
        def operation():
            self.editor_tools.commit(False)
            s = self.current_segment()
            if s is None:
                return
            if (s.text, s.translation, time_text(s.start), time_text(s.end)) != (
                    self.jp_edit.toPlainText(), self.en_edit.toPlainText(), self.start_edit.text(), self.end_edit.text()):
                raise ValueError('Najpierw zatwierdź zmiany tekstu i czasu przyciskiem Zastosuj.')
            self.preview_split(self.segments_table.currentRow(), from_editor=True)
        self.guarded(operation)

    def undo(self):
        if not self.busy and self.editor_tools.dirty:
            for edit in (self.jp_edit,self.en_edit):
                if edit.hasFocus() and edit.document().isUndoAvailable(): edit.undo();return
            self.editor_tools.discard();return
        if self.busy or not self.undo_stack:
            return
        self.editor_tools.dirty=False
        self.redo_stack.append(self.project.to_dict())
        self.project = Project.from_dict(self.undo_stack.pop())
        self.sync_media()
        self.guarded(lambda: self.changed("undo"))

    def redo(self):
        if self.busy or not self.redo_stack:
            return
        self.editor_tools.dirty=False
        self.undo_stack.append(self.project.to_dict())
        self.project = Project.from_dict(self.redo_stack.pop())
        self.sync_media()
        self.guarded(lambda: self.changed("redo"))

    def sync_media(self):
        source = QUrl.fromLocalFile(self.project.media) if self.project.media else QUrl()
        if self.player.source() != source:
            self.player.setSource(source)
        self.player.setActiveAudioTrack(self.project.audio_track)

    def duration_changed(self, duration):
        self.seek.setRange(0, duration)
        self.project.duration = duration or self.project.duration

    def position_changed(self, position):
        self.editor_tools.waveform.set_position(position)
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.time_label.setText(f"{time_text(position)} / {time_text(self.player.duration() or self.project.duration)}")
        if self.seek_end is not None and position >= self.seek_end:
            self.player.pause()
            self.seek_end = None
        track = self.project.active
        active = [s for s in track.segments if s.start <= position < s.end] if track else []
        text = "\n".join((s.translation if self.preview_en.isChecked() else s.text) for s in active)
        self.subtitle.setText(text or ("Brak napisu w tym miejscu" if self.project.media else "Otwórz film, aby obejrzeć podgląd"))

    def seek_to(self, position):
        self.seek_end = None
        self.player.setPosition(position)

    def play_pause(self):
        self.seek_end = None
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def play_range(self, start, end):
        self.seek_end = end
        self.player.setPosition(max(0, start))
        self.player.play()

    def play_segment(self):
        s = self.current_segment()
        if s:
            self.play_range(s.start, s.end)

    def compare(self):
        def operation():
            a = next((t for t in self.project.tracks if t.id == self.compare_a.currentData()), None)
            b = next((t for t in self.project.tracks if t.id == self.compare_b.currentData()), None)
            if not a or not b or a.id == b.id:
                raise ValueError("Wybierz dwie różne ścieżki transkrypcji.")
            self.groups = compare_tracks(a, b)
            self.comparison_table.setRowCount(len(self.groups))
            for i, g in enumerate(self.groups):
                values = [time_text(g["start"]), "\n".join(s.text for s in g["a"]),
                          "\n".join(s.text for s in g["b"]), f"{g['similarity']:.0%}", g["kind"]]
                for j, value in enumerate(values):
                    self.comparison_table.setItem(i, j, QTableWidgetItem(value))
                self.comparison_table.setRowHeight(i, 65)
            if self.groups:
                self.comparison_table.selectRow(0)
        self.guarded(operation)

    def comparison_selected(self):
        row = self.comparison_table.currentRow()
        if 0 <= row < len(self.groups):
            g = self.groups[row]
            self.comparison_detail.setPlainText(
                f"{time_text(g['start'])} → {time_text(g['end'])} • "
                f"A: {len(g['a'])} segmentów / B: {len(g['b'])} segmentów\n\n"
                "A: " + "\n".join(s.text for s in g["a"]) + "\n\nB: " + "\n".join(s.text for s in g["b"]))

    def play_comparison(self):
        row = self.comparison_table.currentRow()
        if 0 <= row < len(self.groups):
            g = self.groups[row]
            self.play_range(g["start"], g["end"])

    def choose_variant(self, side):
        row = self.comparison_table.currentRow()
        if 0 <= row < len(self.groups):
            g = self.groups[row]
            g["choice"] = side
            self.comparison_table.item(row, 4).setText(g["kind"] + " • wybrano " + side.upper())

    def build_selected_track(self):
        def operation():
            self.editor_tools.commit(False)
            if not self.groups or any("choice" not in g for g in self.groups):
                raise ValueError("Wybierz wariant A lub B dla każdej grupy. Wybranie pustego wariantu pomija grupę.")
            selected = []
            for group in self.groups:
                for s in group[group["choice"]]:
                    result = copy.deepcopy(s)
                    result.id = uid()
                    result.parents = [s.id]
                    result.source = "manual comparison selection"
                    invalidate(result)
                    selected.append(result)
            self.checkpoint()
            self.project.add_track(Track("Wybrane dialogi", sorted(selected, key=lambda s: s.start),
                                         origin={"type": "comparison", "created": now(),
                                                 "tracks": [self.compare_a.currentData(), self.compare_b.currentData()]}))
            self.changed("manual comparison")
            self.tabs.setCurrentIndex(0)
        self.guarded(operation)

    def review_selected(self, row, column):
        self.tabs.setCurrentIndex(0)
        self.segments_table.selectRow(row)

    def scan_models(self):
        def operation():
            # Respect a setup script or a second settings editor without losing project edits.
            self.settings = Settings.load()
            self.crisp_device.setCurrentText(self.settings.crisp_gpu_backend)
            self.probe_crisp_backends()
            self.models = discover_models(self.settings.model_roots)
            for index,path in ((0,self.settings.whisper_exe),(1,self.settings.crisp_exe),(2,self.settings.crisp_exe)):
                item=self.asr_engine.model().item(index)
                if item:
                    item.setEnabled(bool(path and Path(path).is_file()))
                    item.setToolTip("Silnik jest dostępny" if path and Path(path).is_file() else "Brak silnika — wskaż plik w ustawieniach folderów")
            self.models_table.setRowCount(len(self.models))
            for i, model in enumerate(self.models):
                for j, value in enumerate((model.name, model.kind, f"{model.size/1024**3:.2f} GiB", model.path)):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.models_table.setItem(i, j, item)
                self.models_table.setRowHeight(i, 40)
            self.update_asr_models()
            selected = self.local_llm_combo.currentData() or self.settings.llm_model
            self.local_llm_combo.blockSignals(True)
            self.local_llm_combo.clear()
            for model in self.models:
                if model.kind=="LLM / GGUF":
                    self.local_llm_combo.addItem(f"{model.name} • {model.size/1024**3:.2f} GiB",model.path)
            self.local_llm_combo.setCurrentIndex(max(0,self.local_llm_combo.findData(selected)))
            self.local_llm_combo.blockSignals(False)
            self.pipeline_panel.refresh_models()
            self.ai_review_panel.refresh_models()
            free = check_space(Path(self.settings.cache_dir), 0, 0)
            self.disk_label.setText(f"Cache: {self.settings.cache_dir}\nWolne na tym dysku: {free/1024**3:.2f} GiB • "
                                    f"rezerwa: {self.settings.reserve_gib:.1f} GiB • znaleziono {len(self.models)} modeli • pobieranie wyłączone")
            self.paths_label.setText(f"Subtitle Edit: {self.settings.subtitle_edit or 'nie znaleziono'}\n"
                                     f"FFmpeg: {self.settings.ffmpeg or 'wskaż w ustawieniach'}\n"
                                     f"Skanowane foldery: {'; '.join(self.settings.model_roots)}")
        self.guarded(operation)

    def apply_crisp_backends(self, build_text):
        available = crisp_backends(build_text)
        if not available:
            raise ValueError('Silnik ASR nie zgłosił obsługiwanych backendów.')
        selected = self.crisp_device.currentText()
        for index in range(self.crisp_device.count()):
            backend = self.crisp_device.itemText(index)
            item = self.crisp_device.model().item(index)
            item.setEnabled(backend in available)
            item.setToolTip('Dostępny w tym silniku' if backend in available else 'Ten silnik nie zawiera tego backendu')
        self.backend_label.setText('Backendy tego silnika: ' + ', '.join(available) +
                                   '. VAD może pracować na CPU niezależnie od modelu ASR.')
        if selected not in available:
            selected = 'vulkan' if 'vulkan' in available else available[0]
            self.crisp_device.setCurrentText(selected)
            self.settings = Settings.load()
            self.settings.crisp_gpu_backend = selected
            self.settings.save()
            self.log(f'Poprawiono wybór backendu ASR na {selected}: poprzedni nie jest dostępny w tym silniku.')

    def probe_crisp_backends(self):
        if self.backend_probe is not None:
            self.backend_probe.kill()
        executable = self.settings.crisp_exe
        if not executable or not Path(executable).is_file():
            self.backend_label.setText('Nie wskazano silnika Qwen / whisper.cpp.')
            return
        process = self.backend_probe = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        def finished(code, *_):
            if self.backend_probe is process:
                self.backend_probe = None
                if code == 0:
                    try:
                        self.apply_crisp_backends(bytes(process.readAllStandardOutput()).decode('utf8', errors='replace'))
                    except ValueError as exc:
                        self.backend_label.setText(str(exc))
                else:
                    self.backend_label.setText('Nie odczytano backendów; zgodność zostanie sprawdzona przed zadaniem.')
            process.deleteLater()
        process.finished.connect(finished)
        QTimer.singleShot(5000, lambda: process.kill() if self.backend_probe is process else None)
        process.start(executable, ['--version'])

    def update_asr_models(self):
        if not hasattr(self, "asr_model"):
            return
        self.asr_model.clear()
        kind = {0:"Whisper / CTranslate2",1:"Qwen ASR",2:"Whisper / GGML"}[self.asr_engine.currentIndex()]
        for i, model in enumerate(self.models):
            if model.kind == kind:
                self.asr_model.addItem(f"{model.name} • {model.size/1024**3:.2f} GiB", i)
        if kind == "Whisper / CTranslate2":
            for index in range(self.asr_model.count()):
                if "large-v3-turbo" in self.asr_model.itemText(index):
                    self.asr_model.setCurrentIndex(index)
                    break
        self.update_asr_controls()

    def update_asr_controls(self):
        xxl = self.asr_engine.currentIndex() == 0
        self.compute.setEnabled(not self.busy and xxl)
        self.device.setEnabled(not self.busy and xxl)
        self.crisp_device.setEnabled(not self.busy and not xxl)

    def add_model_root(self):
        path = QFileDialog.getExistingDirectory(self, "Wskaż folder istniejących modeli (bez kopiowania)")
        if path and path not in self.settings.model_roots:
            def operation():
                self.settings.model_roots.append(path)
                self.settings.save()
                self.scan_models()
            self.guarded(operation)

    def configure(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Foldery i narzędzia")
        dialog.resize(850, 430)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Wskaż istniejące narzędzia i folder cache. Zmiana cache dotyczy nowych plików; "
                               "dotychczasowe pozostają w swojej lokalizacji. Modeli nie przenosimy.", True))
        form = QFormLayout()
        edits = {}
        fields = [("subtitle_edit", "Folder Subtitle Edit", True), ("cache_dir", "Folder cache audio", True),
                  ("ffmpeg", "FFmpeg.exe", False), ("whisper_exe", "Faster Whisper XXL.exe", False),
                  ("crisp_exe", "CrispASR.exe", False),
                  ("crisp_aligner", "Lokalny aligner CrispASR", False),
                  ("crisp_vad", "Lokalny VAD CrispASR", False),
                  ("llm_exe", "Wbudowany silnik llama-completion.exe", False)]
        for key, title, directory in fields:
            row = QHBoxLayout()
            edit = QLineEdit(getattr(self.settings, key))
            edits[key] = edit
            row.addWidget(edit)
            def browse(checked=False, edit=edit, directory=directory):
                value = QFileDialog.getExistingDirectory(dialog, "Wybierz folder", edit.text()) if directory else \
                    QFileDialog.getOpenFileName(dialog, "Wybierz plik", edit.text(), "Plik (*.exe *.gguf *.bin);;Wszystkie (*)")[0]
                if value:
                    edit.setText(value)
            row.addWidget(button("Wybierz…", browse))
            form.addRow(title, row)
        reserve = QDoubleSpinBox()
        reserve.setRange(0.5, 100)
        reserve.setValue(self.settings.reserve_gib)
        reserve.setSuffix(" GiB")
        form.addRow("Zapas wolnego miejsca", reserve)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            def operation():
                candidate = copy.deepcopy(self.settings)
                for key, edit in edits.items():
                    setattr(candidate, key, edit.text().strip())
                if not candidate.cache_dir:
                    raise ValueError("Wskaż folder cache.")
                if candidate.subtitle_edit and candidate.subtitle_edit != self.settings.subtitle_edit:
                    candidate.set_subtitle_edit(Path(candidate.subtitle_edit))
                for key in ("ffmpeg", "whisper_exe", "crisp_exe", "crisp_aligner", "crisp_vad", "llm_exe"):
                    value = getattr(candidate, key)
                    if value and not Path(value).is_file():
                        raise ValueError(f"Nie znaleziono programu: {value}")
                candidate.reserve_gib = reserve.value()
                check_space(Path(candidate.cache_dir), 0, candidate.reserve_gib)
                candidate.save()
                self.settings = candidate
                self.scan_models()
            self.guarded(operation)

    def open_cache(self):
        path = Path(self.settings.cache_dir)
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        else:
            self.log("Cache jest pusty. Folder powstanie przy pierwszej transkrypcji.")

    def open_model_folder(self, row, column):
        if 0 <= row < len(self.models):
            path = Path(self.models[row].path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))

    def start_asr(self):
        if self.busy:
            return
        self.guarded(self._start_asr)

    def _start_asr(self):
        self.editor_tools.commit()
        media = Path(self.project.media)
        if not self.project.media or not media.is_file():
            raise ValueError("Najpierw zaimportuj film lub audio.")
        index = self.asr_model.currentData()
        if index is None:
            raise ValueError("Nie znaleziono zgodnego lokalnego modelu. Dodaj folder w zakładce Modele i dysk.")
        if not Path(self.settings.ffmpeg).is_file():
            raise ValueError("Wskaż FFmpeg.exe w ustawieniach.")
        engine = self.asr_engine.currentIndex()
        executable = self.settings.whisper_exe if engine == 0 else self.settings.crisp_exe
        if not executable or not Path(executable).is_file():
            raise ValueError("Wskaż program ASR w ustawieniach folderów.")
        if engine in (1,2):
            self.settings.crisp_gpu_backend = self.crisp_device.currentText()
            self.settings.save()
        if engine == 0 and self.device.currentText() == "cpu" and self.compute.currentText() != "float32":
            raise ValueError("Dla CPU wybierz float32. Prototyp nie przełącza urządzenia automatycznie.")
        start = round(self.asr_start.value()*1000)
        length = round(self.asr_length.value()*1000)
        if self.project.duration and start >= self.project.duration:
            raise ValueError("Początek fragmentu wypada poza materiałem.")
        duration = min(length, max(0, self.project.duration-start)) if length and self.project.duration else \
            length or max(0, self.project.duration-start)
        if not duration:
            raise ValueError("Nieznana długość materiału. Ustaw długość testu w sekundach.")
        needed = (duration*32) + 20*1024**2  # PCM16 mono 16 kHz; plus output/headroom.
        check_space(Path(self.settings.cache_dir), needed, self.settings.reserve_gib)
        self.save()
        check_space(self.store.path.parent, 20*1024**2, self.settings.reserve_gib)
        self.checkpoint()
        job_dir = self.store.path.parent / "runs" / uid()
        job_dir.mkdir(parents=True)
        cache = audio_cache_path(self.settings, media, self.project.audio_track, start, length)
        cache.parent.mkdir(parents=True, exist_ok=True)
        self.job = {"id": job_dir.name, "type": "asr", "status": "running", "created": now(),
                    "engine": engine, "model": self.models[index].path, "start": start, "duration": duration,
                    "audio_track": self.project.audio_track, "cache": str(cache), "output": str(job_dir),
                    "executable": executable, "compute": self.compute.currentText(),
                    "device": self.device.currentText(), "vad": self.vad.isChecked(),
                    "crisp_gpu_backend": self.settings.crisp_gpu_backend}
        self.project.jobs.append(self.job)
        self.save(reason="ASR started")
        self.progress_label.setText("Sprawdzanie parametrów zainstalowanego ASR…")
        model = self.models[index]
        if engine in (1, 2):
            self.runner.start(executable, ['--version'],
                              lambda c, out, cancelled: self.asr_version_ready(c, out, cancelled, model), cwd=job_dir,timeout_seconds=30)
        else:
            self.runner.start(executable, ['--help'],
                              lambda c, out, cancelled: self.asr_help_ready(c, out, cancelled, model), cwd=job_dir,timeout_seconds=30)

    def asr_version_ready(self, code, output, cancelled, model):
        if cancelled:
            self.finish_cancelled()
            return
        atomic_text(Path(self.job['output'])/'engine-version.txt', output)
        if code != 0:
            raise ValueError('Nie udało się sprawdzić backendów silnika ASR.\n' + output[-2000:])
        validate_crisp_backend(self.job['crisp_gpu_backend'], output)
        self.runner.start(self.job['executable'], ['--help'],
                          lambda c, out, cancelled: self.asr_help_ready(c, out, cancelled, model), cwd=self.job['output'],timeout_seconds=30)

    def asr_help_ready(self, code, output, cancelled, model):
        if cancelled:
            self.finish_cancelled()
            return
        if code != 0:
            raise ValueError("Nie udało się odczytać parametrów ASR.\n" + output[-2000:])
        job = self.job
        folder = Path(job["output"])
        atomic_text(folder / "engine-help.txt", output)
        cache = Path(job["cache"])
        if job["engine"]==0:
            args=whisper_command(self.settings,model,cache,folder,job["compute"],job["device"],job["vad"],output)
        else:
            builder=crisp_command if job["engine"]==1 else whisper_cpp_command
            args=builder(self.settings,model,cache,folder,job["vad"],output)
        job["command"] = args
        atomic_text(folder / "configuration.json", json.dumps(job, ensure_ascii=False, indent=2))
        self.save()
        if cache.exists() and cache.stat().st_size > 44:
            self.log("Ponowne użycie audio z cache: " + str(cache))
            self.launch_asr()
            return
        partial = cache.with_suffix(".partial.wav")
        args = ["-hide_banner", "-nostdin", "-y", "-ss", str(job["start"]/1000), "-i", self.project.media,
                "-map", f"0:a:{job['audio_track']}", "-vn", "-t", str(job["duration"]/1000),
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(partial)]
        self.progress_label.setText("Wyodrębnianie wybranej ścieżki audio…")
        self.runner.start(self.settings.ffmpeg, args, lambda c, o, x: self.audio_ready(c, o, x, partial), cwd=folder,
                          timeout_seconds=max(120,job['duration']/1000))

    def audio_ready(self, code, output, cancelled, partial):
        if cancelled or code != 0:
            partial.unlink(missing_ok=True)
            if cancelled:
                self.finish_cancelled()
                return
            raise ValueError("FFmpeg nie wyodrębnił audio.\n" + output[-2500:])
        if not partial.exists() or partial.stat().st_size <= 44:
            raise ValueError("Wyodrębnione audio jest puste.")
        partial.replace(self.job["cache"])
        self.launch_asr()

    def launch_asr(self):
        self.progress_label.setText("Transkrypcja • szczegóły w logach…")
        self.runner.start(self.job["executable"], self.job["command"], self.asr_finished, cwd=self.job["output"],
                          timeout_seconds=max(300,self.job['duration']/1000*20))

    def asr_finished(self, code, output, cancelled):
        folder = Path(self.job["output"])
        atomic_text(folder / "engine.log", output)
        if cancelled:
            self.finish_cancelled()
            return
        if code != 0:
            raise ValueError("Silnik ASR zakończył się błędem. Sprawdź VRAM, biblioteki CUDA i log.\n" + output[-3500:])
        files = list(folder.glob("*.srt"))
        if not files:
            raise ValueError("Silnik nie zapisał pliku SRT. Surowe wyniki i log pozostają w folderze zadania.")
        track = load_srt(files[0])
        if not track.segments:
            raise ValueError("ASR nie zwrócił dialogów. Sprawdź audio, VAD i wybrany fragment.")
        for s in track.segments:
            s.start += self.job["start"]
            s.end += self.job["start"]
            s.source = self.job["id"]
        model_name = Path(self.job["model"]).name
        track.name = f"{model_name} • {len(self.project.tracks)+1}"
        track.origin = copy.deepcopy(self.job)
        self.project.add_track(track)
        suspicious = [s.id for s in track.segments if s.end <= s.start or s.start < 0]
        diagnostics = any(value in output.lower() for value in ("alignment collapse", "out of memory", "allocation failed"))
        self.job.update(status="needs_review" if suspicious or diagnostics else "completed", finished=now(), track_id=track.id,
                        invalid_segments=suspicious)
        self.changed("ASR result committed")
        self.progress.setValue(100)
        self.progress_label.setText(f"Zapisano {len(track.segments)} napisów" + (" • sprawdź ostrzeżenia" if suspicious or diagnostics else ""))
        self.tabs.setCurrentIndex(0)

    def finish_cancelled(self):
        if self.job:
            self.job.update(status="cancelled", finished=now())
        self.save(reason="cancelled")
        self.progress_label.setText("Anulowano • zapisane wyniki zachowane")

    def fetch_llm_models(self):
        if self.busy:
            return
        def operation():
            self.worker_error = ""
            self.run_worker({"action": "models", "url": self.lm_url.text()}, self.models_fetched)
        self.guarded(operation)

    def translation_mode_changed(self,index=0):
        local=self.translation_backend.currentData()=="embedded"
        self.native_panel.setVisible(local)
        self.server_panel.setVisible(not local)

    def choose_local_llm(self):
        path,_=QFileDialog.getOpenFileName(self,"Wybierz istniejący model GGUF",str(Path(self.settings.llm_model).parent),"Model GGUF (*.gguf)")
        if path:
            def operation():
                latest=Settings.load()
                parent=str(Path(path).resolve().parent)
                if parent not in latest.model_roots:
                    latest.model_roots.append(parent)
                latest.llm_model=str(Path(path).resolve())
                latest.save()
                self.settings=latest
                self.scan_models()
            self.guarded(operation)

    def run_worker(self, spec, callback):
        folder = Path(self.settings.cache_dir) / "worker"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uid()}.json"
        atomic_text(path, json.dumps(spec, ensure_ascii=False))
        def completed(code, output, cancelled):
            try:
                callback(code, output, cancelled)
            finally:
                path.unlink(missing_ok=True)
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        self.runner.start(str(executable), ["-m", "studio.llm_worker", str(path)], completed, json_lines=True)

    def models_fetched(self, code, output, cancelled):
        if cancelled:
            self.progress_label.setText("Anulowano połączenie")
        elif code != 0:
            raise ValueError("Nie można połączyć się z lokalnym LM Studio. Włącz serwer w zakładce Developer.\n" + self.worker_error)
        else:
            latest = Settings.load()
            latest.lm_url = self.lm_url.text().strip()
            latest.save()
            self.settings = latest
            self.progress_label.setText("LM Studio • lista modeli odczytana")
            self.pipeline_panel.refresh_models()
            self.ai_review_panel.refresh_models()

    def start_translation(self):
        if self.busy:
            return
        def operation():
            self.editor_tools.commit()
            if not self.project.active or not self.project.active.segments:
                raise ValueError("Najpierw wybierz ścieżkę z japońskimi napisami.")
            backend=self.translation_backend.currentData()
            local=backend=="embedded"
            model=self.local_llm_combo.currentData() if local else self.llm_combo.currentText()
            if not model:
                raise ValueError("Wybierz lokalny plik GGUF." if local else "Sprawdź serwer i wybierz model w LM Studio.")
            if "translategemma" in model.lower():
                raise ValueError("W prototypie wybierz model Qwen / Instruct. Adapter TranslateGemma nie jest jeszcze dostępny.")
            extra={}
            if local:
                extra={"backend":"embedded","executable":self.settings.llm_exe,"model_path":model,
                       "device":self.llm_device_combo.currentData(),"context_length":self.llm_context.currentData(),
                       "batch_size":self.llm_batch.value(),"cache_dir":self.settings.cache_dir,
                       "reserve_gib":self.settings.reserve_gib}
                from .embedded_llm import model_identity
                model_identity(extra)
            check_space(Path(self.settings.cache_dir),4*1024**2,self.settings.reserve_gib)
            latest=Settings.load()
            latest.translation_backend=backend
            if local:
                latest.llm_model=model
                latest.llm_device=extra["device"]
                latest.llm_context=extra["context_length"]
                latest.llm_batch_size=extra["batch_size"]
            latest.save()
            self.settings=latest
            self.checkpoint()
            self.worker_error = ""
            self.job = {"id": uid(), "type": "translation", "status": "running", "created": now(),
                        "track_id": self.project.active.id, "model": model,"backend":backend,
                        "prompt": self.prompt.toPlainText(), "url": self.lm_url.text().strip(), "errors": [],
                        "configuration":extra}
            self.project.jobs.append(self.job)
            self.save(reason="translation started")
            self.progress_label.setText("Tłumaczenie • zapis po każdym napisie…")
            self.run_worker({"action": "translate", "url": self.job["url"], "model": self.job["model"],
                             "prompt": self.job["prompt"],"job_id":self.job["id"],"backend":backend,
                             "project": self.project.to_dict(),**extra}, self.translation_finished)
        self.guarded(operation)

    def worker_message(self, message):
        kind = message.get("type")
        if kind and kind.startswith('pipeline_'):
            self.pipeline_panel.message(message)
        elif kind=='ai_review':
            self.ai_review_panel.message(message)
        elif kind=='film_context':
            self.ai_review_panel.context_message(message)
        elif kind=="phase":
            self.progress_label.setText(message["message"])
            self.log(message["message"])
        elif kind == "models":
            self.llm_combo.clear()
            self.llm_combo.addItems(message["models"])
            for i in range(self.llm_combo.count()):
                if "qwen3-4b-instruct" in self.llm_combo.itemText(i).lower():
                    self.llm_combo.setCurrentIndex(i)
                    break
        elif kind == "translation":
            track = next(t for t in self.project.tracks if t.id == self.job["track_id"])
            segment = next(s for s in track.segments if s.id == message["id"])
            segment.translation, segment.translation_key = message["translation"], message["key"]
            segment.status = "machine"
            self.save(reason="translation checkpoint")
            self.refresh()
        elif kind == "progress":
            self.progress.setRange(0, message["total"])
            self.progress.setValue(message["done"])
            title='AI Review' if self.job and self.job.get('type')=='ai_review' else 'Tłumaczenie'
            self.progress_label.setText(f"{title} {message['done']} / {message['total']}")
        elif kind == "segment_error":
            self.job["errors"].append(message)
            self.log("Błąd napisu " + message["id"] + ": " + message["message"])
            self.save()
        elif kind == "fatal":
            self.worker_error = message["message"]
            title={'pipeline':'Pipeline','ai_review':'AI Review'}.get(self.job.get('type') if self.job else '', 'Tłumaczenie')
            self.log(title+': '+self.worker_error)

    def translation_finished(self, code, output, cancelled):
        if cancelled:
            self.finish_cancelled()
            return
        if code != 0:
            raise ValueError(self.worker_error or output[-2000:])
        errors = len(self.job.get("errors", []))
        self.job.update(status="needs_review" if errors else "completed", finished=now())
        self.save(reason="translation finished")
        self.refresh()
        self.progress_label.setText("Zapisano tłumaczenie" + (f" • {errors} błędów do ponowienia" if errors else " • sprawdź kontrolę i eksportuj EN"))

    def closeEvent(self, event):
        if self.evaluation_panel.has_unsaved_reference():
            self.tabs.setCurrentWidget(self.evaluation_panel)
            self.evaluation_panel.status.setText('Save the reference audit or discard its edits before closing KoeSub.')
            event.ignore()
            return
        if self.busy:
            QMessageBox.information(self, "Trwa zadanie", "Anuluj bieżące zadanie przed zamknięciem aplikacji. Zapisane wyniki pozostaną w projekcie.")
            event.ignore()
            return
        try:
            self.editor_tools.commit()
            self.save()
            # Editors persist settings immediately. Closing an old window should not
            # overwrite newer model paths written by the setup script.
        except Exception as exc:
            self.fail(exc)
            event.ignore()
            return
        self.player.stop()
        self.evaluation_panel.player.stop()
        self.editor_tools.wave.closed=True
        self.editor_tools.wave.stop()
        event.accept()

    def dragEnterEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if self.editor_tools.accepts(paths): event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.guarded(lambda:self.editor_tools.import_paths(paths))
        event.acceptProposedAction()


def setup_fonts(app):
    # Explicit fallback also makes offscreen QA usable on Windows.
    if os.name == "nt":
        folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "meiryo.ttc"):
            path = folder / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 10))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KoeSub")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    setup_fonts(app)
    DATA.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(DATA / "studio.lock"))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(100):
        QMessageBox.information(None, "KoeSub", "KoeSub is already running. Switch to its window on the taskbar.")
        return 0
    try:
        window = Window()
    except Exception as exc:
        import traceback
        try:
            atomic_text(DATA / "startup-error.log", traceback.format_exc())
        except OSError:
            pass
        QMessageBox.critical(None, "KoeSub startup failed", str(exc))
        return 1
    def exception_hook(kind, value, tb):
        import traceback
        detail = "".join(traceback.format_exception(kind, value, tb))
        window.log(detail)
        try:
            atomic_text(DATA / "last-error.log", detail)
        except OSError:
            pass
        QMessageBox.warning(window, "Błąd aplikacji", str(value))
    sys.excepthook = exception_hook
    screen=app.primaryScreen()
    if screen:
        area=screen.availableGeometry()
        window.resize(min(window.width(),max(640,area.width()-32)),min(window.height(),max(480,area.height()-32)))
    window.show()
    return app.exec()

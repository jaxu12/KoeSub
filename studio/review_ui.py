from __future__ import annotations

from dataclasses import asdict

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QSpinBox, QVBoxLayout)

from .core import split_segment, time_text
from .review import ReviewSettings, metrics, split_proposal


class ReviewOptionsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle('Limity review • zapisane w projekcie')
        layout = QVBoxLayout(self)
        note = QLabel('Limity są wskazówkami do kontroli. Nie potwierdzają synchronizacji z mową.\n'
                      'CPS = znaki ze spacjami na sekundę, bez znaków nowego wiersza.\n'
                      'JP liczymy jako znaki Unicode, bez przeliczenia szerokości glifów.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.inputs = {}
        definitions = [('en_cps', 'EN: maks. znaków/s', 1, 100), ('jp_cps', 'JP: maks. znaków/s', 1, 100),
                       ('en_line', 'EN: znaki w wierszu', 1, 200), ('jp_line', 'JP: znaki w wierszu', 1, 200),
                       ('max_lines', 'Maksymalna liczba wierszy', 1, 10), ('min_ms', 'Min. czas (ms)', 1, 30000),
                       ('max_ms', 'Maks. czas (ms)', 1, 60000), ('gap_ms', 'Minimalna przerwa (ms)', 0, 2000)]
        for key, title, minimum, maximum in definitions:
            widget = QDoubleSpinBox() if key.endswith('cps') else QSpinBox()
            widget.setRange(minimum, maximum)
            widget.setValue(getattr(settings, key))
            self.inputs[key] = widget
            form.addRow(title, widget)
        layout.addLayout(form)
        self.error = QLabel()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return asdict(ReviewSettings.load({key: widget.value() for key, widget in self.inputs.items()}))

    def validate(self):
        try:
            self.values()
        except ValueError as exc:
            self.error.setText(str(exc))
        else:
            self.accept()


class SplitPreviewDialog(QDialog):
    def __init__(self, parent, segment, settings, play=None):
        super().__init__(parent)
        self.segment, self.settings, self.parts = segment, settings, None
        self.setWindowTitle('Podgląd podziału • JP i EN')
        self.resize(980, 700)
        layout = QVBoxLayout(self)
        note = QLabel('Propozycja jest oparta na tekście, nie na wyrównaniu do audio. '
                      'Ustaw punkty JP i EN przy tej samej wypowiedzi i sprawdź czas odsłuchem. '
                      'Sam podział nie zmniejsza liczby znaków na sekundę. EN zostanie zachowane do kontroli.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.jp_text, self.en_text = QPlainTextEdit(segment.text), QPlainTextEdit(segment.translation)
        for title, edit, language in [('JP', self.jp_text, 'jp'), ('EN', self.en_text, 'en')]:
            column = QVBoxLayout()
            column.addWidget(QLabel(title + ' • kliknij miejsce podziału'))
            edit.setReadOnly(True)
            column.addWidget(edit)
            choose = QPushButton('Ustaw punkt w kursorze ' + title)
            choose.clicked.connect(lambda checked=False, lang=language, editor=edit: self.set_cursor_point(lang, editor))
            choose.setEnabled(bool(segment.translation) if language == 'en' else True)
            column.addWidget(choose)
            row.addLayout(column)
        layout.addLayout(row, 1)
        form = QFormLayout()
        self.jp_point, self.en_point = QSpinBox(), QSpinBox()
        self.jp_point.setRange(1, max(1, len(segment.text)-1))
        self.en_point.setRange(1, max(1, len(segment.translation)-1))
        self.en_point.setEnabled(bool(segment.translation))
        self.at = QDoubleSpinBox()
        self.at.setDecimals(3)
        self.at.setRange((segment.start+1)/1000, max(segment.start+1, segment.end-1)/1000)
        self.at.setSuffix(' s • pozycja w filmie')
        proposal = split_proposal(segment, settings)
        jp, en, at = proposal or (max(1, len(segment.text)//2), max(1, len(segment.translation)//2),
                                 (segment.start+segment.end)//2)
        self.jp_point.setValue(jp)
        self.en_point.setValue(en or 1)
        self.at.setValue(at/1000)
        form.addRow('Podział JP po znaku', self.jp_point)
        form.addRow('Podział EN po znaku', self.en_point)
        form.addRow('Czas podziału', self.at)
        layout.addLayout(form)
        if play:
            row = QHBoxLayout()
            for title, which in [('Odsłuch całości', 'all'), ('Odsłuch części 1', 'first'), ('Odsłuch części 2', 'second')]:
                b = QPushButton(title)
                def listen(checked=False, part=which):
                    at = round(self.at.value()*1000)
                    play(segment.start if part != 'second' else at, segment.end if part != 'first' else at)
                b.clicked.connect(listen)
                row.addWidget(b)
            layout.addLayout(row)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText('Zastosuj podział')
        self.apply_button.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for control in (self.jp_point, self.en_point, self.at):
            control.valueChanged.connect(self.update_preview)
        self.update_preview()

    def set_cursor_point(self, language, editor):
        # Qt positions use UTF-16 units; convert explicitly for Python's Unicode indexes.
        before = editor.toPlainText().encode('utf-16-le')[:editor.textCursor().position()*2]
        position = len(before.decode('utf-16-le', errors='ignore'))
        (self.jp_point if language == 'jp' else self.en_point).setValue(position)

    def update_preview(self):
        try:
            parts = split_segment(self.segment, self.jp_point.value(), round(self.at.value()*1000),
                                  self.en_point.value() if self.segment.translation else None)
        except ValueError as exc:
            self.parts = None
            self.preview.setPlainText(str(exc))
            self.apply_button.setEnabled(False)
            return
        self.parts = parts
        lines = []
        for i, part in enumerate(parts, 1):
            duration = part.end-part.start
            jp, en = metrics(part.text, duration), metrics(part.translation, duration)
            warnings = []
            if duration < self.settings.min_ms:
                warnings.append('krótszy niż minimum')
            for lang, m, limit, width in [('JP', jp, self.settings.jp_cps, self.settings.jp_line),
                                           ('EN', en, self.settings.en_cps, self.settings.en_line)]:
                if m['cps'] > limit:
                    warnings.append(lang + ' za szybko')
                if m['line'] > width:
                    warnings.append(f'{lang} wiersz {m["line"]} > {width} znaków')
                if m['lines'] > self.settings.max_lines:
                    warnings.append(f'{lang} za dużo wierszy')
            lines.append(f'{i}. {time_text(part.start)} → {time_text(part.end)} • {duration/1000:.3f} s\n'
                         f'JP {jp["cps"]:.1f} zn./s: {part.text}\nEN {en["cps"]:.1f} zn./s: {part.translation}\n'
                         + ('Uwagi: ' + ', '.join(warnings) if warnings else 'Tempo, wiersze i minimalny czas: OK'))
        self.preview.setPlainText('\n\n'.join(lines))
        self.apply_button.setEnabled(True)

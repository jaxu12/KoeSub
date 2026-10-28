from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QDialogButtonBox,QHBoxLayout,QLabel,
                               QPlainTextEdit,QPushButton,QSpinBox,QTableWidget,QTableWidgetItem,QVBoxLayout)
from .core import time_text
from .editing import propose_cleanup,shift_track


class CleanupDialog(QDialog):
    def __init__(self,parent,track,rules,duration):
        super().__init__(parent)
        self.track,self.rules,self.duration=track,rules,duration
        self.result_track=None
        self.setWindowTitle('Typowe poprawki • podgląd bez zmiany oryginału')
        self.resize(920,600)
        layout=QVBoxLayout(self)
        note=QLabel('Korekty czasów są techniczne, nie potwierdzają zgodności z audio. '
                    'Niepewne przypadki pozostają bez zmian. Całą operację można cofnąć.')
        note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout()
        self.whitespace=QCheckBox('Białe znaki / końce linii');self.whitespace.setChecked(True)
        self.merge=QCheckBox('Scal mikronapisy');self.timing=QCheckBox('Drobne korekty czasów')
        for widget in (self.whitespace,self.merge,self.timing):
            row.addWidget(widget);widget.toggled.connect(self.preview)
        layout.addLayout(row)
        self.table=QTableWidget(0,3)
        self.table.setHorizontalHeaderLabels(['Przed','Po','Tekst JP / EN'])
        self.table.setColumnWidth(0,230);self.table.setColumnWidth(1,230)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table,1)
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);self.summary.setMaximumHeight(150)
        layout.addWidget(self.summary)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        self.apply_button=buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText('Zastosuj widoczne poprawki')
        self.apply_button.clicked.connect(self.accept);buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.preview()

    def preview(self):
        result,changes,unresolved=propose_cleanup(self.track,self.rules,self.duration,
                          self.whitespace.isChecked(),self.merge.isChecked(),self.timing.isChecked())
        self.result_track=result
        old={s.id:s for s in self.track.segments}
        rows=[]
        for s in result.segments:
            original=old.get(s.id)
            if original and (original.start,original.end,original.text,original.translation)==(s.start,s.end,s.text,s.translation):
                continue
            sources=[original] if original else [old[k] for k in s.parents if k in old]
            before=' / '.join(time_text(v.start)+' → '+time_text(v.end) for v in sources)
            rows.append((before,time_text(s.start)+' → '+time_text(s.end),s.text+'\n'+s.translation))
        self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):
                item=QTableWidgetItem(value);item.setToolTip(value);self.table.setItem(i,j,item)
            self.table.setRowHeight(i,70)
        self.summary.setPlainText('\n'.join(changes+['\nDo ręcznej kontroli:']+unresolved) if changes or unresolved else 'Brak zmian do zaproponowania.')
        self.apply_button.setEnabled(bool(changes))


class ShiftDialog(QDialog):
    def __init__(self,parent,track,rows,position):
        super().__init__(parent)
        self.track,self.rows,self.result_track=track,rows,None
        self.setWindowTitle('Przesuń czasy • podgląd');self.resize(800,480)
        layout=QVBoxLayout(self)
        row=QHBoxLayout()
        self.scope=QComboBox();self.scope.addItem('Cała aktywna ścieżka','all')
        if rows:
            self.scope.addItem(f'Zaznaczone napisy ({len(rows)})','selected')
            self.scope.setCurrentIndex(1)
        self.offset=QSpinBox();self.offset.setRange(-86400000,86400000);self.offset.setSuffix(' ms')
        row.addWidget(self.scope);row.addWidget(self.offset)
        align=QPushButton('Bieżący napis na pozycji odtwarzacza')
        align.clicked.connect(lambda:self.offset.setValue(position-track.segments[rows[0] if rows else 0].start))
        row.addWidget(align);layout.addLayout(row)
        self.preview_text=QPlainTextEdit();self.preview_text.setReadOnly(True);layout.addWidget(self.preview_text)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        self.apply_button=buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.clicked.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.scope.currentIndexChanged.connect(self.preview);self.offset.valueChanged.connect(self.preview)
        self.preview()

    def preview(self):
        try:
            self.result_track=shift_track(self.track,self.offset.value(),self.rows if self.scope.currentData()=='selected' else None)
            lines=[f'#{i+1}: {time_text(a.start)} → {time_text(b.start)}  |  {time_text(a.end)} → {time_text(b.end)}'
                   for i,(a,b) in enumerate(zip(self.track.segments,self.result_track.segments)) if (a.start,a.end)!=(b.start,b.end)]
            self.preview_text.setPlainText('\n'.join(lines) or 'Ustaw dodatnie lub ujemne przesunięcie. Tekst i czas trwania pozostaną zachowane.')
            self.apply_button.setEnabled(bool(lines))
        except ValueError as exc:
            self.result_track=None;self.preview_text.setPlainText(str(exc));self.apply_button.setEnabled(False)

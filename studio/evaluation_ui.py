"""Human listening workbench for offline source-quality studies."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QUrl,Qt
from PySide6.QtMultimedia import QAudioOutput,QMediaPlayer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFileDialog,QComboBox,
    QLineEdit,QCheckBox,QPlainTextEdit,QSplitter,QTabWidget,QTableWidget,QTableWidgetItem,
    QDialog,QDialogButtonBox,QFormLayout,QHeaderView)

from .source_evaluation import (CATEGORIES,SEVERITIES,VARIANTS,StudyStore,create_study,audit_reference,
    record_rating,quality_report,write_reports,check_audio)
from .evaluation_text import score_text


def label(text):
    widget=QLabel(text);widget.setWordWrap(True);widget.setTextFormat(Qt.TextFormat.PlainText);return widget


class ErrorEventDialog(QDialog):
    def __init__(self,parent,reference_quote,hypothesis_quote):
        super().__init__(parent);self.setWindowTitle('Classify an audio error');self.resize(700,360)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.category=QComboBox()
        for key in CATEGORIES:self.category.addItem(key.title(),key)
        self.severity=QComboBox();self.severity.addItems(SEVERITIES);self.severity.setCurrentText('major')
        self.reference=QLineEdit(reference_quote);self.hypothesis=QLineEdit(hypothesis_quote);self.note=QLineEdit()
        self.definition=label(CATEGORIES[self.category.currentData()]);self.category.currentIndexChanged.connect(lambda:self.definition.setText(CATEGORIES[self.category.currentData()]))
        for title,widget in [('Primary category',self.category),('Severity',self.severity),('Exact reference quote',self.reference),
                             ('Exact hypothesis quote',self.hypothesis),('Why / what you heard',self.note)]:form.addRow(title,widget)
        layout.addWidget(self.definition)
        layout.addWidget(label('Use one primary category per error. Spelling-only differences belong to Orthography, not Meaning. Quotes identify evidence in this clip.'))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def values(self):
        return {'category':self.category.currentData(),'severity':self.severity.currentText(),
                'reference_quote':self.reference.text(),'hypothesis_quote':self.hypothesis.text(),'note':self.note.text()}


class EvaluationPanel(QWidget):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.study=None;self.store=None;self.loading=False
        layout=QVBoxLayout(self)
        layout.addWidget(label('Source quality • reference listening and baseline / after-review comparison'))
        layout.addWidget(label('CER measures text differences. Omissions, additions, names and meaning are counted only after explicit listening review with an audited reference. This study never edits your subtitle project.'))
        row=QHBoxLayout();self.create_button=QPushButton('Create from benchmark results');self.open_button=QPushButton('Open study')
        self.export_button=QPushButton('Export quality report')
        for button in (self.create_button,self.open_button,self.export_button):row.addWidget(button)
        layout.addLayout(row);self.summary=label('No study loaded. Use a reference index and completed pipeline results, or open a saved quality study.');layout.addWidget(self.summary)
        row=QHBoxLayout();self.cases=QComboBox();self.reviewer=QLineEdit();self.reviewer.setPlaceholderText('Reviewer name or ID')
        self.play=QPushButton('Listen to clip');self.stop=QPushButton('Stop')
        row.addWidget(self.cases,2);row.addWidget(self.reviewer,1);row.addWidget(self.play);row.addWidget(self.stop);layout.addLayout(row)
        split=QSplitter();layout.addWidget(split,3)
        reference_page=QWidget();left=QVBoxLayout(reference_page);left.addWidget(label('Reference • corrections are saved only in this study'))
        self.reference=QPlainTextEdit();left.addWidget(self.reference,1)
        self.reference_note=QLineEdit();self.reference_note.setPlaceholderText('Listening evidence / correction note');left.addWidget(self.reference_note)
        self.reference_listened=QCheckBox('I checked this reference against the audio, not against ASR');left.addWidget(self.reference_listened)
        self.mask_hypotheses=QCheckBox('Hide ASR during an unverified reference audit');self.mask_hypotheses.setChecked(True);left.addWidget(self.mask_hypotheses)
        row=QHBoxLayout();self.save_reference=QPushButton('Save reference audit');self.discard_reference=QPushButton('Discard reference edits')
        row.addWidget(self.save_reference);row.addWidget(self.discard_reference);left.addLayout(row);split.addWidget(reference_page)
        right=QWidget();right_layout=QVBoxLayout(right);self.variants=QTabWidget();self.hypotheses={}
        for key,title in [('baseline','Baseline ASR'),('review','After review')]:
            text=QPlainTextEdit();text.setReadOnly(True);self.hypotheses[key]=text;self.variants.addTab(text,title)
        right_layout.addWidget(self.variants,1);self.rating_listened=QCheckBox('I listened and completed this variant’s error review');right_layout.addWidget(self.rating_listened)
        right_layout.addWidget(label('Complete with no events to record a checked, error-free clip. Adding or removing an event saves a draft until you attest listening again.'))
        self.save_rating=QPushButton('Save variant assessment');right_layout.addWidget(self.save_rating);split.addWidget(right)
        split.setSizes([500,500])
        self.events=QTableWidget(0,5);self.events.setHorizontalHeaderLabels(['Category','Severity','Reference quote','Hypothesis quote','Explanation'])
        self.events.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.events.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(self.events,2)
        row=QHBoxLayout();self.add_event=QPushButton('Add error from selected text');self.remove_event=QPushButton('Remove selected error')
        row.addWidget(self.add_event);row.addWidget(self.remove_event);layout.addLayout(row)
        self.status=label('References start unverified, even when imported from an existing caption dataset.');layout.addWidget(self.status)
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.audio.setVolume(.8);self.player.setAudioOutput(self.audio)
        self.player.errorOccurred.connect(lambda *_:self.status.setText('Playback error: '+self.player.errorString()))
        self.create_button.clicked.connect(lambda:self.guard(self.create_dialog))
        self.open_button.clicked.connect(lambda:self.guard(self.open_dialog))
        self.export_button.clicked.connect(lambda:self.guard(self.export_dialog))
        self.cases.currentIndexChanged.connect(self.render_case);self.variants.currentChanged.connect(self.render_variant)
        self.reference.textChanged.connect(self.reference_edited)
        self.reference_note.textChanged.connect(self.reference_dirty)
        self.reference_listened.toggled.connect(self.reference_dirty)
        self.mask_hypotheses.toggled.connect(self.render_variant)
        self.discard_reference.clicked.connect(self.render_case)
        self.save_reference.clicked.connect(lambda:self.guard(self.apply_reference))
        self.save_rating.clicked.connect(lambda:self.guard(self.apply_rating))
        self.add_event.clicked.connect(lambda:self.guard(self.add_event_dialog))
        self.remove_event.clicked.connect(lambda:self.guard(self.delete_event))
        self.play.clicked.connect(lambda:self.guard(self.play_clip));self.stop.clicked.connect(self.player.stop)
        self.enable_controls()

    def guard(self,operation):
        try:operation()
        except (ValueError,OSError,KeyError,TypeError) as exc:self.status.setText(str(exc))

    def case(self):
        return self.study['cases'][self.cases.currentIndex()]

    def variant(self):return VARIANTS[self.variants.currentIndex()]

    def enable_controls(self):
        loaded=self.study is not None
        dirty=self.has_unsaved_reference()
        for widget in (self.cases,self.play,self.export_button,self.save_reference,self.reference,self.reference_note,self.reference_listened,self.variants):widget.setEnabled(loaded)
        self.cases.setEnabled(loaded and not dirty)
        self.open_button.setEnabled(not dirty);self.create_button.setEnabled(not dirty);self.export_button.setEnabled(loaded and not dirty)
        self.discard_reference.setEnabled(bool(dirty))
        available=loaded and self.case()['variants'][self.variant()]['available'] and not self.masked()
        for widget in (self.add_event,self.remove_event,self.save_rating,self.rating_listened):widget.setEnabled(bool(available and not dirty))

    def has_unsaved_reference(self):
        if not self.study:return False
        audit=self.case().get('reference_audit') or {}
        return (self.reference.toPlainText()!=self.case()['reference'] or self.reference_note.text()!=audit.get('note','')
                or self.reference_listened.isChecked()!=audit.get('listened',False))

    def masked(self):
        return bool(self.study and self.mask_hypotheses.isChecked() and
            (not (self.case().get('reference_audit') or {}).get('listened') or self.reference.toPlainText()!=self.case()['reference']))

    def reference_edited(self):
        if self.loading:return
        if self.study and self.reference.toPlainText()!=self.case()['reference']:self.reference_listened.setChecked(False)
        self.reference_dirty()
        self.render_variant()

    def reference_dirty(self,*_):
        if self.loading:return
        self.enable_controls()
        if self.has_unsaved_reference():
            self.status.setText('Save or discard the reference audit before changing clips or rating a variant. Text corrections invalidate prior ratings while preserving history.')

    def load_study(self,path):
        store=StudyStore(path);study=store.load();self.player.stop();self.store=store;self.study=study
        self.cases.blockSignals(True);self.cases.clear()
        for case in study['cases']:self.cases.addItem(case['id'])
        self.cases.blockSignals(False);self.cases.setCurrentIndex(0);self.render_case()
        self.status.setText('Loaded '+str(store.path))

    def refresh_summary(self):
        report=quality_report(self.study);base=report['variants']['baseline'];after=report['variants']['review']
        def cer(v):
            metric=v['automatic_text_difference']['cer_available'];return f'{metric:.2%}' if metric is not None else 'N/A'
        self.summary.setText(f'Clips: {len(self.study["cases"])} • text CER: {cer(base)} → {cer(after)} • available: '
            f'{base["available_cases"]}/{len(self.study["cases"])} → {after["available_cases"]}/{len(self.study["cases"])} • '
            f'audited references: {base["audio_audited_reference_cer"]["cases"]} • paired listening reviews: {report["paired_semantic_comparison"]["cases"]}')

    def render_case(self,*_):
        if not self.study:return
        self.player.stop();case=self.case();self.loading=True
        self.reference.setPlainText(case['reference']);audit=case.get('reference_audit') or {}
        self.reference_note.setText(audit.get('note',''));self.reference_listened.setChecked(audit.get('listened',False))
        self.loading=False;self.render_variant();self.refresh_summary();self.enable_controls()

    def render_variant(self,*_):
        if not self.study:return
        for variant,text in self.hypotheses.items():
            data=self.case()['variants'][variant]
            text.setPlainText('[Hidden during reference audit] Save an audio-checked reference, or turn off the ASR mask to compare provisionally.'
                if self.masked() else data['text'] if data['available'] else '[Unavailable] '+data['error'])
            if data['available']:
                metric=score_text(self.case()['reference'],data['text'])
                text.setToolTip(f'Character edits only: substitutions {metric["substitutions"]}, deletions {metric["deletions"]}, insertions {metric["insertions"]}. These are not semantic event counts.\n'+str(data['evidence']))
        rating=self.case()['ratings'].get(self.variant(),{});self.rating_listened.setChecked(rating.get('listened',False))
        values=rating.get('events',[]);self.events.setRowCount(len(values))
        for row,event in enumerate(values):
            for column,key in enumerate(('category','severity','reference_quote','hypothesis_quote','note')):
                item=QTableWidgetItem(event[key]);item.setToolTip(event[key]);self.events.setItem(row,column,item)
            self.events.setRowHeight(row,65)
        self.enable_controls()

    def _commit(self,operation):
        candidate=deepcopy(self.study);operation(candidate['cases'][self.cases.currentIndex()])
        self.store.save(candidate);self.study=candidate;self.render_case();self.status.setText('Saved study assessment. Production tracks and source artifacts were not modified.')

    def apply_reference(self):
        self._commit(lambda case:audit_reference(case,self.reference.toPlainText(),self.reviewer.text(),self.reference_note.text(),listened=self.reference_listened.isChecked()))

    def current_events(self):return deepcopy(self.case()['ratings'].get(self.variant(),{}).get('events',[]))

    def apply_rating(self):
        self._commit(lambda case:record_rating(case,self.variant(),self.current_events(),self.reviewer.text(),listened=self.rating_listened.isChecked()))

    def add_event_dialog(self):
        if self.masked():raise ValueError('Finish the reference audit or turn off masking before classifying a hypothesis.')
        dialog=ErrorEventDialog(self,self.reference.textCursor().selectedText().replace('\u2029','\n'),
            self.hypotheses[self.variant()].textCursor().selectedText().replace('\u2029','\n'))
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        values=self.current_events()+[dialog.values()]
        self._commit(lambda case:record_rating(case,self.variant(),values,self.reviewer.text(),listened=False))

    def delete_event(self):
        row=self.events.currentRow();values=self.current_events()
        if not 0<=row<len(values):raise ValueError('Select an error event first.')
        del values[row]
        self._commit(lambda case:record_rating(case,self.variant(),values,self.reviewer.text(),listened=False))

    def play_clip(self):
        path=check_audio(self.case());self.owner.player.pause()
        self.player.setSource(QUrl.fromLocalFile(str(path)));self.player.play()
        self.status.setText('Listening: '+self.case()['id']+' • reference audit and variant assessment require separate confirmation.')

    def hideEvent(self,event):
        self.player.pause();super().hideEvent(event)

    def open_dialog(self):
        path,_=QFileDialog.getOpenFileName(self,'Open quality study','','Quality study (*.json)')
        if path:self.load_study(path)

    def create_dialog(self):
        index,_=QFileDialog.getOpenFileName(self,'Choose reference index','','JSON (*.json)')
        if not index:return
        results,_=QFileDialog.getOpenFileName(self,'Choose results with records: id / manifest','','JSON (*.json)')
        if not results:return
        path,_=QFileDialog.getSaveFileName(self,'Save a new quality study',str(Path(self.owner.settings.cache_dir)/'source-quality/study.json'),'JSON (*.json)')
        if not path:return
        study=create_study(index,results);store=StudyStore(path);store.save(study);self.load_study(path)

    def export_dialog(self):
        path,_=QFileDialog.getSaveFileName(self,'Export quality report',str(self.store.path.with_name(self.store.path.stem+'-report.json')),'JSON (*.json)')
        if path:self.export_report(Path(path))

    def export_report(self,path):
        write_reports(self.study,path,self.store.path)
        self.status.setText('Exported JSON and Markdown quality reports: '+str(path))

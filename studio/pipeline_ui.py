from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .core import now, uid
from .pipeline import VARIANTS, create_run, digest, load_run, plan, repairs_enabled, track_from, validate_config
from .pipeline_worker import approve_review, read_json, write_json
from .storage import check_space
from .editing import processing_digest


def text_label(value):
    label = QLabel(value)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class PipelinePanel(QWidget):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner = owner
        self.inputs = []
        self.project_token = None
        self.restoring = False
        layout = QVBoxLayout(self)
        layout.addWidget(text_label('Zrób wszystko • kolejne etapy od filmu do SRT'))
        self.transcription_only=QCheckBox('Tylko oryginalne napisy JP • bez tłumaczenia i review EN')
        self.transcription_only.setChecked(True)
        layout.addWidget(self.transcription_only)
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(['Zrównoważony • 2 ASR / 2 EN','Szybki • 1 ASR / 1 EN','Dokładny • 2 ASR / 2 EN + pełne AI','Własny',
                             'Porównawczy • 3 ASR / 2 EN + pełne AI','Transkrypcja JP • Large V3 + wycinki'])
        self.preset.currentIndexChanged.connect(self.apply_preset)
        row.addWidget(self.preset,1)
        self.backend = QComboBox()
        self.backend.addItem('Wbudowany GGUF','embedded')
        self.backend.addItem('LM Studio • opcjonalny','lmstudio')
        self.backend.currentIndexChanged.connect(self.refresh_models)
        row.addWidget(self.backend)
        self.review = QComboBox()
        for title,key in [('Szybkie • reguły, bez poprawek AI','rules'),('Dokładne • AI dla podejrzanych','balanced'),
                          ('Pełne • AI, poprawki i ponowna ocena','deep')]:
            self.review.addItem(title,key)
        self.review.setCurrentIndex(1)
        row.addWidget(self.review,1)
        self.review_action=QComboBox()
        self.review_action.addItem('Sprawdź i popraw','repair')
        self.review_action.addItem('Tylko sprawdź','check')
        self.review_action.setToolTip('Poprawki EN przechodzą porównanie z poprzednią wersją; niepewne pozostają do kontroli.')
        row.addWidget(self.review_action)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.asr_count,self.en_count = QSpinBox(),QSpinBox()
        for spin in (self.asr_count,self.en_count):
            spin.setRange(1,4)
            spin.setValue(2)
        row.addWidget(text_label('Transkrypcje'))
        row.addWidget(self.asr_count)
        self.en_count_label=text_label('Tłumaczenia');row.addWidget(self.en_count_label)
        row.addWidget(self.en_count)
        self.judge = QComboBox()
        self.judge_label=text_label('Model porównujący / review');row.addWidget(self.judge_label)
        row.addWidget(self.judge,1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.asr_table = QTableWidget(4,2)
        self.asr_table.setHorizontalHeaderLabels(['Model ASR','VAD'])
        self.en_table = QTableWidget(4,2)
        self.en_table.setHorizontalHeaderLabels(['Model tłumacza','Profil wariantu'])
        self.asr_models,self.vad,self.en_models,self.variants = [],[],[],[]
        for table,width in ((self.asr_table,65),(self.en_table,155)):
            table.horizontalHeader().setStretchLastSection(False)
            table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(1,width)
            table.setMinimumHeight(125)
        for i in range(4):
            a,e,v,p = QComboBox(),QComboBox(),QCheckBox(),QComboBox()
            v.setChecked(i<2)
            for n,(label,_) in enumerate(VARIANTS):
                p.addItem(label,n)
            p.setCurrentIndex(i)
            self.asr_models.append(a); self.en_models.append(e); self.vad.append(v); self.variants.append(p)
            self.asr_table.setCellWidget(i,0,a); self.asr_table.setCellWidget(i,1,v)
            self.en_table.setCellWidget(i,0,e); self.en_table.setCellWidget(i,1,p)
            self.inputs += [a,e,v,p]
            self.asr_table.setRowHeight(i,46); self.en_table.setRowHeight(i,46)
        row.addWidget(self.asr_table,1)
        row.addWidget(self.en_table,1)
        layout.addLayout(row)
        options = QHBoxLayout()
        self.start,self.length = QDoubleSpinBox(),QDoubleSpinBox()
        for box in (self.start,self.length):
            box.setRange(0,864000)
            box.setDecimals(3)
            box.setSuffix(' s')
        self.length.setSpecialValueText('Cały pozostały film')
        options.addWidget(text_label('Od'))
        options.addWidget(self.start)
        options.addWidget(text_label('Długość'))
        options.addWidget(self.length)
        self.autosplit = QCheckBox('Podział zdań • czas szacowany')
        self.autosplit.setToolTip('Opcjonalny podział dwóch zdań JP/EN w istniejącym czasie. '
                                  'Każdy taki punkt zostaje oznaczony do odsłuchu.')
        self.export = QCheckBox('Eksport JP / EN')
        self.export_format=QComboBox()
        for fmt in ('srt','ass','ssa','txt'): self.export_format.addItem(fmt.upper(),fmt)
        self.export.setChecked(True)
        self.sound = QCheckBox('Dźwięk na koniec')
        self.pause = QCheckBox('Pauza na niepewnych wyborach')
        self.pause.setToolTip('Po wyborze JP lub EN zatrzymaj przebieg do ręcznej kontroli. Potem kontynuuj bez powtarzania ASR.')
        options.addWidget(self.autosplit)
        options.addWidget(self.export)
        options.addWidget(self.export_format)
        options.addWidget(self.sound)
        layout.addLayout(options)
        layout.addWidget(self.pause)
        self.continue_asr = QCheckBox('Kontynuuj na poprawnych ASR, jeśli któryś wynik ma wadliwe czasy')
        self.continue_asr.setChecked(True)
        self.continue_asr.setToolTip('Wadliwy wynik i logi pozostają w raporcie. Jeśli wszystkie ASR zawiodą, przebieg zostanie zatrzymany. Błędy pamięci, urządzenia i plików nadal zatrzymują proces.')
        layout.addWidget(self.continue_asr)
        self.readability=QCheckBox('Popraw układ JP/EN i wydłuż ekspozycję do 250 ms w wolnych przerwach')
        self.readability.setChecked(True)
        self.readability.setToolTip('Bez zmiany początku i nakładania napisów; każda zmiana czasu zostaje oznaczona. Nie zastępuje wyrównania do audio. Ręczne napisy zachowują czasy.')
        layout.addWidget(self.readability)
        retry_row=QHBoxLayout()
        self.retry_clips=QCheckBox('Ponów podejrzane wycinki • Large V3 + model pomocniczy')
        self.retry_clips.setChecked(True)
        self.retry_aux=QComboBox();self.retry_aux.setToolTip('Pomocnicza propozycja audio; sam ten model nie zastępuje bazy.')
        self.retry_context=QDoubleSpinBox();self.retry_context.setRange(1,10);self.retry_context.setValue(3);self.retry_context.setSuffix(' s kontekstu')
        self.retry_limit=QSpinBox();self.retry_limit.setRange(1,30);self.retry_limit.setValue(12);self.retry_limit.setSuffix(' wycinków maks.')
        for widget in (self.retry_clips,self.retry_aux,self.retry_context,self.retry_limit):retry_row.addWidget(widget)
        layout.addLayout(retry_row)
        self.scan_first=QCheckBox('Compare the whole recording with auxiliary ASR before selecting retries')
        self.scan_first.setChecked(True)
        self.scan_first.setToolTip('Find disagreements even when the baseline is confident. Adds a full auxiliary pass and may select more retries. Complete scan cues are reused; the retry-window limit bounds further work.')
        layout.addWidget(self.scan_first)
        self.film_context=QCheckBox('Kontekst całego filmu • temat, terminy i spójność dialogów')
        self.film_context.setChecked(True)
        layout.addWidget(self.film_context)
        self.context_label=text_label('Opis kontekstu pojawi się po analizie JP; to hipoteza wymagająca zgodności ze źródłem.')
        self.context_label.setMaximumHeight(65);layout.addWidget(self.context_label)
        layout.addWidget(text_label('Wybierz film w edytorze. Domyślnie przetwarzany jest cały materiał; '
                                    'na próbę ustaw 20–60 s. Warianty i decyzje pozostają w projekcie. '
                                    'Różne ASR są porównywane tekstowo; niepewne miejsca trafiają do raportu i review.'))
        row = QHBoxLayout()
        self.start_button = QPushButton('Zrób wszystko')
        self.start_button.setObjectName('primary')
        self.resume_button = QPushButton('Wznów przerwany przebieg')
        self.folder_button = QPushButton('Otwórz wyniki')
        self.plan_button = QPushButton('Pokaż plan')
        self.clips_button=QPushButton('Review JP • porównaj frazy ASR')
        self.clips_button.clicked.connect(self.show_retry_results)
        self.start_button.clicked.connect(self.start_run)
        self.resume_button.clicked.connect(self.resume_run)
        self.folder_button.clicked.connect(self.open_results)
        self.plan_button.clicked.connect(self.preview_plan)
        for b in (self.start_button,self.resume_button,self.plan_button,self.folder_button):
            row.addWidget(b,1)
            owner.mutating.append(b)
        layout.addLayout(row)
        self.summary = text_label('Plan: audio → ASR → wybór JP → warianty EN → wybór EN → review → SRT i raport.')
        layout.addWidget(self.clips_button)
        layout.addWidget(self.summary)
        self.stages = QTableWidget(0,3)
        self.stages.setHorizontalHeaderLabels(['Etap','Stan','Czas'])
        self.stages.setColumnWidth(0,750)
        self.stages.setColumnWidth(1,180)
        self.stages.horizontalHeader().setStretchLastSection(True)
        self.stages.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.stages,1)
        self.inputs += [self.preset,self.backend,self.review,self.review_action,self.asr_count,self.en_count,self.judge,
                        self.start,self.length,self.autosplit,self.export,self.export_format,self.sound,self.pause,self.film_context,self.continue_asr,self.readability,
                        self.transcription_only,self.retry_clips,self.retry_aux,self.retry_context,self.retry_limit,self.scan_first]
        self.asr_count.valueChanged.connect(self.show_rows)
        self.en_count.valueChanged.connect(self.show_rows)
        self.asr_count.valueChanged.connect(self.update_preset_label)
        self.en_count.valueChanged.connect(self.update_preset_label)
        self.review.currentIndexChanged.connect(self.update_preset_label)
        self.review.currentIndexChanged.connect(lambda *_:self.review_action.setEnabled(not self.owner.busy and self.review.currentData()!='rules'))
        self.show_rows()
        self.transcription_only.toggled.connect(self.update_scope)
        self.retry_clips.toggled.connect(self.update_scope)
        self.apply_preset(5)

    def update_scope(self,*_):
        jp=self.transcription_only.isChecked()
        for widget in (self.en_count,self.en_count_label,self.judge,self.judge_label,self.en_table,self.backend,self.review,self.review_action,self.film_context):
            widget.setVisible(not jp)
        self.asr_count.setEnabled(not jp and not self.owner.busy)
        if jp:
            self.asr_count.setValue(1);self.vad[0].setChecked(True)
            choices=self.asr_models[0]
            index=next((i for i in range(choices.count()) if choices.itemData(i)['engine']==2 and 'large-v3' in choices.itemData(i)['model'].lower()),-1)
            if index>=0: choices.setCurrentIndex(index)
        self.autosplit.setEnabled(not jp and not self.owner.busy)
        self.pause.setEnabled(not jp and not self.owner.busy)
        self.vad[0].setEnabled(not jp and not self.owner.busy)
        self.continue_asr.setEnabled(not self.owner.busy)
        self.readability.setText('Popraw układ JP • bez przesuwania czasów' if jp else 'Popraw układ JP/EN i wydłuż ekspozycję do 250 ms w wolnych przerwach')
        self.export.setText('Eksport JP' if jp else 'Eksport JP / EN')
        for widget in (self.retry_clips,self.retry_aux,self.retry_context,self.retry_limit,self.scan_first):widget.setVisible(jp)
        self.scan_first.setEnabled(jp and self.retry_clips.isChecked() and not self.owner.busy)
        self.retry_aux.setEnabled(jp and self.retry_clips.isChecked() and not self.owner.busy)
        self.retry_context.setEnabled(jp and self.retry_clips.isChecked() and not self.owner.busy)
        self.retry_limit.setEnabled(jp and self.retry_clips.isChecked() and not self.owner.busy)
        self.update_preset_label()

    def preview_plan(self):
        config = {'asr':[combo.currentData() or {'name':'wybierz model'} for combo in self.asr_models[:self.asr_count.value()]],
                  'translations':[{'variant':v.currentData()} for v in self.variants[:self.en_count.value()]],
                  'review':self.review.currentData(),'review_action':self.review_action.currentData(),'film_context':self.film_context.isChecked(),
                  'source_review_version':2 if self.transcription_only.isChecked() else 1}
        config.update(transcription_only=self.transcription_only.isChecked(),retry_asr={'enabled':self.retry_clips.isChecked(),
            'scan_first':self.scan_first.isChecked(),'auxiliary':self.retry_aux.currentData()})
        steps = plan(config)
        self.stages.setRowCount(len(steps))
        for row,stage in enumerate(steps):
            for col,value in enumerate((stage['label'],'W planie','')):
                self.stages.setItem(row,col,QTableWidgetItem(value))
            self.stages.setRowHeight(row,34)
        self.summary.setText(f'Plan nowego przebiegu: {len(steps)} etapów. '
                             'Wbudowany model zwalnia GPU przed następnym etapem; warianty zostaną zachowane.')

    def apply_preset(self,index):
        if index==3:
            return
        self.transcription_only.setChecked(index==5)
        if index==5:
            self.asr_count.setValue(1);self.vad[0].setChecked(True)
            self.film_context.setChecked(False);self.update_scope();return
        self.asr_count.setValue(1 if index==1 else 3 if index==4 else 2)
        self.en_count.setValue(1 if index==1 else 2)
        self.review.setCurrentIndex(0 if index==1 else 2 if index in (2,4) else 1)
        self.film_context.setChecked(index!=1)
        if index==4:
            for vad in self.vad[:3]: vad.setChecked(True)

    def update_preset_label(self,*_):
        if self.transcription_only.isChecked():
            self.preset.blockSignals(True);self.preset.setCurrentIndex(5);self.preset.blockSignals(False);return
        key = (self.asr_count.value(),self.en_count.value(),self.review.currentData())
        index = {(2,2,'balanced'):0,(1,1,'rules'):1,(2,2,'deep'):2,(3,2,'deep'):4}.get(key,3)
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(index)
        self.preset.blockSignals(False)

    def show_rows(self):
        for i in range(4):
            self.asr_table.setRowHidden(i,i>=self.asr_count.value())
            self.en_table.setRowHidden(i,i>=self.en_count.value())
        height = 46*max(self.asr_count.value(),self.en_count.value())+50
        self.asr_table.setFixedHeight(height)
        self.en_table.setFixedHeight(height)

    def refresh_models(self,*_):
        records = []
        for engine,kind in [(2,'Whisper / GGML'),(1,'Qwen ASR'),(3,'ReazonSpeech / GGUF'),(0,'Whisper / CTranslate2')]:
            executable = self.owner.settings.whisper_exe if engine==0 else self.owner.settings.crisp_exe
            if not executable or not Path(executable).is_file():
                continue
            records += [{'engine':engine,'model':m.path,'name':m.name,'kind':m.kind}
                        for m in self.owner.models if m.kind==kind]
        for index,combo in enumerate(self.asr_models):
            selected = combo.currentData()
            combo.clear()
            for item in records:
                combo.addItem(('Anime-Whisper • ' if 'anime-whisper' in item['model'].lower() else 'Kotoba • ' if 'kotoba' in item['model'].lower() else 'ReazonSpeech • ' if item['engine']==3 else 'Qwen JA Anime/Galgame • ' if item['engine']==1 else 'Whisper • ')+item['name'],item)
            found = next((i for i in range(combo.count()) if combo.itemData(i)==selected),-1)
            if found<0 and index in (0,1):
                found=next((i for i in range(combo.count()) if
                    (combo.itemData(i)['engine']==1 if index==1 else
                     combo.itemData(i)['engine']==2 and 'large-v3' in combo.itemData(i)['model'].lower())), -1)
            if found<0 and index==2:
                found=next((i for i in range(combo.count()) if 'kotoba' in combo.itemData(i)['model'].lower()),-1)
            combo.setCurrentIndex(found if found>=0 else index%len(records) if records else -1)
        selected=self.retry_aux.currentData()
        self.retry_aux.clear()
        auxiliaries=[item for item in records if item['engine'] in (1,3) or item['engine']==2 and any(t in item['model'].lower() for t in ('kotoba','anime-whisper'))]
        auxiliaries.sort(key=lambda item:(0 if 'kotoba' in item['model'].lower() else 1 if item['engine']==3 else 2,item['name']))
        for item in auxiliaries:
            label=item['name']+(' • eksperymentalna konwersja' if 'anime-whisper' in item['model'].lower() else ' • testowy' if item['engine'] in (1,3) else '')
            self.retry_aux.addItem(label,item)
        index=next((i for i in range(self.retry_aux.count()) if self.retry_aux.itemData(i)==selected),0 if auxiliaries else -1)
        self.retry_aux.setCurrentIndex(index)
        models = ([ (m.name,m.path) for m in self.owner.models if m.kind=='LLM / GGUF'] if self.backend.currentData()=='embedded'
                  else [(self.owner.llm_combo.itemText(i),self.owner.llm_combo.itemText(i)) for i in range(self.owner.llm_combo.count())])
        for combo in self.en_models+[self.judge]:
            selected = combo.currentData() or self.owner.settings.llm_model
            combo.clear()
            for name,path in models:
                combo.addItem(name,path)
            combo.setCurrentIndex(max(0,combo.findData(selected)))

    def last_job(self):
        return next((j for j in reversed(self.owner.project.jobs) if j.get('type')=='pipeline'),None)

    def set_busy(self,busy):
        for widget in self.inputs:
            widget.setEnabled(not busy)
        self.review_action.setEnabled(not busy and self.review.currentData()!='rules')
        job = self.last_job()
        self.resume_button.setEnabled(not busy and bool(job and job['status'] in {'cancelled','failed','running','interrupted','awaiting_review'}))
        self.resume_button.setText('Kontynuuj po kontroli' if job and job['status']=='awaiting_review' else 'Wznów przerwany przebieg')
        self.folder_button.setEnabled(not busy and bool(job))
        self.clips_button.setEnabled(not busy and bool(job and any((Path(job['manifest']).parent/p).is_file()
            for p in ('jp-review/result.json','asr-retry/result.json'))))
        self.update_scope()

    def sync_project(self):
        if self.project_token != id(self.owner.project):
            self.project_token = id(self.owner.project)
            prefs = self.owner.project.pipeline_prefs
            self.continue_asr.setChecked(prefs.get('asr_failure_policy','continue')=='continue')
            self.readability.setChecked(prefs.get('readability_repair',True))
            for key,widget in [('asr_count',self.asr_count),('en_count',self.en_count),('start',self.start),('length',self.length)]:
                if key in prefs:
                    widget.setValue(prefs[key])
            if 'review' in prefs:
                self.review.setCurrentIndex(max(0,self.review.findData(prefs['review'])))
            self.review_action.setCurrentIndex(max(0,self.review_action.findData(prefs.get('review_action','repair'))))
            self.film_context.setChecked(prefs.get('film_context',True))
            if 'backend' in prefs:
                self.backend.setCurrentIndex(max(0,self.backend.findData(prefs['backend'])))
            for combo,vad,item in zip(self.asr_models,self.vad,prefs.get('asr',[])):
                combo.setCurrentIndex(combo.findData({k:v for k,v in item.items() if k!='vad'}))
                vad.setChecked(item['vad'])
            for combo,profile,item in zip(self.en_models,self.variants,prefs.get('translations',[])):
                combo.setCurrentIndex(combo.findData(item['model']))
                profile.setCurrentIndex(profile.findData(item['variant']))
            if 'judge_model' in prefs:
                self.judge.setCurrentIndex(self.judge.findData(prefs['judge_model']))
            self.export_format.setCurrentIndex(max(0,self.export_format.findData(prefs.get('export_format','srt'))))
            for key,widget in [('autosplit',self.autosplit),('export_srt',self.export),('sound',self.sound),('pause_uncertain',self.pause)]:
                if key in prefs:
                    widget.setChecked(prefs[key])
            self.transcription_only.setChecked(prefs.get('transcription_only',not bool(prefs.get('translations'))))
            self.retry_clips.setChecked(prefs.get('retry_clips',True))
            self.scan_first.setChecked(prefs.get('scan_first',True))
            self.retry_context.setValue(prefs.get('retry_context',3))
            self.retry_limit.setValue(prefs.get('retry_limit',12))
            saved_aux=prefs.get('retry_aux_model')
            if saved_aux:
                selected=next((i for i in range(self.retry_aux.count()) if self.retry_aux.itemData(i)['model']==saved_aux),-1)
                if selected>=0:self.retry_aux.setCurrentIndex(selected)
            self.update_scope()
            self.update_preset_label()
        job = self.last_job()
        if job and Path(job['manifest']).is_file():
            self.render_state(read_json(job['manifest']))
        elif not job:
            self.context_label.setText('Kontekst dostępnych napisów pojawi się po analizie.')
            self.context_label.setToolTip('')
        self.set_busy(self.owner.busy)

    def config(self,run_id):
        owner = self.owner
        if not owner.project.media or not Path(owner.project.media).is_file():
            raise ValueError('Najpierw zaimportuj film lub audio w edytorze.')
        start,length = round(self.start.value()*1000),round(self.length.value()*1000)
        duration = min(length,owner.project.duration-start) if length else owner.project.duration-start
        asr = []
        for combo,vad in zip(self.asr_models[:self.asr_count.value()],self.vad):
            if not combo.currentData():
                raise ValueError('Brak modelu ASR. Sprawdź foldery modeli.')
            asr.append({**combo.currentData(),'vad':vad.isChecked()})
        jp_only=self.transcription_only.isChecked()
        translations = [] if jp_only else [{'model':combo.currentData(),'variant':profile.currentData()}
                        for combo,profile in zip(self.en_models[:self.en_count.value()],self.variants)]
        if not jp_only and (any(not item['model'] for item in translations) or not self.judge.currentData()):
            raise ValueError('Wybierz modele tłumacza i review. Dla LM Studio odczytaj modele w zakładce tłumaczenia.')
        settings = asdict(owner.settings)
        settings.update(lm_url=owner.lm_url.text().strip(),llm_device=owner.llm_device_combo.currentData(),
                        llm_context=owner.llm_context.currentData(),llm_batch_size=owner.llm_batch.value())
        config = {'media':str(Path(owner.project.media).resolve()),'media_duration':owner.project.duration,
                  'audio_track':owner.project.audio_track,'start':start,'duration':duration,'asr':asr,
                  'translations':translations,'backend':self.backend.currentData(),'judge_model':self.judge.currentData(),
                  'review':self.review.currentData(),'review_action':self.review_action.currentData(),
                  'film_context':self.film_context.isChecked() and not jp_only,
                  'transcription_only':jp_only,
                  'source_review_version':2 if jp_only else 1,
                  'asr_failure_policy':'continue' if self.continue_asr.isChecked() else 'stop',
                  'decision_batch_size':4,'source_guard':True,'readability_repair':self.readability.isChecked(),
                  'llm_keep_loaded':Path(settings['llm_exe']).with_name('llama-server.exe').is_file() if settings['llm_exe'] else False,
                  'review_settings':copy.deepcopy(owner.project.review_settings),
                  'settings':settings,'prompt':owner.prompt.toPlainText(),'export_srt':self.export.isChecked(),
                  'autosplit':self.autosplit.isChecked(),'output_dir':str(owner.store.path.parent/'exports'/run_id),
                  'pause_uncertain':self.pause.isChecked(),
                  'export_format':self.export_format.currentData(),
                  'xxl_device':owner.device.currentText(),'xxl_compute':owner.compute.currentText()}
        if jp_only:
            auxiliary={**self.retry_aux.currentData(),'vad':True} if self.retry_aux.currentData() else None
            config.update(review='rules',llm_keep_loaded=False,judge_model='',autosplit=False,
                retry_asr={'enabled':self.retry_clips.isChecked(),'padding_ms':round(self.retry_context.value()*1000),
                           'max_window_ms':30000,'max_targets':self.retry_limit.value(),'auxiliary':auxiliary,
                           'scan_first':self.scan_first.isChecked()})
        validate_config(config)
        if config['backend']=='embedded' and not jp_only:
            from .embedded_llm import model_identity
            for model in {config['judge_model'],*(t['model'] for t in translations)}:
                model_identity({'model_path':model,'executable':settings['llm_exe']})
        return config

    def start_run(self):
        if self.owner.busy:
            return
        def operation():
            owner = self.owner
            owner.editor_tools.commit()
            owner.save()
            if owner.store is None:
                raise ValueError('Najpierw zaimportuj film lub audio.')
            run_id = uid()
            config = self.config(run_id)
            check_space(Path(owner.settings.cache_dir),config['duration']*32+20*1024**2,owner.settings.reserve_gib)
            folder = Path(owner.settings.cache_dir)/'pipeline'/run_id
            state = create_run(config,folder)
            owner.checkpoint()
            owner.project.pipeline_prefs = {'asr_count':self.asr_count.value(),'en_count':self.en_count.value(),
                                           'review':self.review.currentData(),'review_action':self.review_action.currentData(),'backend':self.backend.currentData(),
                                           'start':self.start.value(),'length':self.length.value(),
                                           'asr':config['asr'],'translations':config['translations'],
                                           'judge_model':config['judge_model'],'autosplit':config['autosplit'],
                                           'export_srt':config['export_srt'],'sound':self.sound.isChecked()}
            owner.project.pipeline_prefs['pause_uncertain']=self.pause.isChecked()
            owner.project.pipeline_prefs['film_context']=self.film_context.isChecked()
            owner.project.pipeline_prefs['asr_failure_policy']=config['asr_failure_policy']
            owner.project.pipeline_prefs['readability_repair']=config['readability_repair']
            owner.project.pipeline_prefs['export_format']=self.export_format.currentData()
            owner.project.pipeline_prefs.update(transcription_only=config['transcription_only'],retry_clips=self.retry_clips.isChecked(),
                retry_context=self.retry_context.value(),retry_limit=self.retry_limit.value(),scan_first=self.scan_first.isChecked())
            owner.project.pipeline_prefs['retry_aux_model']=(self.retry_aux.currentData() or {}).get('model')
            owner.job = {'id':run_id,'type':'pipeline','status':'running','created':now(),
                         'manifest':str(folder/'manifest.json'),'track_hashes':{},'stage_tracks':{}}
            owner.project.jobs.append(owner.job)
            owner.save(reason='pipeline started')
            self.render_state(state)
            owner.worker_error = ''
            owner.run_worker({'action':'pipeline','manifest':owner.job['manifest']},self.finished)
        self.owner.guarded(operation)

    def resume_run(self):
        if self.owner.busy:
            return
        def operation():
            owner = self.owner
            owner.editor_tools.commit()
            job = self.last_job()
            if not job or job['status'] not in {'failed','cancelled','running','interrupted','awaiting_review'}:
                raise ValueError('Brak przerwanego przebiegu do wznowienia.')
            state = load_run(job['manifest'])
            if str(Path(owner.project.media).resolve()) != state['config']['media'] or owner.project.audio_track!=state['config']['audio_track']:
                raise ValueError('Zmieniono materiał lub ścieżkę audio. Uruchom nowy przebieg.')
            tracks = {t.id:t for t in owner.project.tracks}
            changes=[key for key,value in job['track_hashes'].items() if key not in tracks or processing_digest(tracks[key])!=value]
            allowed=state.get('paused_track') if state['status']=='awaiting_review' else None
            if any(key!=allowed for key in changes):
                raise ValueError('Edytowano wyniki pipeline po zatrzymaniu. Uruchom nowy przebieg, aby zachować te zmiany.')
            if allowed:
                if allowed not in tracks: raise ValueError('Brak ścieżki oczekującej na kontrolę.')
                state=approve_review(job['manifest'],tracks[allowed])
                job['track_hashes'][allowed]=processing_digest(tracks[allowed])
            owner.job = job
            job.update(status='running',error='')
            owner.worker_error = ''
            owner.save()
            owner.run_worker({'action':'pipeline','manifest':job['manifest']},self.finished)
        self.owner.guarded(operation)

    def render_state(self,state):
        context=state.get('film_context','')
        self.context_label.setText('Kontekst • hipoteza z dostępnego JP: '+context if context else 'Kontekst dostępnych napisów pojawi się po analizie.')
        self.context_label.setToolTip(context+'\n\n'+state.get('continuity_notes',''))
        if state['config'].get('transcription_only'):
            self.context_label.setText('Large V3 + VAD → ponowienia audio → review i składanie zgodnych fraz JP → SRT. Sporne frazy do odsłuchu. Bez tłumaczenia i bez LLM.')
            if state['config'].get('retry_asr',{}).get('scan_first'):
                self.context_label.setText(f'Baseline + auxiliary scan → disagreements → audio retries → JP review. '
                    f'Disputed cues: {state.get("jp_scan_disagreements",0)}; reused scan fragments: {state.get("jp_reused_scan_attempts",0)}.')
        self.stages.setRowCount(len(state['stages']))
        labels = {'pending':'Oczekuje','running':'Przetwarzanie','completed':'Gotowe','failed':'Błąd'}
        rejected={f['stage'] for f in state.get('asr_failures',[])}
        for i,stage in enumerate(state['stages']):
            for col,value in enumerate((stage['label'],'Odrzucony wynik ASR' if stage['id'] in rejected else labels.get(stage['status'],stage['status']),
                                        str(stage.get('seconds',''))+' s' if 'seconds' in stage else '')):
                self.stages.setItem(i,col,QTableWidgetItem(value))
            self.stages.setRowHeight(i,34)
        active = next((i for i,s in enumerate(state['stages']) if s['status']=='running'),None)
        if active is None:
            active = max((i for i,s in enumerate(state['stages']) if s['status']=='completed'),default=0)
        if state['stages']:
            self.stages.selectRow(active)
            self.stages.scrollToItem(self.stages.item(active,0))
        done = sum(s['status']=='completed' for s in state['stages'])
        status = {'running':'Przetwarzanie','pending':'W planie','needs_review':'Gotowe • wymaga kontroli',
                  'completed':'Gotowe','cancelled':'Anulowano','failed':'Zatrzymano','awaiting_review':'Czeka na Twoją kontrolę'}.get(state['status'],state['status'])
        edits=f' • poprawiono EN: {state["review_changed_cues"]}' if 'review_changed_cues' in state else ''
        if state['config'].get('transcription_only'):
            edits=f' • ponowione wycinki: {state.get("asr_retry_windows",0)} • zmienione napisy JP: {state.get("jp_review_changed_cues",state.get("asr_retry_changes",0))}'
        if rejected: edits+=f' • odrzucone ASR: {len(rejected)}'
        action='sprawdź i popraw' if state['config'].get('review') in {'balanced','deep'} and repairs_enabled(state['config']) else 'sprawdzanie'
        self.summary.setText(f'Etapy: {done}/{len(state["stages"])} • {status} • {action}{edits} • '
                             f'ostrzeżenia: {state.get("warnings",0)} • wyniki: {state["config"]["output_dir"]}')

    def message(self,message):
        owner = self.owner
        job = owner.job
        if message['type']=='pipeline_progress':
            done,total = message['done'],max(1,message['total'])
            owner.progress.setRange(0,message['stages']*1000)
            owner.progress.setValue(round((message['completed']+done/total)*1000))
            owner.progress_label.setText(f'Pipeline • etap {message["completed"]+1}/{message["stages"]} • {done}/{total}')
            return
        if message.get('manifest') != job['manifest']:
            raise ValueError('Checkpoint należy do innego przebiegu.')
        state = read_json(job['manifest'])
        if message['type']=='pipeline_checkpoint':
            artifact = Path(message['artifact']).resolve()
            if not artifact.is_relative_to(Path(job['manifest']).resolve().parent):
                raise ValueError('Checkpoint poza folderem przebiegu.')
            data = read_json(artifact)
            if 'track' in data:
                track = track_from(data['track'])
                existing = next((i for i,t in enumerate(owner.project.tracks) if t.id==track.id),None)
                old_stage_id = job['stage_tracks'].get(message['stage'])
                if old_stage_id and old_stage_id!=track.id:
                    raise ValueError('Zmieniono ID ścieżki w checkpointcie.')
                if existing is None:
                    owner.project.add_track(track)
                else:
                    annotations={s.id:s for s in owner.project.tracks[existing].segments}
                    for segment in track.segments:
                        old=annotations.get(segment.id)
                        if old:
                            segment.bookmarked,segment.comment=old.bookmarked,old.comment
                            if (old.start,old.end,old.text,old.translation)==(segment.start,segment.end,segment.text,segment.translation):
                                segment.review_status=old.review_status
                    owner.project.tracks[existing] = track
                    owner.project.active_track = track.id
                job['stage_tracks'][message['stage']] = track.id
                job['track_hashes'][track.id] = processing_digest(track)
                owner.refresh()
        self.render_state(state)
        owner.save(reason='translation checkpoint')

    def finished(self,code,output,cancelled):
        owner = self.owner
        job = owner.job
        state = read_json(job['manifest'])
        if cancelled:
            state.update(status='cancelled')
            write_json(Path(job['manifest']),state)
            job.update(status='cancelled',finished=now())
            owner.progress_label.setText('Pipeline anulowany • gotowe etapy i wyniki zachowane')
        elif not code and state['status']=='awaiting_review':
            job.update(status='awaiting_review')
            owner.project.active_track=state['paused_track']
            owner.progress_label.setText('Pipeline czeka na kontrolę • popraw aktywną ścieżkę i kliknij Kontynuuj')
        elif code==75:
            job.update(status='interrupted')
            owner.progress_label.setText('Ten przebieg już działa w innym procesie • nie uruchomiono drugiej kopii')
        elif code:
            job.update(status='failed',error=owner.worker_error or state.get('error') or output[-2000:])
            state.update(status='failed',error=job['error'])
            write_json(Path(job['manifest']),state)
            owner.log('Pipeline zatrzymany: '+job['error'])
            owner.progress_label.setText('Pipeline zatrzymany • popraw przyczynę i wznów')
        else:
            job.update(status=state['status'],finished=now())
            owner.project.active_track = state['final_track']
            owner.progress.setRange(0,100)
            owner.progress.setValue(100)
            owner.progress_label.setText(f'Pipeline zakończony • poprawiono EN: {state.get("review_changed_cues",0)} • {state["warnings"]} napisów do kontroli')
            if state['config'].get('transcription_only'):
                owner.progress_label.setText(f'JP zakończone • wycinki: {state.get("asr_retry_windows",0)} • zmienione napisy: {state.get("jp_review_changed_cues",state.get("asr_retry_changes",0))} • {state["warnings"]} napisów do kontroli')
            if self.sound.isChecked():
                QApplication.beep()
        self.render_state(state)
        owner.save(reason='pipeline finished')
        owner.refresh()
        self.set_busy(False)

    def open_results(self):
        job = self.last_job()
        if job:
            state = read_json(job['manifest'])
            output = Path(state['config']['output_dir'])
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output if output.exists() else Path(job['manifest']).parent)))

    def show_retry_results(self):
        from PySide6.QtWidgets import QDialog,QDialogButtonBox
        job=self.last_job()
        if not job: return
        review_path=Path(job['manifest']).parent/'jp-review/result.json'
        if review_path.is_file():
            return self.show_source_review(read_json(review_path))
        path=Path(job['manifest']).parent/'asr-retry/result.json'
        if not path.is_file(): return
        result=read_json(path)
        dialog=QDialog(self.owner);dialog.setWindowTitle('Wycinki ASR • baza i ponowienia audio');dialog.resize(1200,650)
        layout=QVBoxLayout(dialog)
        layout.addWidget(text_label('Model pomocniczy jest propozycją. Bez zgodności dwóch poprawnych ponowień pozostaje baza Large V3. Dwuklik: odsłuch wycinka.'))
        table=QTableWidget(len(result['windows']),5)
        table.setHorizontalHeaderLabels(['Czas','Baza Large V3','Ponowienie Large V3','Model pomocniczy','Decyzja'])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setWordWrap(True);table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i,window in enumerate(result['windows']):
            alternatives=[' '.join(s['text'] for s in attempt.get('track',{}).get('segments',[])) if attempt.get('usable') else attempt.get('error','Brak wyniku') for attempt in window['attempts']]
            values=[f'{window["start"]/1000:.2f}–{window["end"]/1000:.2f} s',' '.join(s['text'] for s in window['before']),
                    alternatives[0] if alternatives else '',alternatives[1] if len(alternatives)>1 else 'Model niedostępny',window['decision']]
            for col,text in enumerate(values):table.setItem(i,col,QTableWidgetItem(text))
            table.setRowHeight(i,125)
        table.cellDoubleClicked.connect(lambda row,col:self.owner.play_interval(result['windows'][row]['start'],result['windows'][row]['end']))
        layout.addWidget(table)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);dialog.show()
        self.retry_dialog=dialog

    def show_source_review(self,result):
        from PySide6.QtWidgets import QDialog,QDialogButtonBox
        fragments=result['fragments']
        dialog=QDialog(self.owner);dialog.setWindowTitle('Review oryginału JP • porównanie fraz');dialog.resize(1250,700)
        layout=QVBoxLayout(dialog)
        layout.addWidget(text_label(f'Zmienione frazy: {len(result["changes"])}; napisy: {result["changed_cues"]}. '
            'Czasy zachowano. Sporne fragmenty pozostają z bazy. Zgodność modeli nie gwarantuje poprawności. Dwuklik: odsłuch napisu.'))
        table=QTableWidget(len(fragments),6)
        table.setHorizontalHeaderLabels(['Czas','Fraza z bazy','Wynik','Ponowienie bazy / ASR 1','Pozostałe ASR','Decyzja'])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setWordWrap(True);table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row,fragment in enumerate(fragments):
            def description(a):
                score=f' • pewność napisu {a["confidence"]:.2f}' if a['confidence'] is not None else ''
                return a['name']+score+'\n'+(a['text'] or '[brak dopasowanej frazy]')
            alternatives=fragment['alternatives']
            values=[f'{fragment["start"]/1000:.2f}–{fragment["end"]/1000:.2f} s',fragment['before'],fragment['after'],
                description(alternatives[0]) if alternatives else '',
                '\n\n'.join(description(a) for a in alternatives[1:]),
                ('ZMIENIONO\n' if fragment['applied'] else 'DO ODSŁUCHU\n')+fragment['reason']]
            tooltip='Kontekst: '+fragment['context']+'\n\n'+'\n'.join(a['name']+': '+a['directory'] for a in alternatives)
            for col,value in enumerate(values):
                item=QTableWidgetItem(value);item.setToolTip(tooltip);table.setItem(row,col,item)
            table.setRowHeight(row,115)
        table.cellDoubleClicked.connect(lambda row,col:self.owner.play_interval(fragments[row]['start'],fragments[row]['end']))
        layout.addWidget(table)
        selection_row=QHBoxLayout();alternatives_combo=QComboBox()
        alternatives_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        alternatives_combo.setMinimumContentsLength(25)
        apply_choice=QPushButton('Use selected ASR phrase');play_choice=QPushButton('Listen to selected cue')
        choice_status=text_label('Choose a row and an ASR alternative. Human choices are saved with provenance and can be undone.')
        for widget in (alternatives_combo,apply_choice,play_choice):selection_row.addWidget(widget)
        layout.addLayout(selection_row);layout.addWidget(choice_status)
        def update_choices(*_):
            row=table.currentRow();alternatives_combo.clear()
            if row>=0:
                alternatives_combo.addItem('Original baseline • '+fragments[row]['before'],-1)
                for index,alternative in enumerate(fragments[row]['alternatives']):
                    if alternative['text'] and alternative['usable'] and alternative['temporal']:
                        alternatives_combo.addItem(alternative['name']+' • '+alternative['text'],index)
            apply_choice.setEnabled(row>=0 and alternatives_combo.count()>0 and not self.owner.busy)
            play_choice.setEnabled(row>=0)
        def choose():
            def operation():
                from .source_choices import choice_preview
                from .core import invalidate
                if self.owner.busy:raise ValueError('Wait for the running task to finish')
                self.owner.editor_tools.commit()
                job=self.last_job()
                if not job:raise ValueError('No pipeline job in this project')
                preview=choice_preview(self.owner.project,result,table.currentRow(),alternatives_combo.currentData(),job)
                if preview is None:return
                self.owner.checkpoint();target=preview['target'];target.text=preview['text']
                invalidate(target);target.status='manual';target.source='manual-asr-choice'
                target.notes.append('Human-selected ASR phrase; source: '+preview['record']['model'])
                job.setdefault('manual_source_choices',[]).append(preview['record'])
                self.owner.changed('manual source phrase choice')
                choice_status.setText('Applied to the active track. Undo is available; export again to update subtitle files.')
            self.owner.guarded(operation)
        table.currentCellChanged.connect(update_choices);apply_choice.clicked.connect(choose)
        play_choice.clicked.connect(lambda:self.owner.play_interval(fragments[table.currentRow()]['start'],fragments[table.currentRow()]['end']))
        update_choices()
        self.source_choice_combo=alternatives_combo;self.source_choice_button=apply_choice
        if not fragments: layout.addWidget(text_label('Brak lokalnych różnic do oceny w dostępnych hipotezach. Nie oznacza to, że transkrypcja jest bezbłędna.'))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);dialog.show();self.retry_dialog=dialog

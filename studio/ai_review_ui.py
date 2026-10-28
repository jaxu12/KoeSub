from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox,QComboBox,QHBoxLayout,QLabel,QPlainTextEdit,QPushButton,
                               QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from .ai_review import apply_proposals,apply_verified_automatically,source_key
from .core import now,uid


class AIReviewPanel(QWidget):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner=owner;self.ids=[]
        layout=QVBoxLayout(self)
        note=QLabel('AI porównuje JP z EN. Tryb „Sprawdź i popraw” stosuje propozycje potwierdzone kontrolą JP → EN. '
                    'Ręczne EN i propozycje wymagające odsłuchu pozostają do decyzji. Zmiany można cofnąć.')
        note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout()
        self.backend=QComboBox();self.backend.addItem('Wbudowany GGUF','embedded');self.backend.addItem('LM Studio','lmstudio')
        self.model=QComboBox();self.mode=QComboBox()
        for label,key in [('Fast • podejrzane','fast'),('Full • wszystkie','full'),('Refusal Repair','refusals'),('Hallucination Review','hallucinations')]:
            self.mode.addItem(label,key)
        self.force=QCheckBox('Oceń ponownie zapisane')
        for widget in (self.backend,self.model,self.mode,self.force): row.addWidget(widget,1)
        layout.addLayout(row)
        self.auto_apply=QCheckBox('Sprawdź i popraw • zastosuj potwierdzone zmiany automatycznie')
        self.auto_apply.setChecked(True);layout.addWidget(self.auto_apply)
        self.film_context=QCheckBox('Uwzględnij cały film • temat, nazwy i spójność wypowiedzi')
        self.film_context.setChecked(True);layout.addWidget(self.film_context)
        self.context_label=QLabel('Kontekst całego filmu pojawi się po analizie.')
        self.context_label.setTextFormat(Qt.TextFormat.PlainText)
        self.context_label.setWordWrap(True);self.context_label.setMaximumHeight(65);layout.addWidget(self.context_label)
        self.auto_apply.toggled.connect(lambda value:self.start_button.setText('Sprawdź i popraw' if value else 'Zbierz propozycje AI'))
        self.start_button=QPushButton('Sprawdź i popraw');self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.start);layout.addWidget(self.start_button)
        row=QHBoxLayout();self.filter=QComboBox()
        for label,key in [('Propozycje do decyzji','pending'),('Wszystkie oceny','all'),('Zaakceptowane','accepted'),('Odrzucone','rejected'),('Nieaktualne','stale')]:
            self.filter.addItem(label,key)
        self.summary=QLabel();row.addWidget(self.filter);row.addWidget(self.summary,1);layout.addLayout(row)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['#','Typ / stan','JP','EN przed / obecne','Propozycja / po poprawce'])
        for col,width in enumerate((45,180,320,350,350)): self.table.setColumnWidth(col,width)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self.details)
        self.table.cellDoubleClicked.connect(lambda *_:self.open_editor())
        layout.addWidget(self.table,1)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumHeight(180);layout.addWidget(self.detail)
        row=QHBoxLayout()
        for label,fn in [('Zastosuj wybrane propozycje',self.accept),('Odrzuć wybrane',self.reject),
                         ('Otwórz w edytorze',self.open_editor),('Odsłuch',self.play)]:
            b=QPushButton(label);b.clicked.connect(fn);row.addWidget(b);owner.mutating.append(b)
            if fn==self.accept: self.accept_button=b
            if fn==self.reject: self.reject_button=b
        layout.addLayout(row)
        owner.mutating.append(self.start_button)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.backend.currentIndexChanged.connect(self.refresh_models)

    def refresh_models(self,*_):
        selected=self.model.currentData() or self.owner.settings.llm_model
        self.model.clear()
        if self.backend.currentData()=='embedded':
            models=[(m.name,m.path) for m in self.owner.models if m.kind=='LLM / GGUF']
        else:
            models=[(self.owner.llm_combo.itemText(i),self.owner.llm_combo.itemText(i)) for i in range(self.owner.llm_combo.count())]
        for name,value in models: self.model.addItem(name,value)
        self.model.setCurrentIndex(max(0,self.model.findData(selected)))

    def set_busy(self,busy):
        for widget in (self.backend,self.model,self.mode,self.force,self.auto_apply,self.film_context): widget.setEnabled(not busy)
        self.update_action_state()

    def refresh(self,*_):
        track=self.owner.project.active;self.ids=[]
        job=next((j for j in reversed(self.owner.project.jobs) if track and j.get('type')=='ai_review'
                  and j.get('track_id')==track.id and j.get('film_context')),None)
        context='Kontekst • hipoteza z dostępnego JP: '+job['film_context'] if job else 'Kontekst dostępnych napisów pojawi się po analizie.'
        self.context_label.setText(context);self.context_label.setToolTip(context+'\n\n'+(job.get('continuity_notes','') if job else ''))
        rows=[];total=0
        if track:
            for i,s in enumerate(track.segments):
                result=self.owner.project.ai_reviews.get(s.id)
                if not result or result.get('track_id')!=track.id: continue
                total+=1
                state=result.get('decision','pending')
                if state=='pending' and (result.get('source_key')!=source_key(track,i) or result.get('protocol_version')!=2 or not self.global_current(result)): state='stale'
                mode=self.filter.currentData()
                if mode!='all' and (mode!=state or mode=='pending' and result['status']=='ok'): continue
                self.ids.append(s.id)
                category={'none':'Bez problemu','meaning':'Znaczenie','negation':'Negacja','speaker':'Mówca',
                          'omission':'Pominięcie','addition':'Dopisanie','name':'Nazwy','tone':'Ton','refusal':'Odmowa',
                          'romanization':'Romanizacja','language':'Język','uncertain':'Niepewne'}.get(result['issue_type'],result['issue_type'])
                decision={'pending':'Do decyzji','accepted':'Przyjęto','rejected':'Odrzucono','stale':'Nieaktualne'}[state]
                rows.append((str(i+1),category+' / '+decision,s.text,result['current_translation'] if state=='accepted' else s.translation,result['suggested_translation']))
        self.table.blockSignals(True);self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):
                item=QTableWidgetItem(value);item.setToolTip(value);self.table.setItem(i,j,item)
            self.table.setRowHeight(i,70)
        self.table.blockSignals(False)
        applied=sum(r.get('applied_automatically',False) for r in self.owner.project.ai_reviews.values() if track and r.get('track_id')==track.id)
        self.summary.setText(f'Oceniono: {total} • zmieniono automatycznie: {applied} • w tym widoku: {len(rows)}')
        if rows: self.table.selectRow(0)
        self.details()

    def selected_ids(self):
        return [self.ids[i.row()] for i in self.table.selectionModel().selectedRows() if 0<=i.row()<len(self.ids)]

    def global_current(self,result):
        from .context_review import source_digest
        return not result.get('global_source_key') or (self.owner.project.active is not None and result['global_source_key']==source_digest(self.owner.project.active))

    def context_message(self,message):
        text='Kontekst • hipoteza z dostępnego JP: '+message['overview']
        self.context_label.setText(text);self.context_label.setToolTip(text+'\n\n'+message['continuity_notes'])
        self.owner.job['film_context']=message['overview'];self.owner.job['continuity_notes']=message['continuity_notes']
        self.owner.save(reason='translation checkpoint')

    def details(self):
        self.update_action_state()
        row=self.table.currentRow()
        if not 0<=row<len(self.ids): self.detail.clear();return
        result=self.owner.project.ai_reviews[self.ids[row]]
        self.detail.setPlainText('Uzasadnienie: '+result['reason']+'\n\nŹródłowe JP: '+result['source_text']+
             '\nOceniane EN: '+result['current_translation']+'\nPropozycja: '+result['suggested_translation']+
             '\n\nWymaga odsłuchu: '+('tak' if result['requires_audio_review'] else 'model nie zgłosił takiej potrzeby')+
             '\nModel: '+result.get('model',''))

    def update_action_state(self):
        ids=self.selected_ids();project=self.owner.project
        indices={s.id:i for i,s in enumerate(project.active.segments)} if project.active else {}
        applicable=bool(ids) and not self.owner.busy
        rejectable=applicable
        for key in ids:
            result=project.ai_reviews[key]
            rejectable=rejectable and result.get('decision')=='pending'
            applicable=applicable and bool(result.get('suggested_translation')) and result.get('verification')=='faithful' and result.get('protocol_version')==2 and result.get('decision')=='pending' and key in indices and result.get('source_key')==source_key(project.active,indices[key])
            applicable=applicable and self.global_current(result)
        self.accept_button.setEnabled(bool(applicable));self.reject_button.setEnabled(bool(rejectable))

    def start(self):
        if self.owner.busy: return
        def work():
            owner=self.owner;owner.editor_tools.commit()
            if not owner.project.active or not owner.project.active.segments: raise ValueError('Wybierz ścieżkę z JP / EN.')
            model=self.model.currentData()
            if not model: raise ValueError('Wybierz model do review.')
            spec={'action':'review','backend':self.backend.currentData(),'model':model,'model_path':model,
                  'executable':owner.settings.llm_exe,'device':owner.llm_device_combo.currentData(),
                  'context_length':owner.llm_context.currentData(),'batch_size':1,
                  'url':owner.lm_url.text().strip(),'cache_dir':owner.settings.cache_dir,
                  'reserve_gib':owner.settings.reserve_gib,'mode':self.mode.currentData(),
                  'force':self.force.isChecked(),'job_id':uid(),'project':owner.project.to_dict()}
            spec['film_context']=self.film_context.isChecked()
            if spec['backend']=='embedded':
                from .embedded_llm import model_identity
                model_identity(spec)
            owner.checkpoint();owner.worker_error=''
            owner.job={'id':spec['job_id'],'type':'ai_review','status':'running','created':now(),
                       'track_id':owner.project.active.id,'errors':[],'mode':spec['mode'],'auto_apply':self.auto_apply.isChecked()}
            owner.project.jobs.append(owner.job);owner.save(reason='AI review started')
            owner.run_worker(spec,self.finished)
        self.owner.guarded(work)

    def message(self,message):
        self.owner.project.ai_reviews[message['id']]=message['result']
        self.owner.save(reason='translation checkpoint');self.refresh()

    def finished(self,code,output,cancelled):
        owner=self.owner
        if cancelled: owner.finish_cancelled();return
        if code: raise ValueError(owner.worker_error or output[-2000:])
        owner.job.update(status='needs_review' if owner.job['errors'] else 'completed',finished=now())
        applied=0
        if owner.job.get('auto_apply'):
            from .core import Project
            candidate=Project.from_dict(owner.project.to_dict())
            applied=apply_verified_automatically(candidate)
            if applied:
                job_id=owner.job['id'];owner.checkpoint();owner.project=candidate
                owner.job=next(j for j in candidate.jobs if j['id']==job_id)
                owner.refresh()
        owner.job['applied_changes']=applied
        if applied: self.filter.setCurrentIndex(self.filter.findData('accepted'))
        owner.save(reason='AI review completed');owner.progress.setRange(0,100);owner.progress.setValue(100)
        errors=len(owner.job['errors'])
        owner.progress_label.setText(f'AI Review • zmieniono EN: {applied} • błędy: {errors} • pozostałe propozycje do decyzji');self.refresh()

    def accept(self):
        if self.owner.busy: return
        def work():
            self.owner.editor_tools.commit()
            ids=self.selected_ids()
            if not ids: return
            # Apply to a copy to validate every selected proposal before committing history.
            from .core import Project
            candidate=Project.from_dict(self.owner.project.to_dict())
            apply_proposals(candidate,ids)
            self.owner.checkpoint();self.owner.project=candidate;self.owner.changed('accept AI proposals')
        self.owner.guarded(work)

    def reject(self):
        if self.owner.busy: return
        def work():
            self.owner.editor_tools.commit()
            ids=self.selected_ids()
            if not ids: return
            if any(self.owner.project.ai_reviews[key].get('decision')!='pending' for key in ids): return
            self.owner.checkpoint()
            for key in ids:
                result=self.owner.project.ai_reviews[key]
                result.update(decision='rejected',decided_at=now())
            self.owner.changed('reject AI proposals')
        self.owner.guarded(work)

    def open_editor(self):
        ids=self.selected_ids()
        if ids and self.owner.project.active:
            row=next((i for i,s in enumerate(self.owner.project.active.segments) if s.id==ids[0]),None)
            if row is not None:
                self.owner.editor_tools.search.clear();self.owner.editor_tools.filter.setCurrentIndex(0)
                self.owner.review_selected(row,0)

    def play(self):
        ids=self.selected_ids()
        if ids and self.owner.project.active:
            s=next(s for s in self.owner.project.active.segments if s.id==ids[0])
            self.owner.play_range(s.start,s.end)

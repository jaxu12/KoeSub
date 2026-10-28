import json
from pathlib import Path

from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import QCheckBox,QComboBox,QDialog,QHBoxLayout,QInputDialog,QLabel,QLineEdit,QMenu,QMessageBox,QPushButton

from .core import atomic_text,invalidate,parse_time,time_text
from .editing_ui import CleanupDialog,ShiftDialog
from .review import ReviewSettings
from .waveform_ui import WaveformController,WaveformWidget
from .cache_tools import show_cache_dialog


class EditorTools:
    def __init__(self,owner,data):
        self.owner,self.data=owner,Path(data)
        self.editing_id=None;self.editing_track=None;self.dirty=False;self.filling=False
        self.pending_imports=[]
        self.last_wave_source=None
        row=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('Szukaj JP, EN lub czasu • Ctrl+F')
        self.filter=QComboBox()
        for title,key in [('Wszystkie','all'),('Z ostrzeżeniami','issues'),('Nieprzejrzane','unreviewed'),('Zakładki','bookmarks'),('Brak EN','missing_en')]:
            self.filter.addItem(title,key)
        self.count=QLabel()
        row.addWidget(self.search,1);row.addWidget(self.filter);row.addWidget(self.count)
        for title,direction in [('↑',-1),('↓',1)]:
            b=QPushButton(title);b.setMaximumWidth(36);b.clicked.connect(lambda checked=False,d=direction:self.navigate(d))
            row.addWidget(b)
        owner.editor_layout.insertLayout(0,row)
        self.bookmark=QPushButton('☆');self.bookmark.setMaximumWidth(40);self.bookmark.setToolTip('Zakładka • Ctrl+M')
        self.reviewed=QCheckBox('Sprawdzony')
        owner.timestamp_layout.addWidget(self.bookmark);owner.timestamp_layout.addWidget(self.reviewed)
        self.bookmark.clicked.connect(self.toggle_bookmark)
        self.reviewed.clicked.connect(lambda checked:self.mark_reviewed(checked))
        self.search.textChanged.connect(self.apply_filter);self.filter.currentIndexChanged.connect(self.apply_filter)
        for editor in (owner.jp_edit,owner.en_edit):
            editor.textChanged.connect(self.mark_dirty)
        for editor in (owner.start_edit,owner.end_edit):
            editor.textEdited.connect(self.mark_dirty)
        self.waveform=WaveformWidget(owner)
        owner.media_layout.insertWidget(4,self.waveform)
        self.waveform.seekRequested.connect(owner.seek_to)
        self.waveform.rangeSelected.connect(self.range_selected)
        self.wave=WaveformController(owner,self.waveform)
        self.build_menu()
        owner.setAcceptDrops(True)

    def build_menu(self):
        owner=self.owner
        project=owner.menuBar().addMenu('Projekt')
        self.recent_menu=project.addMenu('Ostatnie projekty')
        tools=owner.menuBar().addMenu('Narzędzia')
        definitions=[(tools,'Typowe poprawki…','Ctrl+Shift+F',self.cleanup,True),
                     (tools,'Przesuń czasy…','Ctrl+Shift+T',self.shift,True),
                     (tools,'Zakładka','Ctrl+M',self.toggle_bookmark,True),
                     (tools,'Oznacz jako sprawdzone','Ctrl+Shift+Return',lambda:self.mark_reviewed(True),True),
                     (tools,'Notatka do napisu…','Ctrl+Shift+M',self.comment,True),
                     (tools,'Zarządzaj cache…',None,lambda:show_cache_dialog(owner),True),
                     (tools,'Odrzuć edycję pól',None,self.discard,True),
                     (tools,'Następny problem','F8',lambda:self.navigate(1,True),False),
                     (tools,'Poprzedni problem','Shift+F8',lambda:self.navigate(-1,True),False)]
        for menu,title,shortcut,fn,mutating in definitions:
            action=QAction(title,owner)
            if shortcut: action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(fn);menu.addAction(action)
            if mutating: owner.mutating.append(action)
        for shortcut,fn in [('Ctrl+F',self.focus_search),('F3',lambda:self.navigate(1)),
                            ('Shift+F3',lambda:self.navigate(-1)),('Ctrl+Return',owner.apply_edit),
                            ('Ctrl+O',owner.open_project),('Ctrl+I',owner.import_media),
                            ('Ctrl+Shift+S',owner.save_as),('Ctrl+L',owner.play_segment),('F1',self.help)]:
            action=QAction(owner);action.setShortcut(QKeySequence(shortcut));action.triggered.connect(fn);owner.addAction(action)
        self.reload_recent()

    def mark_dirty(self,*_):
        if not self.filling and not self.owner.loading and not self.owner.busy:
            self.dirty=True
            self.owner.statusBar().showMessage('Edycja pól • zapis przy zmianie napisu lub Ctrl+Enter')

    def old_segment(self):
        track=next((t for t in self.owner.project.tracks if t.id==self.editing_track),None)
        return track,next((s for s in track.segments if s.id==self.editing_id),None) if track else None

    def commit(self,refresh=True):
        owner=self.owner
        if not self.dirty or self.filling or owner.busy:
            return False
        track,segment=self.old_segment()
        if segment is None:
            self.dirty=False;return False
        start,end=parse_time(owner.start_edit.text()),parse_time(owner.end_edit.text())
        if end<=start:
            raise ValueError('Koniec musi być późniejszy od początku. Popraw czas lub wybierz Narzędzia → Odrzuć edycję pól.')
        jp,en=owner.jp_edit.toPlainText(),owner.en_edit.toPlainText()
        self.dirty=False
        if (start,end,jp,en)==(segment.start,segment.end,segment.text,segment.translation):
            return False
        owner.checkpoint()
        if jp!=segment.text:
            for s in track.segments: invalidate(s)
        if en!=segment.translation:
            segment.status='manual' if en.strip() else 'unchecked';segment.translation_key=''
        segment.start,segment.end,segment.text,segment.translation=start,end,jp,en
        segment.review_status='unreviewed'
        if refresh:
            owner.changed('edit subtitle')
        else:
            owner.save(reason='edit subtitle')
        return True

    def before_selection(self):
        current=self.owner.current_segment()
        if self.dirty and current and current.id!=self.editing_id:
            try:
                changed=self.commit(False)
            except ValueError as exc:
                table=self.owner.segments_table
                track,old=self.old_segment()
                if old and track is self.owner.project.active:
                    table.blockSignals(True);table.selectRow(track.segments.index(old));table.blockSignals(False)
                self.owner.fail(exc)
                return False
            if changed: QTimer.singleShot(0,self.owner.refresh)
        self.filling=True
        return True

    def loaded(self,segment):
        self.editing_id=segment.id if segment else None
        self.editing_track=self.owner.project.active_track
        self.dirty=False;self.filling=False
        if segment is None:
            self.filling=True
            for edit in (self.owner.jp_edit,self.owner.en_edit,self.owner.start_edit,self.owner.end_edit): edit.clear()
            self.filling=False
        for edit in (self.owner.jp_edit,self.owner.en_edit,self.owner.start_edit,self.owner.end_edit):
            edit.setEnabled(bool(segment) and not self.owner.busy)
        self.reviewed.setChecked(bool(segment and segment.review_status=='reviewed'))
        self.bookmark.setText('★' if segment and segment.bookmarked else '☆')
        self.bookmark.setToolTip((segment.comment+'\n' if segment and segment.comment else '')+'Zakładka • Ctrl+M')

    def discard(self):
        self.dirty=False;self.owner.selection_changed()

    def apply_filter(self,*_):
        if self.owner.loading:
            return
        table=self.owner.segments_table
        segments=self.owner.project.active.segments if self.owner.project.active else []
        needle=self.search.text().casefold().strip();mode=self.filter.currentData()
        visible=[]
        for i,s in enumerate(segments):
            text=' '.join((s.text,s.translation,time_text(s.start),time_text(s.end),s.comment)).casefold()
            issues=self.owner.quality_rows[i]['issues'] if i<len(self.owner.quality_rows) else []
            show=(not needle or needle in text) and (mode=='all' or mode=='issues' and bool(issues) or
                  mode=='unreviewed' and s.review_status!='reviewed' or mode=='bookmarks' and s.bookmarked or
                  mode=='missing_en' and not s.translation.strip())
            table.setRowHidden(i,not show)
            if show: visible.append(i)
        self.count.setText(f'{len(visible)}/{len(segments)}')
        if table.currentRow() not in visible and visible:
            table.selectRow(visible[0])
        elif not visible:
            try:
                self.commit(False)
            except ValueError as exc:
                if table.currentRow()>=0: table.setRowHidden(table.currentRow(),False)
                self.owner.fail(exc);return []
            table.blockSignals(True);table.clearSelection();table.setCurrentCell(-1,-1);table.blockSignals(False)
            self.loaded(None);self.owner.issue_label.setText('Brak pasujących napisów. Zmień filtr lub wyszukiwanie.')
        return visible

    def navigate(self,direction,problems=False):
        owner=self.owner
        if not owner.project.active:
            return
        owner.tabs.setCurrentIndex(0)
        rows=[i for i in range(len(owner.project.active.segments)) if not owner.segments_table.isRowHidden(i) and
              (not problems or owner.quality_rows[i]['issues'])]
        if not rows: return
        current=owner.segments_table.currentRow()
        choices=[i for i in rows if (i>current if direction>0 else i<current)]
        row=(choices[0] if direction>0 else choices[-1]) if choices else (rows[0] if direction>0 else rows[-1])
        owner.segments_table.selectRow(row);owner.segments_table.scrollToItem(owner.segments_table.item(row,0))

    def focus_search(self):
        self.owner.tabs.setCurrentIndex(0);self.search.setFocus();self.search.selectAll()

    def annotate(self,fn,reason):
        if self.owner.busy: return
        def work():
            self.commit()
            rows=self.owner.selected_rows()
            if not rows or not self.owner.project.active: return
            self.owner.checkpoint()
            for i in rows: fn(self.owner.project.active.segments[i])
            self.owner.changed(reason)
        self.owner.guarded(work)

    def toggle_bookmark(self):
        segment=self.owner.current_segment()
        if segment:
            value=not segment.bookmarked
            self.annotate(lambda s:setattr(s,'bookmarked',value),'bookmark subtitles')

    def mark_reviewed(self,checked=True):
        self.annotate(lambda s:setattr(s,'review_status','reviewed' if checked else 'unreviewed'),'review acknowledgement')

    def comment(self):
        segment=self.owner.current_segment()
        if not segment or self.owner.busy: return
        value,ok=QInputDialog.getMultiLineText(self.owner,'Notatka do napisu','Notatka lokalna w projekcie:',segment.comment)
        if ok: self.annotate(lambda s:setattr(s,'comment',value),'subtitle comment')

    def apply_track(self,result,reason):
        owner=self.owner
        old=owner.project.active
        if not result or not old: return
        owner.checkpoint()
        if [(s.id,s.text) for s in old.segments]!=[(s.id,s.text) for s in result.segments]:
            for s in result.segments: invalidate(s)
        owner.project.tracks[owner.project.tracks.index(old)]=result
        self.dirty=False
        owner.changed(reason)

    def cleanup(self):
        if self.owner.busy or not self.owner.project.active: return
        def work():
            self.commit()
            dialog=CleanupDialog(self.owner,self.owner.project.active,ReviewSettings.load(self.owner.project.review_settings),self.owner.project.duration)
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.apply_track(dialog.result_track,'common subtitle fixes')
        self.owner.guarded(work)

    def shift(self):
        if self.owner.busy or not self.owner.project.active or not self.owner.project.active.segments: return
        def work():
            self.commit()
            dialog=ShiftDialog(self.owner,self.owner.project.active,self.owner.selected_rows(),self.owner.player.position())
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.apply_track(dialog.result_track,'shift subtitle times')
        self.owner.guarded(work)

    def range_selected(self,start,end):
        if self.owner.busy: return
        for a,b in [(self.owner.asr_start,self.owner.asr_length),(self.owner.pipeline_panel.start,self.owner.pipeline_panel.length)]:
            a.setValue(start/1000);b.setValue((end-start)/1000)
        self.owner.seek_to(start)
        self.owner.statusBar().showMessage(f'Zakres testu: {time_text(start)} → {time_text(end)}',5000)

    def remember_project(self):
        if not self.owner.store: return
        path=self.data/'recent_projects.json'
        try: recent=json.loads(path.read_text('utf8'))
        except (OSError,ValueError): recent=[]
        if not isinstance(recent,list): recent=[]
        record={'path':str(self.owner.store.path.resolve()),'name':self.owner.project.name}
        updated=[record]+[v for v in recent if isinstance(v,dict) and v.get('path')!=record['path']]
        if updated[:12]!=recent: atomic_text(path,json.dumps(updated[:12],ensure_ascii=False,indent=2))
        self.reload_recent()

    def reload_recent(self):
        self.recent_menu.clear()
        try: recent=json.loads((self.data/'recent_projects.json').read_text('utf8'))
        except (OSError,ValueError): recent=[]
        if not isinstance(recent,list): recent=[]
        for item in recent[:12]:
            if not isinstance(item,dict) or not isinstance(item.get('path'),str): continue
            path=Path(item['path'])
            name=item.get('name',path.stem)
            action=self.recent_menu.addAction(name if isinstance(name,str) else path.stem)
            action.setToolTip(str(path));action.setEnabled(path.is_file())
            action.triggered.connect(lambda checked=False,p=path:self.owner.guarded(lambda:self.owner.open_project_path(p)))

    def accepts(self,paths):
        return not self.owner.busy and bool(paths) and all(Path(p).suffix.lower() in
              {'.mp4','.mkv','.avi','.mov','.webm','.wav','.flac','.mp3','.m4a','.ogg','.srt','.ass','.ssa','.sqlite'} for p in paths)

    def import_paths(self,paths):
        if not self.accepts(paths): raise ValueError('Nieobsługiwane pliki lub trwa zadanie.')
        paths=[Path(p) for p in paths]
        projects=[p for p in paths if p.suffix.lower()=='.sqlite']
        subtitles=[p for p in paths if p.suffix.lower() in {'.srt','.ass','.ssa'}]
        media=[p for p in paths if p not in projects+subtitles]
        if projects:
            if len(paths)!=1: raise ValueError('Projekt otwieraj osobno od pozostałych plików.')
            self.owner.open_project_path(projects[0]);return
        if len(media)>1: raise ValueError('Przeciągnij jeden film i dowolną liczbę plików napisów.')
        self.commit()
        if media: self.owner.import_media_path(media[0])
        self.pending_imports.extend(subtitles);self.drain_imports()

    def drain_imports(self):
        if not self.pending_imports: return
        if self.owner.busy:
            QTimer.singleShot(150,self.drain_imports);return
        path=self.pending_imports.pop(0)
        self.owner.guarded(lambda:self.owner.import_subtitle_path(path))
        QTimer.singleShot(0,self.drain_imports)

    def help(self):
        QMessageBox.information(self.owner,'Skróty i waveform',
            'Ctrl+F: szukaj • F3 / Shift+F3: kolejne wyniki\nF8 / Shift+F8: kolejny / poprzedni problem\n'
            'Ctrl+Enter: zastosuj pola • Ctrl+Shift+Enter: sprawdzony\nCtrl+M: zakładka • Ctrl+Shift+M: notatka\n'
            'Ctrl+L: odsłuch napisu • Ctrl+Shift+T: przesunięcie czasów\nCtrl+Shift+F: typowe poprawki\n'
            'Waveform: klik przewija, przeciągnięcie wybiera zakres, kółko zmienia zoom, prawy klik pokazuje cały film.')

    def sync_wave(self):
        source=(self.owner.project.media,self.owner.project.audio_track)
        if source!=self.last_wave_source:
            self.wave.stop();self.wave.key=None;self.waveform.peaks=b'';self.waveform.duration=0
            self.last_wave_source=source;self.wave.schedule()

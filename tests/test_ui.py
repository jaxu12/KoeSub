import os
import sys
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PySide6.QtWidgets import QApplication
from studio import storage, ui
from studio.core import Project, ProjectStore, Segment, Track
from studio.review_ui import SplitPreviewDialog
from studio.storage import Settings
from tests.test_source_evaluation import study_files


@pytest.fixture(scope='module')
def app():
    value = QApplication.instance() or QApplication([])
    ui.setup_fonts(value)
    yield value


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(ui, 'DATA', tmp_path)
    monkeypatch.setattr(storage, 'DATA', tmp_path)
    monkeypatch.setattr(Settings, 'load', classmethod(lambda cls: Settings(cache_dir=str(tmp_path/'cache'))))
    value = ui.Window()
    failures = []
    value.fail = lambda exc: failures.append(str(exc))
    yield value, failures
    assert not failures, failures
    value.close()


def test_editor_save_undo_and_manual_comparison(window, app):
    w, errors = window
    w.demo()
    assert w.segments_table.rowCount() == 5
    w.segments_table.selectRow(0)
    w.jp_edit.setPlainText('こんにちは。')
    w.en_edit.setPlainText('Hello.')
    w.apply_edit()
    assert w.project.active.segments[0].translation == 'Hello.'
    assert ProjectStore(w.store.path).load().active.segments[0].text == 'こんにちは。'
    w.undo()
    assert w.project.active.segments[0].text == '今日はいい天気ですね。'
    w.redo()
    assert w.project.active.segments[0].text == 'こんにちは。'
    w.compare()
    assert w.groups
    for group in w.groups:
        group['choice'] = 'a' if group['a'] else 'b'
    w.build_selected_track()
    assert len(w.project.tracks) == 3
    assert all(s.parents for s in w.project.active.segments)


def test_waveform_stop_tolerates_qprocess_deleted_with_its_owner(window,app):
    from PySide6.QtCore import QProcess
    from shiboken6 import delete
    w,_=window
    controller=w.editor_tools.wave
    process=QProcess(w)
    controller.process=process
    delete(process)
    controller.stop()
    assert controller.process is None


def test_embedded_is_default_and_lm_studio_is_secondary(window,app):
    w,errors=window
    assert w.translation_backend.currentData()=='embedded'
    assert not w.native_panel.isHidden()
    assert w.server_panel.isHidden()
    w.translation_backend.setCurrentIndex(1)
    assert w.translation_backend.currentData()=='lmstudio'
    assert w.native_panel.isHidden()
    assert not w.server_panel.isHidden()


def test_asr_disables_unavailable_backend_and_blocks_before_inference(window, tmp_path):
    w, errors = window
    w.crisp_device.setCurrentText('cuda')
    w.apply_crisp_backends('ggml backends : cpu,vulkan')
    assert w.crisp_device.currentText() == 'vulkan'
    assert not w.crisp_device.model().item(w.crisp_device.findText('cuda')).isEnabled()
    assert Settings.load().crisp_gpu_backend == 'vulkan'
    w.asr_engine.setCurrentIndex(2)
    assert not w.device.isEnabled() and not w.compute.isEnabled()
    assert w.crisp_device.isEnabled()
    w.set_busy(True)
    w.set_busy(False)
    assert not w.device.isEnabled() and w.crisp_device.isEnabled()
    w.job = {'output': str(tmp_path), 'crisp_gpu_backend': 'cuda'}
    with pytest.raises(ValueError, match='CUDA'):
        w.asr_version_ready(0, 'ggml backends : cpu,vulkan', False, None)
    assert w.runner.process is None


def test_cancel_background_process_keeps_gui_responsive(window, app):
    w, errors = window
    results = []
    w.runner.start(sys.executable, ['-c', 'import time; time.sleep(30)'],
                   lambda code, output, cancelled: results.append(cancelled))
    for _ in range(10):
        app.processEvents()
        time.sleep(.01)
    assert w.busy
    w.runner.cancel()
    deadline = time.monotonic()+8
    while w.runner.process is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert results == [True]
    assert not w.busy


def test_quality_filter_navigation_split_cancel_commit_and_undo(window, app, monkeypatch):
    w, errors = window
    bad = Segment(0, 3000, '今日は晴れです。明日は雨です。',
                  translation='This is a very long subtitle that does not fit on one line. Tomorrow there will be more rain.')
    normal = Segment(4000, 6000, 'はい。', translation='Yes.')
    w.project = Project()
    w.project.add_track(Track('review', [bad, normal]))
    w.changed('test review')
    assert w.quality_table.rowCount() == 1
    assert w.quality_index() == 0
    assert 'za szybko' in w.quality_detail.toPlainText()
    w.open_quality_editor()
    assert w.current_segment().id == bad.id
    w.quality_only_issues.setChecked(False)
    assert w.quality_table.rowCount() == 2
    monkeypatch.setattr(SplitPreviewDialog, 'exec', lambda self: self.DialogCode.Rejected)
    w.split_quality()
    assert len(w.project.active.segments) == 2
    original = w.project.to_dict()
    monkeypatch.setattr(SplitPreviewDialog, 'exec', lambda self: self.DialogCode.Accepted)
    w.split_quality()
    assert len(w.project.active.segments) == 3
    assert all(s.translation for s in w.project.active.segments)
    assert ProjectStore(w.store.path).load().active.segments[0].parents == [bad.id]
    w.undo()
    assert w.project.to_dict() == original


def test_split_preview_updates_metrics_and_manual_points(window, app):
    w, _ = window
    segment = Segment(1000, 5000, 'こんにちは。さようなら。', translation='Hello there. Goodbye now.')
    from studio.review import ReviewSettings
    dialog = SplitPreviewDialog(w, segment, ReviewSettings())
    assert dialog.parts and 'zn./s' in dialog.preview.toPlainText()
    dialog.jp_point.setValue(1)
    dialog.en_point.setValue(1)
    dialog.at.setValue(1.5)
    assert dialog.parts[0].end == 1500
    assert dialog.parts[0].translation == 'H'
    dialog.close()
    invalid = SplitPreviewDialog(w, Segment(0, 2000, '   こんにちは'), ReviewSettings())
    invalid.jp_point.setValue(1)
    assert invalid.parts is None and not invalid.apply_button.isEnabled()
    invalid.close()


def test_quality_reflow_keeps_text_timing_and_undo(window, monkeypatch):
    w, _ = window
    from PySide6.QtWidgets import QDialog
    original = 'This is a longer English subtitle that needs a line break to fit within the selected limit.'
    w.project = Project()
    w.project.add_track(Track('test', [Segment(2000, 8000, '今日は晴れです。', translation=original)]))
    w.changed('test reflow')
    before = w.project.to_dict()
    monkeypatch.setattr(QDialog, 'exec', lambda self: self.DialogCode.Rejected)
    w.reflow_quality()
    assert w.project.to_dict() == before
    monkeypatch.setattr(QDialog, 'exec', lambda self: self.DialogCode.Accepted)
    w.reflow_quality()
    s = w.project.active.segments[0]
    assert s.translation.split() == original.split() and '\n' in s.translation
    assert (s.start, s.end) == (2000, 8000)
    assert s.status == 'manual'
    assert ProjectStore(w.store.path).load().active.segments[0].translation == s.translation
    w.undo()
    assert w.project.to_dict() == before


def test_pipeline_presets_and_stage_plan(window):
    w,_ = window
    panel = w.pipeline_panel
    panel.preset.setCurrentIndex(1)
    assert panel.asr_count.value()==panel.en_count.value()==1
    assert panel.review.currentData()=='rules'
    panel.preview_plan()
    quick = panel.stages.rowCount()
    panel.preset.setCurrentIndex(2)
    assert panel.asr_count.value()==panel.en_count.value()==2
    assert panel.review.currentData()=='deep'
    panel.preview_plan()
    assert panel.stages.rowCount()>quick
    panel.asr_count.setValue(3)
    assert panel.preset.currentIndex()==4
    panel.vad[2].setChecked(False)
    panel.apply_preset(4)
    assert all(v.isChecked() for v in panel.vad[:3])
    panel.asr_count.setValue(4)
    assert panel.preset.currentIndex()==3
    panel.apply_preset(0)
    assert panel.review.currentData()=='balanced'
    assert panel.preset.currentIndex()==0


def test_jp_scope_needs_no_translator_and_fixes_baseline_vad(window,tmp_path):
    from studio.storage import Model
    from studio.pipeline import plan
    w,_=window
    media=tmp_path/'source.wav';media.write_bytes(b'local media')
    base=tmp_path/'ggml-large-v3.bin';base.write_bytes(b'ggml')
    aux=tmp_path/'ggml-kotoba-whisper-v2.0.bin';aux.write_bytes(b'ggml')
    w.models=[Model(base.name,str(base),'Whisper / GGML',4),Model(aux.name,str(aux),'Whisper / GGML',4)]
    w.settings.crisp_exe=sys.executable;w.settings.llm_exe='missing-llm.exe'
    w.project=Project(media=str(media),duration=5000);w.store=ProjectStore(tmp_path/'project.sqlite')
    p=w.pipeline_panel;p.refresh_models();p.apply_preset(5)
    config=p.config('test')
    assert config['transcription_only'] and config['translations']==[] and not config['llm_keep_loaded']
    assert config['asr'][0]['model']==str(base) and config['asr'][0]['vad']
    assert config['retry_asr']['auxiliary']['model']==str(aux)
    assert config['source_review_version']==3 and config['retry_asr']['scan_first']
    assert config['retry_asr']['batch_retries'] and not config['jp_context_review']
    assert [s['id'] for s in plan(config)]==['audio','asr-0','asr-scan','asr-retry','jp-review','jp-layout','jp-export']


def test_third_asr_default_and_explicit_disabled_survive_model_refresh(window,tmp_path):
    from studio.storage import Model
    w,_=window
    paths=[tmp_path/name for name in ('ggml-large-v3.bin','ggml-kotoba-whisper.bin','qwen3-asr-1.7b-ja-anime.gguf')]
    for path in paths:path.write_bytes(b'model')
    w.settings.crisp_exe=sys.executable
    w.models=[Model(p.name,str(p),'Whisper / GGML' if p.suffix=='.bin' else 'Qwen ASR',5) for p in paths]
    panel=w.pipeline_panel;panel.refresh_models()
    assert panel.retry_third.currentData()['engine']==1
    panel.retry_third.setCurrentIndex(0);panel.refresh_models()
    assert panel.retry_third.currentData() is None


def test_retry_comparison_dialog_keeps_alternatives_and_plays_range(window,tmp_path,app):
    from studio.pipeline_worker import write_json
    from PySide6.QtWidgets import QTableWidget
    w,_=window;p=w.pipeline_panel
    folder=tmp_path/'run';(folder/'asr-retry').mkdir(parents=True)
    w.project.jobs=[{'type':'pipeline','manifest':str(folder/'manifest.json')}]
    write_json(folder/'asr-retry/result.json',{'windows':[{'start':1000,'end':5000,'before':[{'text':'元の文'}],
        'attempts':[{'usable':True,'track':{'segments':[{'text':'別の文'}]}},{'usable':False,'error':'Bad alignment'}],
        'decision':'keep baseline'}]})
    played=[];w.play_interval=lambda start,end:played.append((start,end))
    p.show_retry_results();app.processEvents()
    table=p.retry_dialog.findChild(QTableWidget)
    assert table.rowCount()==1 and table.item(0,1).text()=='元の文' and table.item(0,2).text()=='別の文'
    table.cellDoubleClicked.emit(0,0);assert played==[(1000,5000)]
    p.retry_dialog.close();app.processEvents()


def test_source_review_dialog_exposes_local_changes_provenance_and_audio(window,tmp_path,app):
    from tests.test_asr_review import example
    from studio.asr_review import review_fragments
    from studio.pipeline_worker import write_json
    from PySide6.QtWidgets import QTableWidget
    w,_=window;p=w.pipeline_panel
    base,source,scores=example();result=review_fragments(base,[source],scores,'large.bin')
    folder=tmp_path/'run';(folder/'jp-review').mkdir(parents=True)
    w.project.jobs=[{'type':'pipeline','manifest':str(folder/'manifest.json')}]
    write_json(folder/'jp-review/result.json',result)
    played=[];w.play_interval=lambda start,end:played.append((start,end))
    p.show_retry_results();app.processEvents()
    table=p.retry_dialog.findChild(QTableWidget)
    row=next(i for i in range(table.rowCount()) if table.item(i,1).text()=='を得ても')
    assert table.item(row,2).text()=='いつでも' and 'ZMIENIONO' in table.item(row,5).text()
    assert 'Kontekst:' in table.item(row,1).toolTip() and 'kotoba.bin' in table.item(row,4).text()
    table.cellDoubleClicked.emit(row,0);assert played==[(1100,5000)]
    p.retry_dialog.close();app.processEvents()


def test_human_source_phrase_selection_is_persistent_and_undoable(window,tmp_path,app):
    from tests.test_asr_review import example
    from studio.asr_review import review_fragments
    from studio.pipeline import track_from,clone_track
    from studio.pipeline_worker import write_json
    from PySide6.QtWidgets import QTableWidget
    w,errors=window;base,source,scores=example();result=review_fragments(base,[source],scores,'large.bin')
    reviewed=track_from(result['track']);final=clone_track(reviewed,'final')
    w.project=Project(duration=6000);w.project.add_track(base);w.project.add_track(reviewed);w.project.add_track(final)
    folder=tmp_path/'run';(folder/'jp-review').mkdir(parents=True)
    w.project.jobs=[{'type':'pipeline','manifest':str(folder/'manifest.json'),'status':'completed'}]
    write_json(folder/'jp-review/result.json',result)
    w.refresh();p=w.pipeline_panel;p.show_retry_results();app.processEvents()
    table=p.retry_dialog.findChild(QTableWidget)
    row=next(i for i,f in enumerate(result['fragments']) if f['before']=='の開発度')
    table.selectRow(row);p.source_choice_combo.setCurrentIndex(p.source_choice_combo.findData(1))
    old=w.project.active.segments[1].text;p.source_choice_button.click();app.processEvents()
    assert not errors and '国配列堂' in w.project.active.segments[1].text
    assert w.project.jobs[0]['manual_source_choices'][0]['model']=='kotoba.bin'
    assert ProjectStore(w.store.path).load().jobs[0]['manual_source_choices'][0]['model']=='kotoba.bin'
    assert w.project.active.segments[1].review_status=='unreviewed'
    w.undo();assert w.project.active.segments[1].text==old
    assert not w.project.jobs[0].get('manual_source_choices')
    p.retry_dialog.close();app.processEvents()


def test_pipeline_checkpoint_cancel_resume_and_manual_edit_guard(window,tmp_path,monkeypatch):
    from dataclasses import asdict
    from studio import pipeline_ui
    from studio.pipeline_worker import write_json,read_json
    w,_ = window
    panel = w.pipeline_panel
    media = tmp_path/'test.wav'
    media.write_bytes(b'audio')
    w.project = Project(media=str(media.resolve()))
    w.changed('pipeline checkpoint test')
    folder = tmp_path/'run'
    folder.mkdir()
    manifest,artifact = folder/'manifest.json',folder/'track.json'
    state = {'status':'running','config':{'media':str(media.resolve()),'audio_track':0,'output_dir':str(folder)},
             'stages':[{'id':'en-0','label':'EN','status':'running'}]}
    write_json(manifest,state)
    track = Track('EN',[Segment(0,2000,'はい。',translation='Yes.')])
    write_json(artifact,{'track':asdict(track)})
    w.job = {'id':'run','type':'pipeline','status':'running','manifest':str(manifest),
             'track_hashes':{},'stage_tracks':{}}
    w.project.jobs.append(w.job)
    message = {'type':'pipeline_checkpoint','manifest':str(manifest),'artifact':str(artifact),'stage':'en-0'}
    panel.message(message)
    panel.message(message)
    assert len(w.project.tracks)==1
    assert ProjectStore(w.store.path).load().active.segments[0].translation=='Yes.'
    panel.finished(-1,'',True)
    assert w.job['status']=='cancelled' and read_json(manifest)['status']=='cancelled'
    assert panel.resume_button.isEnabled()
    monkeypatch.setattr(pipeline_ui,'load_run',lambda path:read_json(path))
    monkeypatch.setattr(w,'guarded',lambda fn:fn())
    w.project.active.segments[0].translation='User edit.'
    with pytest.raises(ValueError,match='Edytowano'):
        panel.resume_run()
    w.project.active.segments[0].translation='Yes.'
    started = []
    monkeypatch.setattr(w,'run_worker',lambda spec,callback:started.append(spec))
    panel.resume_run()
    assert started==[{'action':'pipeline','manifest':str(manifest)}]


def test_pipeline_saved_preferences_restore_models_profiles_and_options(window):
    w,_ = window
    panel = w.pipeline_panel
    model = {'engine':2,'model':'local.bin','name':'Whisper','kind':'Whisper / GGML'}
    panel.asr_models[0].addItem('Whisper',model)
    panel.en_models[0].addItem('Qwen','local.gguf')
    panel.judge.addItem('Qwen','local.gguf')
    prefs = {'asr_count':1,'en_count':1,'review':'deep','backend':'embedded','start':2,'length':15,
             'asr':[{**model,'vad':False}],'translations':[{'model':'local.gguf','variant':3}],
             'judge_model':'local.gguf','autosplit':True,'sound':True,'export_srt':False}
    w.project = Project(pipeline_prefs=prefs)
    w.project.add_track(Track('test',[Segment(0,2000,'はい')]))
    w.changed('save pipeline preferences')
    assert panel.asr_models[0].currentData()==model and not panel.vad[0].isChecked()
    assert panel.en_models[0].currentData()=='local.gguf' and panel.variants[0].currentData()==3
    assert panel.preset.currentIndex()==3
    assert panel.autosplit.isChecked() and panel.sound.isChecked() and not panel.export.isChecked()
    assert ProjectStore(w.store.path).load().pipeline_prefs==prefs


def test_editor_search_bookmarks_and_automatic_commit_on_row_change(window,app):
    w,_=window;w.demo()
    w.segments_table.selectRow(0)
    first=w.current_segment().id
    w.en_edit.setPlainText('A saved draft.')
    w.segments_table.selectRow(1)
    app.processEvents()
    assert w.project.active.segments[0].translation=='A saved draft.'
    assert ProjectStore(w.store.path).load().active.segments[0].translation=='A saved draft.'
    w.segments_table.selectRow(0);w.editor_tools.toggle_bookmark()
    assert w.current_segment().bookmarked
    w.editor_tools.filter.setCurrentIndex(w.editor_tools.filter.findData('bookmarks'))
    assert not w.segments_table.isRowHidden(0) and w.segments_table.isRowHidden(1)
    w.editor_tools.search.setText('nothing matches this')
    assert w.current_segment() is None and not w.en_edit.isEnabled()
    w.editor_tools.search.clear()
    assert w.current_segment().id==first
    w.editor_tools.mark_reviewed(True)
    assert w.current_segment().review_status=='reviewed'


def test_process_timeout_is_failure_not_user_cancellation(window,app):
    w,_=window;outcomes=[]
    w.runner.start(sys.executable,['-c','import time; time.sleep(30)'],
                   lambda code,output,cancelled:outcomes.append((code,output,cancelled)),timeout_seconds=.1)
    deadline=time.monotonic()+8
    while w.busy and time.monotonic()<deadline:
        app.processEvents();time.sleep(.02)
    assert outcomes and outcomes[0][0]==-124 and outcomes[0][2] is False
    assert 'limit czasu' in outcomes[0][1]


def test_ai_proposal_accept_reject_and_undo(window):
    from studio.ai_review import source_key
    w,_=window
    w.project=Project();s=Segment(0,2000,'いえ。',translation='House.')
    w.project.add_track(Track('JP',[s]))
    w.project.ai_reviews[s.id]={'id':s.id,'track_id':w.project.active.id,'source_key':source_key(w.project.active,0),
         'status':'needs_review','issue_type':'meaning','reason':'Negative reply.','source_text':s.text,
         'current_translation':s.translation,'suggested_translation':'No.','requires_audio_review':False,'decision':'pending',
         'protocol_version':2,'verification':'faithful'}
    w.changed('proposal test')
    w.ai_review_panel.table.selectRow(0);w.ai_review_panel.accept()
    assert w.project.active.segments[0].translation=='No.'
    assert w.project.ai_reviews[s.id]['decision']=='accepted'
    w.undo()
    assert w.project.active.segments[0].translation=='House.'
    assert w.project.ai_reviews[s.id]['decision']=='pending'
    w.ai_review_panel.table.selectRow(0);w.ai_review_panel.reject()
    assert w.project.active.segments[0].translation=='House.'
    assert w.project.ai_reviews[s.id]['decision']=='rejected'


def test_waveform_drag_sets_both_test_ranges(window,app):
    from PySide6.QtCore import QPoint,Qt
    from PySide6.QtTest import QTest
    w,_=window;wave=w.editor_tools.waveform
    wave.resize(400,120);wave.set_peaks(bytes([50]*200),4000)
    QTest.mousePress(wave,Qt.MouseButton.LeftButton,pos=QPoint(50,40))
    QTest.mouseMove(wave,QPoint(250,40))
    QTest.mouseRelease(wave,Qt.MouseButton.LeftButton,pos=QPoint(250,40))
    assert w.asr_start.value()==.5 and w.asr_length.value()==2
    assert w.pipeline_panel.start.value()==.5 and w.pipeline_panel.length.value()==2


def test_invalid_draft_blocks_navigation_without_losing_fields(window,app):
    w,errors=window;w.demo();w.segments_table.selectRow(0)
    previous=w.current_segment().id
    w.start_edit.setText('bad time');w.editor_tools.mark_dirty()
    w.segments_table.selectRow(1)
    assert w.current_segment().id==previous and w.start_edit.text()=='bad time'
    assert errors;errors.clear()
    w.editor_tools.discard()
    assert w.start_edit.text()!='bad time'


def test_review_automatic_finish_updates_english_counter_and_supports_undo(window):
    from studio.ai_review import source_key
    w,_=window;w.demo();s=w.project.active.segments[0]
    s.text='いえ。';s.translation='House.';s.status='machine'
    w.project.ai_reviews[s.id]={'id':s.id,'track_id':w.project.active.id,'source_key':source_key(w.project.active,0),
        'decision':'pending','protocol_version':2,'verification':'faithful','status':'needs_review','issue_type':'meaning',
        'suggested_translation':'No.','current_translation':'House.','source_text':s.text,'reason':'Negative reply.',
        'requires_audio_review':False}
    w.job={'id':'auto-review','type':'ai_review','status':'running','auto_apply':True,'errors':[]}
    w.project.jobs.append(w.job);w.refresh()
    w.ai_review_panel.finished(0,'',False)
    assert w.project.active.segments[0].translation=='No.'
    assert w.project.active.segments[0].review_status=='unreviewed'
    assert w.job['applied_changes']==1 and 'zmieniono EN: 1' in w.progress_label.text()
    w.undo()
    assert w.project.active.segments[0].translation=='House.'


def test_offline_quality_ui_audits_and_rates_without_modifying_project(window,study_files,tmp_path,monkeypatch):
    from copy import deepcopy
    from studio.source_evaluation import StudyStore,quality_report
    from studio.evaluation_ui import ErrorEventDialog
    from PySide6.QtWidgets import QDialog
    w,_=window;panel=w.evaluation_panel;before=deepcopy(w.project.to_dict())
    study=study_files[2];path=tmp_path/'study.json';StudyStore(path).save(study);panel.load_study(path)
    assert 'paired listening reviews: 0' in panel.summary.text()
    assert panel.masked() and 'Hidden during reference audit' in panel.hypotheses['baseline'].toPlainText()
    panel.reviewer.setText('synthetic-test');panel.reference_note.setText('Synthetic fixture audit')
    panel.reference_listened.setChecked(True);panel.save_reference.click()
    assert not panel.has_unsaved_reference()
    assert not panel.masked() and '山田' in panel.hypotheses['baseline'].toPlainText()
    monkeypatch.setattr(ErrorEventDialog,'exec',lambda self:QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ErrorEventDialog,'values',lambda self:{'category':'name','severity':'major',
        'reference_quote':'田中','hypothesis_quote':'山田','note':'Synthetic name mismatch.'})
    panel.add_event.click()
    assert panel.events.rowCount()==1 and not panel.rating_listened.isChecked()
    panel.rating_listened.setChecked(True);panel.save_rating.click()
    panel.variants.setCurrentIndex(1);panel.rating_listened.setChecked(True);panel.save_rating.click()
    report=quality_report(StudyStore(path).load())
    assert report['paired_semantic_comparison']['improved']==1
    assert report['paired_semantic_comparison']['events_by_category']['baseline']['name']==1
    assert w.project.to_dict()==before
    panel.export_report(tmp_path/'quality-report.json');assert (tmp_path/'quality-report.md').is_file()


def test_quality_reference_drafts_block_navigation_and_close_until_saved_or_discarded(window,study_files,tmp_path):
    from studio.source_evaluation import StudyStore
    from PySide6.QtGui import QCloseEvent
    w,_=window;panel=w.evaluation_panel;path=tmp_path/'study.json';StudyStore(path).save(study_files[2]);panel.load_study(path)
    panel.reference.setPlainText('別の参照字幕です。')
    assert panel.has_unsaved_reference() and not panel.cases.isEnabled() and not panel.save_rating.isEnabled()
    event=QCloseEvent();w.closeEvent(event);assert not event.isAccepted()
    assert 'before closing' in panel.status.text()
    panel.discard_reference.click();assert not panel.has_unsaved_reference() and panel.cases.isEnabled()
    panel.reference_note.setText('An unsaved audit note')
    assert panel.has_unsaved_reference() and not panel.open_button.isEnabled()
    panel.discard_reference.click();assert not panel.has_unsaved_reference()


def test_quality_event_dialog_is_a_normal_qt_widget(window,app):
    from studio.evaluation_ui import ErrorEventDialog
    w,_=window;dialog=ErrorEventDialog(w,'田中','山田');dialog.show();app.processEvents()
    dialog.category.setCurrentIndex(dialog.category.findData('meaning'))
    assert 'fact' in dialog.definition.text() and dialog.values()['category']=='meaning'
    dialog.close()

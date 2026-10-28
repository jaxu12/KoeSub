"""Audit exports and replay immutable completed checkpoints into an isolated Qt benchmark project."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from studio import ui
from studio.core import ProjectStore, atomic_text
from studio.editing import processing_digest
from studio.pipeline_worker import read_json
from studio.review import ReviewSettings, review_track
from .verify_pipeline import audit_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir', type=Path)
    args = parser.parse_args()
    ui.DATA = args.data_dir
    app = QApplication([])
    app.setStyle('Fusion'); app.setStyleSheet(ui.STYLE); ui.setup_fonts(app)
    window = ui.Window()
    job = window.pipeline_panel.last_job()
    assert job and job['status'] in {'completed', 'needs_review'}
    state = audit_result(job['manifest'])
    assert not window.busy
    for track in window.project.tracks:
        expected = job['track_hashes'].get(track.id)
        if expected:
            assert processing_digest(track) == expected, 'Track edited after benchmark; refusing checkpoint replay'
    window.job = job
    window.project.pipeline_prefs.update(asr_count=len(state['config']['asr']),
        en_count=len(state['config']['translations']), asr=state['config']['asr'],
        translations=state['config']['translations'])
    window.pipeline_panel.project_token = None
    window.pipeline_panel.sync_project()
    failures = []
    window.fail = lambda message: failures.append(str(message))
    started = time.monotonic()
    for stage in state['stages']:
        window.pipeline_panel.message({'type': 'pipeline_checkpoint', 'manifest': job['manifest'],
                                       'artifact': stage['artifact'], 'stage': stage['id']})
        app.processEvents()
    window.pipeline_panel.finished(0, '', False)
    assert not failures, failures
    saved = ProjectStore(window.store.path).load()
    assert saved.active.id == state['final_track'] and all(s.translation for s in saved.active.segments)
    # Native computation is already complete. Report its actual original wall time,
    # never the much shorter checkpoint replay duration.
    timing = {'manifest': job['manifest'], 'project': str(window.store.path), 'media': state['config']['media'],
              'media_seconds': state['config']['duration'] / 1000, 'probe_seconds': None,
              'wall_seconds': round((datetime.fromisoformat(state['finished']) - datetime.fromisoformat(state['created'])).total_seconds(), 3),
              'wall_clock_scope': 'Original manifest creation to completion; excludes later Qt checkpoint replay',
              'checkpoint_replay_seconds': round(time.monotonic() - started, 3),
              'verification_note': 'Initial Qt benchmark reported a transient EACCES reading en-1/partial.json. '
                                   'All native stages completed. Added bounded retries for errno-only Windows locks, '
                                   'then audited exports and replayed every immutable checkpoint without rerunning models.',
              'status': state['status'], 'warnings': state['warnings'],
              'backend': {'asr': state['config']['settings']['crisp_gpu_backend'], 'llm': state['config']['settings']['llm_device']},
              'stages': [{'id': s['id'], 'label': s['label'], 'seconds': s.get('seconds', 0)} for s in state['stages']],
              'tracks': [{'id': t.id, 'name': t.name, 'cues': len(t.segments),
                          'warnings': sum(bool(r['issues']) for r in review_track(t, ReviewSettings.load(saved.review_settings), saved.duration))}
                         for t in saved.tracks]}
    atomic_text(args.data_dir / 'timings.json', json.dumps(timing, ensure_ascii=False, indent=2))
    window.tabs.setCurrentWidget(window.pipeline_panel)
    window.show(); app.processEvents()
    window.grab().save(str(args.data_dir / 'pipeline-preview.png'))
    print('Completed native run:', timing['wall_seconds'], 'seconds; Qt checkpoint replay:', timing['checkpoint_replay_seconds'], 'seconds')
    print('Tracks:', len(saved.tracks), 'cues:', len(saved.active.segments))
    window.close()


if __name__ == '__main__':
    main()

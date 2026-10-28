import contextlib
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from studio.core import Project, Segment, Track


def test_translation_worker_resumes_and_rejects_wrong_ids(tmp_path):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            target = json.loads(body['messages'][1]['content'])['target']
            requests.append(target['segment_id'])
            if target['text'] == 'api_error':
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Jinja template error')
                return
            payload = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'segment_id': target['segment_id'] if target['text'] != 'bad' else 'WRONG',
                'translation': 'Hello.'})}}]}
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    project = Project()
    project.add_track(Track('jp', [Segment(0,1000,'こんにちは'), Segment(1000,2000,'bad')]))
    spec = {'action': 'translate', 'url': f'http://127.0.0.1:{server.server_port}',
            'model': 'qwen', 'project': project.to_dict()}
    file = tmp_path/'job.json'
    try:
        file.write_text(json.dumps(spec), encoding='utf8')
        result = subprocess.run([sys.executable, '-m', 'studio.llm_worker', str(file)], capture_output=True, text=True,
                                encoding='utf8', timeout=20, cwd=Path(__file__).resolve().parents[1])
        assert result.returncode == 0, result.stderr
        messages = [json.loads(line) for line in result.stdout.splitlines()]
        assert any(m['type'] == 'translation' for m in messages), messages
        translated = next(m for m in messages if m['type'] == 'translation')
        assert len(requests) == 3  # good cue once, invalid response twice.
        assert any(m['type'] == 'segment_error' for m in messages)
        segment = spec['project']['tracks'][0]['segments'][0]
        segment.update(translation=translated['translation'], translation_key=translated['key'], status='machine')
        file.write_text(json.dumps(spec), encoding='utf8')
        result = subprocess.run([sys.executable, '-m', 'studio.llm_worker', str(file)], capture_output=True, text=True,
                                encoding='utf8', timeout=20, cwd=Path(__file__).resolve().parents[1])
        assert result.returncode == 0
        assert requests.count(segment['id']) == 1  # completed result skipped after restart.
        spec['project']['tracks'][0]['segments'][1]['text'] = 'api_error'
        file.write_text(json.dumps(spec), encoding='utf8')
        result = subprocess.run([sys.executable, '-m', 'studio.llm_worker', str(file)], capture_output=True, text=True,
                                encoding='utf8', timeout=20, cwd=Path(__file__).resolve().parents[1])
        assert result.returncode == 1
        assert 'Jinja template error' in result.stdout
    finally:
        server.shutdown()
        server.server_close()

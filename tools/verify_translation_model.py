"""Short real-model integration check on an isolated loopback port; stops its server."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from studio.core import Project, Track, load_srt
from studio.storage import ROOT, offline_env
from .serve_test_model import command


def main():
    folder = Path('D:/models/.cache/verification-translation')
    folder.mkdir(parents=True,exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        port = probe.getsockname()[1]
    args = command()
    args[args.index('--port')+1] = str(port)
    url = f'http://127.0.0.1:{port}'
    env = {**os.environ,**offline_env(),'TEMP':str(folder),'TMP':str(folder)}
    track = load_srt(Path('D:/models/.cache/verification-japanese/transcript.srt'))
    track.segments = track.segments[:2]
    project = Project(name='Real local translation verification')
    project.add_track(track)
    spec = {'action':'translate','url':url,'model':'qwen3-4b-instruct-2507','project':project.to_dict()}
    spec_path = folder/'job.json'
    spec_path.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf8')
    with (folder/'server.log').open('wb') as log:
        process = subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,env=env,cwd=folder,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            with httpx.Client(timeout=2,trust_env=False) as client:
                deadline = time.monotonic()+90
                while time.monotonic()<deadline:
                    if process.poll() is not None:
                        raise RuntimeError('Local model server exited; see server.log')
                    try:
                        if client.get(url+'/health').status_code==200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.3)
                else:
                    raise RuntimeError('Model did not become ready within 90 seconds.')
            print('Qwen 4B ready on isolated loopback port; translating two real Japanese cues.',flush=True)
            result = subprocess.run([sys.executable,'-m','studio.llm_worker',str(spec_path)],capture_output=True,
                                    env=env,cwd=ROOT,timeout=90)
            (folder/'worker.jsonl').write_bytes(result.stdout)
            (folder/'worker-stderr.log').write_bytes(result.stderr)
            messages = [json.loads(line) for line in result.stdout.decode('utf8').splitlines() if line.strip()]
            translations = [m for m in messages if m.get('type')=='translation']
            if result.returncode or len(translations)!=2:
                print(result.stdout.decode('utf8',errors='replace'))
                raise RuntimeError('Translation validation failed.')
            print('Validated translations:',len(translations))
            for item in translations:
                print(item['translation'])
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__=='__main__':
    main()

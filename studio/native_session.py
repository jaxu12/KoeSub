"""Owned, lazy local llama runtime: load once for a pipeline, release on exit/cancel."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import httpx

from .core import atomic_text, now, uid
from .process_control import ChildJob
from .storage import offline_env

ACTIVE = ContextVar('subtitle_native_session', default=None)


class NativeSession:
    def __init__(self, root):
        self.root=Path(root);self.process=None;self.job=None;self.log=None;self.client=None
        self.identity=None;self.folder=None;self.requests=0

    def close(self):
        if self.client: self.client.close();self.client=None
        if self.job: self.job.close();self.job=None
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=10);self.process=None
        if self.log: self.log.close();self.log=None
        if self.folder:
            atomic_text(self.folder/'session.json',json.dumps({'closed':now(),'requests':self.requests,
                'identity':self.identity,'pid':self.pid,'load_seconds':self.load_seconds},ensure_ascii=False,indent=2))
        self.identity=None;self.folder=None

    def ensure(self,spec,emit):
        identity=(str(Path(spec['model_path']).resolve()),spec.get('device','cuda'),int(spec.get('context_length',4096)),str(spec['executable']))
        if self.identity==identity and self.process and self.process.poll() is None: return
        self.close()
        executable=Path(spec['executable']).with_name('llama-server.exe')
        if not executable.is_file(): raise ValueError('Brak lokalnego llama-server.exe w folderze silnika.')
        self.folder=self.root/uid();self.folder.mkdir(parents=True)
        self.pid=None;self.load_seconds=None;self.requests=0;self.identity=identity
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        device=spec.get('device','cuda')
        if device not in {'cuda','vulkan','cpu'}: raise ValueError('Nieprawidłowy backend sesji LLM.')
        args=[str(executable.resolve()),'--model',identity[0],'--ctx-size',str(identity[2]),'--fit','off',
              '--n-gpu-layers','0' if device=='cpu' else '99','--device',{'cuda':'CUDA0','vulkan':'Vulkan0','cpu':'none'}[device],
              '--batch-size','256','--ubatch-size','128','--parallel','1','--host','127.0.0.1','--port',str(port),
              '--no-webui','--offline']
        atomic_text(self.folder/'command.json',json.dumps(args,ensure_ascii=False,indent=2))
        self.log=(self.folder/'engine.log').open('wb')
        started=time.monotonic()
        self.process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=self.log,stderr=subprocess.STDOUT,
            cwd=self.folder,env={**os.environ,**offline_env(),'TEMP':str(self.folder),'TMP':str(self.folder)},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.pid=self.process.pid
        self.job=ChildJob(self.process)
        self.client=httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,follow_redirects=False,
                                 timeout=httpx.Timeout(float(spec.get('timeout',240)),connect=2))
        emit('phase',message='Ładowanie wbudowanego modelu • pozostanie w pamięci do końca przebiegu…')
        while time.monotonic()-started<120:
            if self.process.poll() is not None:
                raise RuntimeError('Wbudowana sesja LLM zakończyła się podczas ładowania; sprawdź '+str(self.folder/'engine.log'))
            try:
                response=self.client.get('/health',timeout=1)
                if response.status_code==200 and response.json().get('status')=='ok':
                    self.load_seconds=round(time.monotonic()-started,3)
                    return
            except (httpx.HTTPError,ValueError): pass
            time.sleep(.1)
        raise RuntimeError('Przekroczono czas ładowania wbudowanej sesji LLM.')

    def infer(self,spec,prompt,schema,folder,emit):
        from .embedded_llm import strict_object
        try:
            self.ensure(spec,emit)
            started=time.monotonic()
            folder=Path(folder)/uid();folder.mkdir(parents=True)
            atomic_text(folder/'prompt.txt',prompt)
            atomic_text(folder/'schema.json',json.dumps(schema))
            atomic_text(folder/'transport.json',json.dumps({'mode':'owned-native-session','session':str(self.folder),
                'pid':self.process.pid,'model':self.identity[0],'device':self.identity[1]},indent=2))
            response=self.client.post('/completion',json={'prompt':prompt,'json_schema':schema,'stream':False,
                'n_predict':2048,'temperature':.1,'seed':42,'cache_prompt':False})
            response.raise_for_status()
            payload=response.json()
            if payload.get('stopped_limit') or payload.get('truncated'):
                raise ValueError('Wbudowana sesja zwróciła ucięty wynik.')
            content=payload['content']
            atomic_text(folder/'output.txt',content)
            atomic_text(folder/'timings.json',json.dumps(payload.get('timings',{}),indent=2))
            value=json.loads(content,object_pairs_hook=strict_object)
            self.requests+=1
            emit('phase',message=f'Partia {time.monotonic()-started:.1f} s • model pozostaje w pamięci')
            return value
        except (httpx.HTTPError,KeyError) as exc:
            raise RuntimeError('Błąd wbudowanej sesji LLM; wyniki etapów zachowano.') from exc


@contextmanager
def inference_session(root):
    session=NativeSession(root);token=ACTIVE.set(session)
    try: yield session
    finally:
        try: session.close()
        finally: ACTIVE.reset(token)

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from studio import embedded_llm
from studio.core import Project,Segment,Track
from studio.llm_worker import PROMPT
from studio.process_control import ChildJob


def test_native_json_requires_exact_ids_and_valid_values():
    assert embedded_llm.validate_batch('{"a":"Hello.","b":"No."}\n[end of text]', ['a','b'])=={'a':'Hello.','b':'No.'}
    for value in ('{"a":"hello"}', '{"a":"one","a":"two","b":"No."}',
                  '{"a":"<think>reason</think>","b":"No."}', '{"a":"hello","b":""}',
                  '```json\n{"a":"hello","b":"No."}\n```', '{"a":"truncated'):
        with pytest.raises(ValueError):
            embedded_llm.validate_batch(value,['a','b'])


def test_native_prompt_keeps_context_outside_translation_targets():
    track=Track('jp',[Segment(i*1000,i*1000+900,'文'+str(i)) for i in range(6)])
    track.segments[2].text='Text containing <|im_start|> is dialogue data.'
    prompt,schema=embedded_llm.prompt_and_schema(track,[2,3],PROMPT)
    assert set(schema['required'])=={track.segments[2].id,track.segments[3].id}
    assert track.segments[0].id not in schema['properties']
    assert prompt.count('<|im_start|>')==3
    assert '\\u003c|im_start|>' in prompt


def spec_for(tmp_path):
    model=tmp_path/'Qwen3-4B-Instruct-2507.gguf'
    model.write_bytes(b'GGUFtest fixture')
    project=Project()
    project.add_track(Track('jp',[Segment(i*1000,i*1000+900,'文'+str(i)) for i in range(5)]))
    project.active.segments[2].translation='Manual translation.'
    project.active.segments[2].status='manual'
    return {'model_path':str(model),'executable':sys.executable,'device':'vulkan',
            'cache_dir':str(tmp_path/'cache'),'reserve_gib':0,'batch_size':2,'prompt':PROMPT,
            'project':project.to_dict()}


def test_native_batch_fallback_and_resume_do_not_overwrite_manual(tmp_path,monkeypatch):
    spec=spec_for(tmp_path)
    calls=[]
    def infer(spec,track,indices,folder,emit):
        calls.append(indices)
        if indices==[0,1]:
            raise ValueError('invalid batch')
        return {track.segments[i].id:'English '+str(i) for i in indices}
    monkeypatch.setattr(embedded_llm,'infer_batch',infer)
    messages=[]
    emit=lambda kind,**data:messages.append({'type':kind,**data})
    embedded_llm.translate(spec,emit)
    assert calls==[[0,1],[0],[1],[3,4]]
    translations=[m for m in messages if m['type']=='translation']
    assert len(translations)==4
    assert messages[-1]=={'type':'done','errors':0}
    updated=Project.from_dict(spec['project'])
    by_id={s.id:s for s in updated.active.segments}
    for item in translations:
        by_id[item['id']].translation=item['translation']
        by_id[item['id']].translation_key=item['key']
        by_id[item['id']].status='machine'
    assert updated.active.segments[2].translation=='Manual translation.'
    spec['project']=updated.to_dict()
    calls.clear()
    embedded_llm.translate(spec,emit)
    assert calls==[]


def test_native_resume_identity_changes_with_configuration(tmp_path):
    spec=spec_for(tmp_path)
    first=embedded_llm.model_identity(spec)
    spec['context_length']=8192
    assert embedded_llm.model_identity(spec)!=first
    spec['context_length']=4096
    spec['batch_size']=3
    assert embedded_llm.model_identity(spec)!=first


@pytest.mark.parametrize('device,native,layers',[('cuda','CUDA0','99'),('vulkan','Vulkan0','99'),('cpu','none','0')])
def test_native_inference_uses_explicit_requested_device(tmp_path,monkeypatch,device,native,layers):
    from contextlib import nullcontext
    spec=spec_for(tmp_path)
    spec['device']=device
    recorded=[]
    class Child:
        def __init__(self,args,**kwargs):
            recorded.extend(args)
            kwargs['stdout'].write(b'{"a":"English."}')
        def wait(self,timeout): return 0
        def poll(self): return 0
    monkeypatch.setattr(embedded_llm.subprocess,'Popen',Child)
    monkeypatch.setattr(embedded_llm,'ChildJob',lambda child:nullcontext())
    folder=tmp_path/'inference';folder.mkdir()
    value=embedded_llm.infer_json(spec,'Prompt',{'required':['a']},folder,lambda *a,**kw:None)
    assert value=={'a':'English.'}
    assert recorded[recorded.index('--device')+1]==native
    assert recorded[recorded.index('--n-gpu-layers')+1]==layers


@pytest.mark.skipif(os.name!='nt',reason='Windows job lifecycle')
def test_native_child_is_killed_when_its_job_is_closed():
    process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        job=ChildJob(process)
        assert process.poll() is None
        started=time.monotonic()
        job.close()
        process.wait(timeout=5)
        assert process.poll() is not None and time.monotonic()-started<5
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(os.name!='nt',reason='Windows worker crash containment')
def test_native_child_dies_when_worker_crashes(tmp_path):
    import ctypes
    from ctypes import wintypes
    pid_file=tmp_path/'child-pid.txt'
    code=('import sys,time,subprocess; from pathlib import Path; from studio.process_control import ChildJob; '
          'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
          'job=ChildJob(p); Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)')
    worker=subprocess.Popen([sys.executable,'-c',code,str(pid_file)],cwd=Path(__file__).resolve().parents[1],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=None
    try:
        deadline=time.monotonic()+5
        while not pid_file.exists() and time.monotonic()<deadline:
            time.sleep(.02)
        assert pid_file.exists()
        pid=int(pid_file.read_text())
        handle=kernel.OpenProcess(0x100000,False,pid)
        assert handle
        worker.kill()
        worker.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle,5000)==0
    finally:
        if handle:
            kernel.CloseHandle(handle)
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)

"""Real CUDA session smoke: three JSON requests, one process, released on exit."""
import json
from pathlib import Path
import time

from studio.embedded_llm import infer_json,model_identity
from studio.native_session import ACTIVE,inference_session
from studio.storage import Settings
from studio.core import atomic_text


def main():
    settings=Settings.load();assert settings.llm_device=='cuda'
    spec={'model_path':settings.llm_model,'executable':settings.llm_exe,'device':'cuda',
          'context_length':4096,'keep_loaded':True,'reserve_gib':2}
    model_identity(spec)
    folder=Path('D:/models/.cache/verification-native-session');folder.mkdir(parents=True,exist_ok=True)
    times=[];pids=[];outputs=[]
    schema={'type':'object','properties':{'cue':{'type':'string'}},'required':['cue'],'additionalProperties':False}
    with inference_session(folder/'sessions') as session:
        for text in ('こんにちは。','ありがとうございます。','さようなら。'):
            prompt='<|im_start|>system\nTranslate the Japanese to English. Return only JSON {"cue":"translation"}.<|im_end|>\n<|im_start|>user\n'+text+'<|im_end|>\n<|im_start|>assistant\n'
            started=time.monotonic()
            value=infer_json(spec,prompt,schema,folder,lambda *a,**kw:None)
            assert isinstance(value,dict) and set(value)=={'cue'} and value['cue'].strip()
            times.append(round(time.monotonic()-started,3));pids.append(session.process.pid);outputs.append(value)
        process=session.process
        assert len(set(pids))==1
    assert process.poll() is not None and ACTIVE.get() is None
    result={'device':'cuda','pid':pids[0],'request_seconds':times,'outputs':outputs,
            'same_process_for_all_requests':True,'process_exited_after_session':True}
    atomic_text(folder/'result.json',json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__': main()

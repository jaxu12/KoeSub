"""Real native translation smoke check; never starts a server or sends HTTP requests."""
import json
import os
import subprocess
import sys
from pathlib import Path

from studio.core import Project,load_srt
from studio.llm_worker import PROMPT
from studio.storage import ROOT,offline_env


def main():
    folder = Path('D:/models/.cache/verification-embedded')
    folder.mkdir(parents=True,exist_ok=True)
    runtime = json.loads(Path('D:/models/subtitle-studio-embedded-llm.json').read_text('utf8'))
    track = load_srt(Path('D:/models/.cache/verification-japanese/transcript.srt'))
    track.segments=track.segments[:2]
    project=Project(name='Native translation verification')
    project.add_track(track)
    spec={'backend':'embedded','action':'translate','executable':runtime['executable'],
          'model_path':'D:/models/lmstudio-community/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q4_K_M.gguf',
          'device':'vulkan','context_length':4096,'batch_size':6,'cache_dir':'D:/models/.cache',
          'job_id':'verification-native','prompt':PROMPT,'project':project.to_dict()}
    file=folder/'job.json'
    file.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf8')
    env={**os.environ,**offline_env()}
    result=subprocess.run([sys.executable,'-m','studio.llm_worker',str(file)],cwd=ROOT,env=env,
                          capture_output=True,timeout=300)
    (folder/'worker.jsonl').write_bytes(result.stdout)
    (folder/'stderr.log').write_bytes(result.stderr)
    text=result.stdout.decode('utf8',errors='replace')
    print(text,flush=True)
    messages=[json.loads(line) for line in text.splitlines()]
    translations=[m for m in messages if m['type']=='translation']
    assert result.returncode==0 and len(translations)==2, result.stderr.decode('utf8',errors='replace')
    print('Native model verified; no LM Studio or HTTP server involved.')


if __name__=='__main__':
    main()

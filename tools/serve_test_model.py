"""Optional foreground local translation server using the downloaded GGUF on D:."""
import os
import socket
import subprocess
from pathlib import Path

from studio.storage import Settings, offline_env


def command():
    settings = Settings.load()
    server = Path(settings.subtitle_edit)/'llama.cpp/llama-server.exe'
    model = Path('D:/models/lmstudio-community/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q4_K_M.gguf')
    if not server.is_file() or not model.is_file():
        raise RuntimeError('Missing llama-server or downloaded model. See README.')
    return [str(server),'--model',str(model),'--host','127.0.0.1','--port','1234',
            '--ctx-size','4096','--parallel','1','--n-gpu-layers','99','--jinja',
            '--alias','qwen3-4b-instruct-2507']


def main():
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1',1234))
        except OSError as exc:
            raise RuntimeError('Port 1234 is already in use. Keep the existing local server or stop it first.') from exc
    cache = Path('D:/models/.cache/translation-server')
    cache.mkdir(parents=True,exist_ok=True)
    env = {**os.environ,**offline_env(),'TEMP':str(cache),'TMP':str(cache)}
    print('Local Qwen server; all weights stay on D:. Close this console before running ASR again.',flush=True)
    try:
        raise SystemExit(subprocess.run(command(),env=env,cwd=cache).returncode)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

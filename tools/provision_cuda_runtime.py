"""Provision pinned official CUDA runtimes on D:, without downloading model weights or changing app settings."""
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from studio.core import atomic_text

ROOT=Path('D:/models/.runtime')
PACKAGES=[
    ('CrispStrobe/CrispASR','v0.8.45','crispasr-windows-x86_64-cuda13.zip',
     'f53db0029f07cc2193ed8e99b975e4582bf87982e3d22b068ef37b58405d5878','crispasr-v0.8.45-cuda13'),
    ('ggml-org/llama.cpp','b11935','llama-b11935-bin-win-cuda-13.4-x64.zip',
     '8535621031db30a4b8649172ecae4639aecbc37bf036091d4e07448694c7b893','llama-b11935-cuda13'),
    ('ggml-org/llama.cpp','b11935','cudart-llama-bin-win-cuda-13.4-x64.zip',
     '738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668','llama-b11935-cuda13'),
]


def fetch(repo,tag,name,expected,folder):
    dest=ROOT/folder
    receipt=dest/(name+'.receipt.json')
    if receipt.exists():
        return json.loads(receipt.read_text('utf8'))
    if shutil.disk_usage(ROOT).free<6*1024**3: raise ValueError('Requires 6 GiB free disk space')
    request=urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/tags/{tag}',headers={'User-Agent':'AI-Subtitle-Studio/0.1'})
    with urllib.request.urlopen(request,timeout=30) as response: release=json.load(response)
    asset=next(a for a in release['assets'] if a['name']==name)
    if asset.get('digest')!='sha256:'+expected or asset['size']>850*1024**2: raise ValueError('Unexpected release asset')
    archive=ROOT/(name+'.download')
    count=0;digest=hashlib.sha256();last=0
    print('Downloading:',name,'MiB:',round(asset['size']/1024**2,1),flush=True)
    try:
        request=urllib.request.Request(asset['browser_download_url'],headers={'User-Agent':'AI-Subtitle-Studio/0.1'})
        with urllib.request.urlopen(request,timeout=60) as response,archive.open('wb') as stream:
            while chunk:=response.read(1024**2):
                count+=len(chunk)
                if count>asset['size']: raise ValueError('Download exceeds expected size')
                stream.write(chunk);digest.update(chunk)
                progress=int(count/asset['size']*4)
                if progress>last:
                    last=progress;print(name,progress*25,'%',flush=True)
        if count!=asset['size'] or digest.hexdigest()!=expected: raise ValueError('Invalid archive checksum')
        dest.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive) as package:
            if sum(i.file_size for i in package.infolist())>3*1024**3: raise ValueError('Unpacked archive exceeds budget')
            for item in package.infolist():
                if not (dest/item.filename).resolve().is_relative_to(dest.resolve()): raise ValueError('Invalid archive path')
                if item.filename.lower().endswith(('.gguf','.bin')): raise ValueError('Unexpected model weights in runtime')
            package.extractall(dest)
        result={'repo':repo,'tag':tag,'asset':name,'url':asset['browser_download_url'],'sha256':expected,
                'archive_bytes':count,'directory':str(dest),'files':[str(p.relative_to(dest)) for p in dest.rglob('*') if p.is_file()]}
        atomic_text(receipt,json.dumps(result,indent=2))
        return result
    finally:
        archive.unlink(missing_ok=True)


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    ROOT.mkdir(parents=True,exist_ok=True)
    for package in PACKAGES: fetch(*package)
    crisp=next((ROOT/'crispasr-v0.8.45-cuda13').rglob('crispasr.exe'))
    llama=next((ROOT/'llama-b11935-cuda13').rglob('llama-completion.exe'))
    results={}
    for name,exe,flag in [('crisp',crisp,'--version'),('llama',llama,'--list-devices')]:
        result=subprocess.run([str(exe),flag],capture_output=True,timeout=30)
        output=(result.stdout+result.stderr).decode('utf8',errors='replace')
        print(name,exe,'exit',result.returncode,output,flush=True)
        if result.returncode: raise ValueError('CUDA runtime probe failed: '+name)
        if 'cuda' not in output.lower(): raise ValueError('Runtime did not confirm CUDA: '+name)
        results[name]={'executable':str(exe),'probe':output}
    atomic_text(ROOT/'cuda-runtimes.json',json.dumps(results,indent=2))


if __name__=='__main__': main()

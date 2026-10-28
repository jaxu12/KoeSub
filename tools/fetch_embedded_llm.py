"""Install a small, verified llama.cpp Vulkan runtime on D:, without model copies."""
import json
import zipfile

from .bootstrap_test_models import ROOT, download, json_url


def main():
    manifest = ROOT/'subtitle-studio-embedded-llm.json'
    if manifest.exists():
        item = json.loads(manifest.read_text('utf8'))
    else:
        releases = json_url('https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=6')
        chosen = next((r,a) for r in releases for a in r['assets'] if a['name'].endswith('-bin-win-vulkan-x64.zip'))
        release, asset = chosen
        digest = asset.get('digest','')
        if not digest.startswith('sha256:'):
            raise RuntimeError('No published SHA-256 for this runtime.')
        item = {'repo':'ggml-org/llama.cpp','revision':release['tag_name'],'filename':asset['name'],
                'relative_path':'.downloads/'+asset['name'],'bytes':asset['size'],
                'sha256':digest.split(':',1)[1],'url':asset['browser_download_url']}
        manifest.write_text(json.dumps(item,indent=2),encoding='utf8')
    output = ROOT/'.runtime'/f'llama-{item["revision"]}-vulkan'
    exes = list(output.rglob('llama-completion.exe')) if output.exists() else []
    if not exes:
        archive_path = download(item)
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if not (output/entry.filename).resolve().is_relative_to(output.resolve()):
                    raise RuntimeError('Unsafe archive path.')
            archive.extractall(output)
        exes = list(output.rglob('llama-completion.exe'))
        if not exes:
            raise RuntimeError('Missing llama-completion.exe in the runtime.')
        archive_path.unlink()
    item['executable'] = str(exes[0])
    item['status'] = 'verified'
    manifest.write_text(json.dumps(item,indent=2),encoding='utf8')
    print('Embedded CLI ready:',exes[0],flush=True)


if __name__=='__main__':
    main()

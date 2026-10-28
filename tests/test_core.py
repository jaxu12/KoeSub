import json
import sqlite3
from pathlib import Path

import pytest

from studio.core import (Project, ProjectStore, Segment, Track, compare_tracks, export_srt,
                         issues_for, load_srt, merge_segments, parse_time, split_segment,
                         time_text, translation_key)
from studio.storage import Settings, audio_cache_path, check_space, discover_models
from studio.adapters import (crisp_backends, crisp_command, validate_crisp_backend,
                             validate_flags, whisper_command, whisper_cpp_command)
from studio.llm_worker import local_url, validate_translation

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('text', ['ggml backends : cpu,vulkan',
                                 'crispasr 0.8.45 [backends: cpu,vulkan]'])
def test_crisp_rejects_unavailable_cuda(text):
    assert crisp_backends(text) == ('vulkan', 'cpu')
    validate_crisp_backend('vulkan', text)
    with pytest.raises(ValueError, match='CUDA'):
        validate_crisp_backend('cuda', text)


def test_crisp_cuda_build_and_unknown_capabilities():
    validate_crisp_backend('cuda', 'ggml backends : cpu,cuda')
    with pytest.raises(ValueError, match='backendów'):
        validate_crisp_backend('cuda', 'unrecognized version output')


def test_srt_roundtrip_and_sqlite_preserve_identity(tmp_path):
    track = load_srt(ROOT / 'samples/japanese_a.srt')
    track.segments[0].translation = 'It is a nice day today.'
    project = Project(name='日本語')
    project.add_track(track)
    store = ProjectStore(tmp_path / 'project.sqlite')
    store.save(project)
    recovered = store.load()
    assert recovered.to_dict() == project.to_dict()
    export_srt(recovered.active, tmp_path / 'export.srt')
    imported = load_srt(tmp_path / 'export.srt')
    assert [(s.start, s.end, s.text) for s in imported.segments] == [(s.start, s.end, s.text) for s in track.segments]


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows atomic replacement sharing violation')
@pytest.mark.parametrize('winerror',[32,None])
def test_atomic_save_retries_windows_reader_conflict_without_truncation(tmp_path,monkeypatch,winerror):
    from studio import core
    path = tmp_path/'progress.json'
    path.write_text('old',encoding='utf8')
    replace = core.os.replace
    attempts = []
    def busy_then_replace(source,target):
        attempts.append(1)
        if len(attempts)<3:
            assert path.read_text()=='old'
            error = PermissionError(13,'Reader briefly holds file')
            if winerror is not None: error.winerror = winerror
            raise error
        return replace(source,target)
    monkeypatch.setattr(core.os,'replace',busy_then_replace)
    monkeypatch.setattr(core.time,'sleep',lambda *_:None)
    core.atomic_text(path,'new')
    assert path.read_text()=='new' and len(attempts)==3


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows checkpoint sharing violation')
@pytest.mark.parametrize('winerror',[5,32,33,None])
@pytest.mark.parametrize('reader_name',['core','worker'])
def test_checkpoint_read_retries_transient_windows_lock(tmp_path,monkeypatch,winerror,reader_name):
    from studio import core, pipeline_worker
    path=tmp_path/'manifest.json'
    path.write_text('{"status":"completed","text":"日本語"}',encoding='utf8')
    original=Path.read_text
    attempts=[]
    def read_locked(target,*args,**kwargs):
        if target==path:
            attempts.append(1)
            if len(attempts)<3:
                error=PermissionError(13,'Atomic replacement briefly blocks opening')
                if winerror is not None: error.winerror=winerror
                raise error
        return original(target,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',read_locked)
    monkeypatch.setattr(core.time,'sleep',lambda *_:None)
    reader=core.read_json_file if reader_name=='core' else pipeline_worker.read_json
    assert reader(path)=={'status':'completed','text':'日本語'}
    assert len(attempts)==3


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows checkpoint sharing violation')
@pytest.mark.parametrize('winerror',[5,None])
def test_checkpoint_read_stops_after_bounded_retries(tmp_path,monkeypatch,winerror):
    from studio import core
    attempts=[]
    def denied(*args,**kwargs):
        attempts.append(1)
        error=PermissionError(13,'Permanent access denial')
        if winerror is not None: error.winerror=winerror
        raise error
    monkeypatch.setattr(Path,'read_text',denied)
    monkeypatch.setattr(core.time,'sleep',lambda *_:None)
    with pytest.raises(PermissionError): core.read_json_file(tmp_path/'manifest.json')
    assert len(attempts)==8


def test_checkpoint_read_does_not_retry_or_hide_invalid_json(tmp_path,monkeypatch):
    from studio import core
    path=tmp_path/'manifest.json'
    path.write_text('{broken',encoding='utf8')
    def no_sleep(*args): pytest.fail('Invalid JSON must not be retried')
    monkeypatch.setattr(core.time,'sleep',no_sleep)
    with pytest.raises(json.JSONDecodeError): core.read_json_file(path)


def test_merge_split_provenance_and_originals(tmp_path):
    a, b = Segment(0, 1000, '今日は'), Segment(1000, 2000, '晴れです。')
    project = Project()
    project.add_track(Track('test', [a, b]))
    merged = merge_segments([a, b])
    assert merged.parents == [a.id, b.id]
    x, y = split_segment(merged, 3, 1100)
    assert x.parents == y.parents == [merged.id]
    assert x.end == y.start == 1100
    assert project.originals[project.active_track]['segments'][0]['text'] == '今日は'
    with pytest.raises(ValueError):
        split_segment(merged, 0, 500)


def test_machine_checkpoints_do_not_duplicate_full_history(tmp_path):
    project = Project()
    project.add_track(Track('test', [Segment(0,1000,'日本語')]))
    store = ProjectStore(tmp_path/'project.sqlite')
    store.save(project, 'import srt')
    for i in range(25):
        project.active.segments[0].translation = f'Translation {i}'
        store.save(project, 'translation checkpoint')
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT count(*) FROM history').fetchone()[0] == 1
    assert store.load().active.segments[0].translation == 'Translation 24'


def test_many_to_one_and_unmatched():
    a = load_srt(ROOT / 'samples/japanese_a.srt')
    b = load_srt(ROOT / 'samples/japanese_b.srt')
    groups = compare_tracks(a, b)
    assert any(len(g['a']) == 2 and len(g['b']) == 1 for g in groups)
    assert any(g['a'] and not g['b'] for g in groups)
    assert any(g['b'] and not g['a'] for g in groups)
    assert sum(len(g['a']) for g in groups) == len(a.segments)


def test_boundary_jitter_does_not_chain_entire_transcript():
    a = Track('a', [Segment(i*1000, (i+1)*1000, str(i)) for i in range(10)])
    b = Track('b', [Segment(i*1000+50, (i+1)*1000+50, str(i)) for i in range(10)])
    assert len(compare_tracks(a,b)) == 10


@pytest.mark.parametrize('value', [0, 1, 999, 3600001, 99999999])
def test_time_roundtrip(value):
    assert parse_time(time_text(value)) == value


def test_invalid_time_and_export(tmp_path):
    with pytest.raises(ValueError):
        parse_time('00:99:00,000')
    with pytest.raises(ValueError):
        export_srt(Track('bad', [Segment(0,0,'zero')]), tmp_path/'x.srt')
    with pytest.raises(ValueError):
        export_srt(Track('missing', [Segment(0,1000,'JP')]), tmp_path/'x.srt', True)
    malformed = tmp_path/'bad.srt'
    malformed.write_text('1\nbroken\n日本語', encoding='utf8')
    with pytest.raises(ValueError):
        load_srt(malformed)


def test_static_flags_are_not_semantic_verdicts():
    assert any('Powtórzenia' in v for v in issues_for(Segment(0,1000,'え?え?え?え?')))
    s = Segment(0,1000,'いえ', translation="I cannot translate this.")
    assert any('odmowa' in v for v in issues_for(s))
    assert any('Japońskie' in v for v in issues_for(Segment(0,1000,'すごい', translation='すごい')))
    assert not any('długość' in v for v in issues_for(Segment(0,1000,'いえ', translation='No, that is not what I meant.')))


def test_local_model_discovery_and_no_download_name(tmp_path):
    model = tmp_path / 'models' / 'faster-whisper-local-model'
    model.mkdir(parents=True)
    (model/'config.json').write_text('{}')
    (model/'model.bin').write_bytes(b'123')
    (tmp_path/'qwen-asr.gguf').write_bytes(b'abc')
    found = discover_models([str(tmp_path), str(tmp_path)])
    assert len(found) == 2
    local = next(m for m in found if 'CTranslate2' in m.kind)
    args = whisper_command(Settings(), local, tmp_path/'audio.wav', tmp_path, 'float16', 'cuda', True,
        '--model --model_dir --output_dir --language --task --device --compute_type --beam_size --best_of '
        '--temperature --condition_on_previous_text --initial_prompt --vad_filter --word_timestamps '
        '--standard_asia --beep_off --output_format')
    assert args[args.index('--model')+1] == 'local-model'
    assert args[args.index('--model_dir')+1] == str(model.parent.resolve())
    with pytest.raises(ValueError):
        validate_flags('--model', ['--unknown'])


def test_disk_and_cache_fingerprint(tmp_path):
    media = tmp_path/'video.mp4'
    media.write_bytes(b'x')
    settings = Settings(cache_dir=str(tmp_path/'cache'))
    first = audio_cache_path(settings, media, 0)
    assert first != audio_cache_path(settings, media, 1)
    assert first != audio_cache_path(settings, media, 0, duration=1000)
    with pytest.raises(ValueError):
        check_space(tmp_path, 10**20)


def test_crisp_uses_explicit_external_models_and_gpu_backend(tmp_path):
    from studio.storage import Model
    asr, aligner, vad = tmp_path/'asr.gguf', tmp_path/'aligner.gguf', tmp_path/'silero.bin'
    for path in (asr, aligner, vad):
        path.write_bytes(b'model-test')
    settings = Settings(crisp_exe=str(tmp_path/'tools/crispasr.exe'), cache_dir=str(tmp_path/'cache'),
                        crisp_gpu_backend='vulkan', crisp_aligner=str(aligner), crisp_vad=str(vad))
    help_text = ('--backend --model --file --language --max-len --split-on-punct --suppress-nst '
                 '--frequency-penalty --gpu-backend --cache-dir --output-srt --output-json '
                 '--output-file --aligner-model --vad --vad-model --strict-pipeline')
    args = crisp_command(settings, Model('ASR',str(asr),'Qwen ASR',10), tmp_path/'audio.wav',tmp_path,True,help_text)
    assert args[args.index('--gpu-backend')+1] == 'vulkan'
    assert args[args.index('--aligner-model')+1] == str(aligner.resolve())
    assert args[args.index('--vad-model')+1] == str(vad.resolve())
    assert '--auto-download' not in args
    assert '--strict-pipeline' in args
    aligner.unlink()
    with pytest.raises(ValueError):
        crisp_command(settings, Model('ASR',str(asr),'Qwen ASR',10), tmp_path/'audio.wav',tmp_path,True,help_text)


def test_whisper_ggml_discovery_and_transcription_only(tmp_path):
    (tmp_path/'ggml-large-v3.bin').write_bytes(b'ggml test')
    vad=tmp_path/'ggml-silero-v6.2.0.bin'
    vad.write_bytes(b'vad test')
    found=discover_models([str(tmp_path)])
    assert len(found)==1 and found[0].kind=='Whisper / GGML'
    settings=Settings(cache_dir=str(tmp_path/'cache'),crisp_gpu_backend='vulkan',crisp_vad=str(vad))
    help_text=('--backend --model --file --language --beam-size --max-len --split-on-punct '
               '--gpu-backend --output-srt --output-json-full --cache-dir --output-file --vad --vad-model --strict-pipeline')
    args=whisper_cpp_command(settings,found[0],tmp_path/'input.wav',tmp_path,True,help_text)
    assert args[args.index('--backend')+1]=='whisper'
    assert args[args.index('--language')+1]=='ja'
    assert '--translate' not in args


def test_kotoba_uses_existing_explicit_aligner_without_downloading(tmp_path):
    from studio.storage import Model
    model_path=tmp_path/'ggml-kotoba-whisper-v2.0.bin';model_path.write_bytes(b'ggml')
    aligner=tmp_path/'aligner.gguf';aligner.write_bytes(b'gguf')
    settings=Settings(cache_dir=str(tmp_path/'cache'),crisp_gpu_backend='cuda',crisp_aligner=str(aligner))
    help_text=('--backend --model --file --language --beam-size --max-len --split-on-punct '
               '--gpu-backend --output-srt --output-json-full --cache-dir --output-file '
               '--aligner-model --force-aligner --strict-pipeline')
    args=whisper_cpp_command(settings,Model(model_path.name,str(model_path),'Whisper / GGML',4),tmp_path/'audio.wav',tmp_path,False,help_text)
    assert '--force-aligner' in args and args[args.index('--aligner-model')+1]==str(aligner.resolve())
    assert args[args.index('--gpu-backend')+1]=='cuda' and '--auto-download' not in args
    aligner.unlink()
    with pytest.raises(ValueError,match='alignera'):
        whisper_cpp_command(settings,Model(model_path.name,str(model_path),'Whisper / GGML',4),tmp_path/'audio.wav',tmp_path,False,help_text)


def test_reazonspeech_is_discovered_as_asr_and_uses_explicit_cuda(tmp_path):
    from studio.storage import Model
    from studio.adapters import reazonspeech_command
    path=tmp_path/'reazonspeech-nemo-v2-f16.gguf';path.write_bytes(b'GGUF')
    found=discover_models([str(tmp_path)])
    assert len(found)==1 and found[0].kind=='ReazonSpeech / GGUF'
    flags='--backend --model --file --language --gpu-backend --max-len --split-on-punct --cache-dir --output-srt --output-json-full --output-file --strict-pipeline'
    args=reazonspeech_command(Settings(crisp_gpu_backend='cuda'),found[0],tmp_path/'audio.wav',tmp_path,False,flags)
    assert args[args.index('--backend')+1]=='reazonspeech' and args[args.index('--gpu-backend')+1]=='cuda'
    assert '--auto-download' not in args


def test_translation_validation_and_context_invalidation():
    assert validate_translation('{"segment_id":"s1","translation":"No."}', 's1') == 'No.'
    for content in ['not json', '{"segment_id":"other","translation":"No."}',
                    '{"segment_id":"s1","translation":"<think>hmm</think>No."}']:
        with pytest.raises(ValueError):
            validate_translation(content, 's1')
    s, neighbor = Segment(0,1000,'いえ'), Segment(1000,2000,'本当？')
    key = translation_key(s, [neighbor], 'qwen', 'translate')
    neighbor.text = '家です。'
    assert key != translation_key(s, [neighbor], 'qwen', 'translate')


@pytest.mark.parametrize('url', ['https://example.com', 'http://example.com', 'http://localhost.evil.com', 'http://user@localhost'])
def test_only_local_lm_server(url):
    with pytest.raises(ValueError):
        local_url(url)

from dataclasses import asdict
from pathlib import Path
import sys

import pytest

from studio.adapters import whisper_command
from studio.pipeline import create_run, load_run, plan, validate_config
from studio.pipeline_worker import PipelineRunner, read_json, run_pipeline
from studio.storage import Settings, Model, audio_cache_path


@pytest.fixture
def installed(tmp_path):
    root=tmp_path/'SubtitleEdit/SpeechToText/Purfview-Faster-Whisper-XXL'
    model=root/'_models/faster-whisper-large-v3'
    for path in (root/'faster-whisper-xxl.exe',model/'model.bin',model/'config.json',model/'tokenizer.json',
                 root/'_xxl_data/faster_whisper/assets/Kim_Vocal_2.onnx'):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
    settings=Settings(subtitle_edit=str(tmp_path/'SubtitleEdit'),crisp_exe='keep-existing',cache_dir=str(tmp_path/'cache'),reserve_gib=0)
    return settings,model


def test_reuse_installed_settings_does_not_copy_models_or_replace_other_runtime(installed):
    settings,model=installed
    before=set(model.parent.parent.rglob('*'))
    assert settings.use_subtitle_edit_whisper()==model.resolve()
    assert settings.crisp_exe=='keep-existing' and settings.whisper_profile=='subtitle-edit'
    assert settings.whisper_vocal_extract=='mdx_kim2'
    assert settings.model_roots==[str(model.parent.resolve())]
    settings.use_subtitle_edit_whisper()
    assert len(settings.model_roots)==1 and set(model.parent.parent.rglob('*'))==before


def test_subtitle_edit_flags_preserve_native_context_defaults_and_require_local_mdx(installed,tmp_path):
    settings,model=installed;settings.use_subtitle_edit_whisper()
    args=whisper_command(settings,Model('Large V3',str(model),'Whisper / CTranslate2',0),tmp_path/'audio.wav',tmp_path,'float16','cuda',True,
        '--model --model_dir --output_dir --language --task --device --compute_type --standard_asia --vad_filter --beep_off --output_format --ff_vocal_extract --voc_device')
    assert args[args.index('--compute_type')+1]=='float16'
    assert args[args.index('--ff_vocal_extract')+1]=='mdx_kim2'
    assert args[args.index('--voc_device')+1]=='cuda'
    assert '--condition_on_previous_text' not in args and '--initial_prompt' not in args
    (Path(settings.whisper_exe).parent/'_xxl_data/faster_whisper/assets/Kim_Vocal_2.onnx').unlink()
    with pytest.raises(ValueError,match='download is disabled'):
        whisper_command(settings,Model('Large V3',str(model),'Whisper / CTranslate2',0),tmp_path/'audio.wav',tmp_path,'float16','cuda',True,'')


def test_ct2_manifest_tracks_weights_and_separation_asset_and_rejects_changed_model(installed,tmp_path):
    settings,model=installed;settings.use_subtitle_edit_whisper();settings.ffmpeg=sys.executable
    media=tmp_path/'media.wav';media.write_bytes(b'audio')
    config={'media':str(media),'media_duration':2000,'start':0,'duration':2000,'audio_track':0,
        'asr':[{'engine':0,'name':'XXL','model':str(model),'kind':'Whisper / CTranslate2','vad':True}],
        'translations':[],'review':'rules','review_settings':{},'settings':asdict(settings),'transcription_only':True,
        'retry_asr':{'enabled':False},'backend':'embedded','output_dir':str(tmp_path/'exports'),'export_srt':True}
    state=create_run(config,tmp_path/'run');paths={Path(p['path']).name for p in state['assets']}
    assert {'model.bin','config.json','tokenizer.json','Kim_Vocal_2.onnx'}<=paths
    assert [p['id'] for p in plan(config)]==['audio','asr-0','jp-layout','jp-export']
    load_run(tmp_path/'run/manifest.json')
    (model/'model.bin').write_bytes(b'changed weights')
    with pytest.raises(ValueError):load_run(tmp_path/'run/manifest.json')


def test_stereo_vocal_cache_does_not_reuse_legacy_audio(installed,tmp_path):
    settings,_=installed;media=tmp_path/'input.wav';media.write_bytes(b'fixture')
    assert audio_cache_path(settings,media,0)!=audio_cache_path(settings,media,0,profile='vocal-stereo44100-v1')
    with pytest.raises(ValueError):audio_cache_path(settings,media,0,profile='unknown')


def test_native_jp_pipeline_runs_without_translation_or_crisp_and_resumes(installed,tmp_path,monkeypatch):
    from studio.core import Track,Segment
    settings,model=installed;settings.use_subtitle_edit_whisper();settings.ffmpeg=sys.executable
    media=tmp_path/'media.wav';media.write_bytes(b'audio')
    config={'media':str(media),'media_duration':2000,'start':0,'duration':2000,'audio_track':0,
        'asr':[{'engine':0,'name':'XXL','model':str(model),'kind':'Whisper / CTranslate2','vad':True}],
        'translations':[],'review':'rules','review_settings':{},'settings':asdict(settings),'transcription_only':True,
        'retry_asr':{'enabled':False},'backend':'embedded','output_dir':str(tmp_path/'exports'),'export_srt':True}
    create_run(config,tmp_path/'run');calls=[]
    monkeypatch.setattr(PipelineRunner,'audio',lambda self,f:{'audio':str(media)})
    def asr(self,folder,item,audio):
        calls.append(item['engine']);return {'track':asdict(Track('XXL',[Segment(200,1800,'こんにちは。')]))}
    monkeypatch.setattr(PipelineRunner,'asr',asr)
    monkeypatch.setattr(PipelineRunner,'ask',lambda *a:pytest.fail('No text model should run'))
    manifest=tmp_path/'run/manifest.json';run_pipeline(manifest,lambda *a,**k:None)
    assert calls==[0] and read_json(manifest)['status'] in ('completed','needs_review')
    run_pipeline(manifest,lambda *a,**k:None);assert calls==[0]
    config['retry_asr']['enabled']=True
    with pytest.raises(ValueError,match='native source-only'):validate_config(config)

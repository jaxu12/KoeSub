import copy
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from studio import embedded_llm
from studio.core import Segment,Track,compare_tracks
from studio.pipeline import (VARIANTS,choose_english,clone_track,create_run,format_final,
                             group_key,load_run,normalize_asr_times,plan,select_asr,validate_choices,validate_config)
from studio.pipeline_worker import PipelineBusyError,PipelineRunner,pipeline_lock,read_json,run_pipeline,write_json
from studio.review import ReviewSettings
from studio.storage import Settings


@pytest.fixture
def config(tmp_path):
    paths = [tmp_path/'audio.wav',tmp_path/'ggml-test.bin',tmp_path/'qwen-asr.gguf',tmp_path/'Qwen3-4B-Instruct.gguf']
    for path in paths:
        path.write_bytes(b'GGUF fixture')
    settings = Settings(ffmpeg=sys.executable,crisp_exe=sys.executable,llm_exe=sys.executable,
                        cache_dir=str(tmp_path/'cache'),llm_model=str(paths[3]),crisp_gpu_backend='vulkan',reserve_gib=0)
    return {'media':str(paths[0].resolve()),'media_duration':6000,'audio_track':0,'start':0,'duration':6000,
            'asr':[{'engine':2,'model':str(paths[1]),'kind':'Whisper / GGML','name':'Whisper','vad':False},
                   {'engine':1,'model':str(paths[2]),'kind':'Qwen ASR','name':'Qwen','vad':False}],
            'translations':[{'model':str(paths[3]),'variant':0},{'model':str(paths[3]),'variant':1}],
            'backend':'embedded','judge_model':str(paths[3]),'review':'deep','review_settings':{},
            'settings':asdict(settings),'prompt':'Faithful translation.','export_srt':True,'autosplit':False,
            'output_dir':str(tmp_path/'exports')}


def install_fake_engines(monkeypatch,config):
    calls = []
    def audio(self,folder):
        calls.append('audio')
        return {'audio':config['media']}
    def asr(self,folder,item,audio):
        calls.append(item['name'])
        return {'track':asdict(Track(item['name'],[Segment(0,2500,'こんにちは。' if item['engine']==2 else 'こんばんは。'),
                                                  Segment(3000,5500,'さようなら。')]))}
    def translate(spec,emit):
        calls.append('translate')
        for segment in spec['project']['tracks'][0]['segments']:
            if not segment['translation']:
                emit('translation',id=segment['id'],translation='Bad translation.' if VARIANTS[1][1] in spec['prompt'] else 'Hello.',key='mock')
        emit('done',errors=0)
    def ask(self,instruction,payload,schema,folder,model=None):
        calls.append('judge')
        result = {}
        target = payload['targets'][0]
        for key,field in schema['properties'].items():
            if 'enum' not in field:
                value = 'Hello there.'
            elif 'ok' in field['enum']:
                value = 'meaning' if target['en']=='Bad translation.' else 'ok'
            else:
                value = 'b'
            result[key] = value
        return result
    monkeypatch.setattr(PipelineRunner,'audio',audio)
    monkeypatch.setattr(PipelineRunner,'asr',asr)
    monkeypatch.setattr(PipelineRunner,'ask',ask)
    monkeypatch.setattr(embedded_llm,'translate',translate)
    return calls,translate


def test_full_pipeline_sequential_variants_review_exports_and_resume(config,tmp_path,monkeypatch):
    calls,_ = install_fake_engines(monkeypatch,config)
    create_run(config,tmp_path/'run')
    manifest = tmp_path/'run/manifest.json'
    events = []
    run_pipeline(manifest,lambda kind,**data:events.append({'type':kind,**data}))
    state = load_run(manifest)
    assert all(s['status']=='completed' for s in state['stages'])
    assert calls[:3]==['audio','Whisper','Qwen']
    assert calls.count('translate')==2
    final = read_json(tmp_path/'run/layout/result.json')['track']
    assert all(s['translation']=='Hello there.' for s in final['segments'])
    assert any('rozbieżne ASR' in note for s in final['segments'] for note in s['notes'])
    assert all(not any(n.startswith('AI:') for n in s['notes']) for s in final['segments'])
    assert len(state['exports'])==4 and all(Path(p).is_file() for p in state['exports'])
    assert all(s['status']=='completed' for s in read_json(Path(config['output_dir'])/'report.json')['stages'])
    assert any(e['type']=='pipeline_checkpoint' for e in events)
    before = copy.deepcopy(state)
    calls.clear()
    run_pipeline(manifest,lambda *args,**kwargs:None)
    assert calls==[]
    assert load_run(manifest)['final_track']==before['final_track']


def test_balanced_context_review_repairs_and_records_before_after(config,tmp_path,monkeypatch):
    config.update(review='balanced',review_action='repair',film_context=True)
    install_fake_engines(monkeypatch,config)
    ordinary=PipelineRunner.ask
    def ask(self,instruction,payload,schema,folder,model=None):
        if schema['required']==['overview']:
            return {'overview':'Two people meet and say goodbye.'}
        if 'memory' in schema['required']:
            return {**{s['id']:'meaning' for s in payload['targets']},'memory':'Keep greetings consistent.'}
        return ordinary(self,instruction,payload,schema,folder,model)
    monkeypatch.setattr(PipelineRunner,'ask',ask)
    create_run(config,tmp_path/'run');manifest=tmp_path/'run/manifest.json'
    run_pipeline(manifest,lambda *a,**kw:None)
    state=load_run(manifest)
    assert state['film_context']=='Two people meet and say goodbye.'
    assert all(s['status']=='completed' for s in state['stages'])
    assert state['review_changed_cues']==2
    report=read_json(Path(config['output_dir'])/'report.json')
    assert report['review_changed_cues']==2
    assert all(c['before']=='Bad translation.' and c['after']=='Hello there.' for c in report['review_changes'])
    assert report['continuity_notes']=='Keep greetings consistent.'


def test_explicit_check_only_and_legacy_balanced_never_schedule_rewrites(config):
    config.update(review='deep',review_action='check')
    assert 'repair' not in [s['id'] for s in plan(config)]
    config.pop('review_action');config['review']='balanced'
    assert 'repair' not in [s['id'] for s in plan(config)]
    config['review_action']='repair'
    assert 'repair' in [s['id'] for s in plan(config)]


def test_partial_translation_failure_and_resume_preserve_ids(config,tmp_path,monkeypatch):
    calls,normal = install_fake_engines(monkeypatch,config)
    first = []
    def interrupted(spec,emit):
        segment = spec['project']['tracks'][0]['segments'][0]
        first.append(segment['id'])
        emit('translation',id=segment['id'],translation='Checkpoint.',key='checkpoint-key')
        raise RuntimeError('GPU interruption')
    monkeypatch.setattr(embedded_llm,'translate',interrupted)
    create_run(config,tmp_path/'run')
    path = tmp_path/'run/manifest.json'
    with pytest.raises(RuntimeError,match='interruption'):
        run_pipeline(path,lambda *args,**kwargs:None)
    assert read_json(path)['status']=='failed'
    partial = read_json(tmp_path/'run/en-0/partial.json')['track']
    assert partial['segments'][0]['translation']=='Checkpoint.'
    monkeypatch.setattr(embedded_llm,'translate',normal)
    calls.clear()
    run_pipeline(path,lambda *args,**kwargs:None)
    recovered = read_json(tmp_path/'run/en-0/result.json')['track']
    assert recovered['id']==partial['id']
    assert recovered['segments'][0]['id']==first[0]
    assert recovered['segments'][0]['translation']=='Checkpoint.'
    assert 'audio' not in calls and 'Whisper' not in calls and 'Qwen' not in calls


def test_manifest_rejects_asset_and_config_changes(config,tmp_path):
    create_run(config,tmp_path/'run')
    path = tmp_path/'run/manifest.json'
    assert load_run(path)['config']==config
    Path(config['media']).write_bytes(b'changed audio')
    with pytest.raises(ValueError,match='zmienił'):
        load_run(path)
    state = read_json(path)
    state['config']['review']='rules'
    write_json(path,state)
    with pytest.raises(ValueError,match='konfigurację'):
        load_run(path)


def test_completed_stage_corruption_stops_resume(config,tmp_path,monkeypatch):
    install_fake_engines(monkeypatch,config)
    create_run(config,tmp_path/'run')
    path = tmp_path/'run/manifest.json'
    run_pipeline(path,lambda *a,**kw:None)
    write_json(tmp_path/'run/asr-0/result.json',{'track':'modified'})
    with pytest.raises(ValueError,match='Zmieniono wynik'):
        run_pipeline(path,lambda *a,**kw:None)


def test_plan_depth_duplicates_and_range_validation(config):
    stages = [s['id'] for s in plan(config)]
    assert stages.index('merge-1')<stages.index('en-0')<stages.index('choose-en')<stages.index('semantic')<stages.index('repair')<stages.index('verify')
    config['review']='rules'
    assert 'semantic' not in [s['id'] for s in plan(config)]
    config['asr'][1]=copy.deepcopy(config['asr'][0])
    with pytest.raises(ValueError,match='Powielono'):
        validate_config(config)
    config['asr'][1]['vad']=True
    validate_config(config)
    config['duration']=7000
    with pytest.raises(ValueError,match='wykracza'):
        validate_config(config)


def test_selection_never_chooses_empty_or_invents_source(config):
    a = Track('a',[Segment(0,1000,'はい。')])
    b = Track('b',[Segment(0,1000,'いいえ。'),Segment(2000,3000,'次。')])
    groups = compare_tracks(a,b)
    choices = {group_key(g):'b?' for g in groups}
    result = select_asr(groups,choices,'selected')
    assert [s.text for s in result.segments]==[s.text for s in b.segments]
    assert all(s.parents for s in result.segments)
    choices[group_key(groups[1])]='a'
    with pytest.raises(ValueError,match='pustego'):
        select_asr(groups,choices,'bad')
    with pytest.raises(ValueError):
        validate_choices({'wrong':'a'},['id'],['a','b'])


def test_translation_selection_requires_exact_source_alignment():
    base = Track('jp',[Segment(1000,3000,'はい。')])
    a,b = clone_track(base,'a'),clone_track(base,'b')
    a.segments[0].translation='Yes.'
    b.segments[0].translation='Right.'
    result = choose_english(base,[a,b],{base.segments[0].id:'b?'})
    assert result.segments[0].translation=='Right.'
    assert b.segments[0].id in result.segments[0].parents
    assert result.segments[0].notes
    b.segments[0].start+=100
    with pytest.raises(ValueError,match='czasy'):
        choose_english(base,[a,b],{base.segments[0].id:'b'})


def test_auto_layout_preserves_content_and_marks_estimated_splits():
    source = Track('jp',[Segment(1000,11000,'今日は晴れです。明日は雨です。',translation='It is sunny today. Tomorrow it will rain.')])
    unchanged = format_final(source,ReviewSettings(),False)
    assert len(unchanged.segments)==1 and unchanged.segments[0].start==1000
    split = format_final(source,ReviewSettings(),True)
    assert len(split.segments)==2
    assert split.segments[0].start==1000 and split.segments[-1].end==11000
    assert all(s.parents==[source.segments[0].id] for s in split.segments)
    assert all(any('szacowany' in n for n in s.notes) for s in split.segments)
    assert ''.join(s.text for s in split.segments)==source.segments[0].text
    assert ' '.join(s.translation for s in split.segments).split()==source.segments[0].translation.split()


def test_asr_small_boundary_drift_is_clamped_and_large_error_stops():
    track = Track('test',[Segment(0,20070,'はい。')])
    normalize_asr_times(track,10000,20000,60000)
    assert track.segments[0].end==30000 and track.segments[0].notes
    with pytest.raises(ValueError,match='czasy'):
        normalize_asr_times(Track('bad',[Segment(0,21000,'はい。')]),10000,20000,60000)


def test_same_run_cannot_execute_twice_or_change_manifest_when_locked(config,tmp_path):
    create_run(config,tmp_path/'run')
    manifest = tmp_path/'run/manifest.json'
    before = manifest.read_bytes()
    with pipeline_lock(tmp_path/'run'):
        with pytest.raises(PipelineBusyError):
            run_pipeline(manifest,lambda *a,**kw:None)
    assert manifest.read_bytes()==before


def test_bad_ai_ids_fall_back_to_marked_choice_not_fabricated_text(config,tmp_path,monkeypatch):
    create_run(config,tmp_path/'run')
    runner = PipelineRunner(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    runner.current = runner.state['stages'][0]
    monkeypatch.setattr(runner,'ask',lambda *a,**kw:{'wrong-id':'b'})
    folder = tmp_path/'choice'
    folder.mkdir()
    decisions = runner.choices(folder,[{'id':'cue','a':'はい','b':'いいえ'}],['a','b','a?','b?'],'Choose')
    assert decisions=={'cue':'a?'}


def test_optional_lm_studio_judge_and_preflight_before_asr(config,tmp_path,monkeypatch):
    import httpx
    from studio.pipeline import choice_schema
    from studio import pipeline_worker
    config['backend']='lmstudio'
    config['judge_model']='qwen-local'
    for item in config['translations']:
        item['model']='qwen-local'
    create_run(config,tmp_path/'run')
    runner = PipelineRunner(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    requests = []
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def get(self,url):
            requests.append(('get',url))
            return httpx.Response(200,json={'data':[{'id':'qwen-local'}]},request=httpx.Request('GET',url))
        def post(self,url,json):
            requests.append(('post',url))
            assert json['model']=='qwen-local' and json['response_format']['json_schema']['strict']
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"cue":"b"}'}}]},
                                  request=httpx.Request('POST',url))
    monkeypatch.setattr(pipeline_worker.httpx,'Client',Client)
    assert runner.ask('Choose',{'targets':[{'id':'cue'}]},choice_schema(['cue'],['a','b']),tmp_path)=={'cue':'b'}
    def stop_before_audio(*args):
        assert requests[-1][0]=='get'
        raise RuntimeError('Reached audio after preflight')
    monkeypatch.setattr(runner,'stage',stop_before_audio)
    with pytest.raises(RuntimeError,match='after preflight'):
        runner.run()


def test_pipeline_pause_adopts_manual_jp_then_resumes_without_repeating_asr(config,tmp_path,monkeypatch):
    from studio.pipeline import track_from
    from studio.pipeline_worker import approve_review
    calls,_=install_fake_engines(monkeypatch,config)
    config['pause_uncertain']=True
    create_run(config,tmp_path/'run')
    path=tmp_path/'run/manifest.json'
    run_pipeline(path,lambda *a,**kw:None)
    state=load_run(path)
    assert state['status']=='awaiting_review' and calls.count('translate')==0
    track=track_from(read_json(tmp_path/'run/merge-1/result.json')['track'])
    track.segments[0].text='手動で確認した日本語。'
    approve_review(path,track)
    calls.clear();run_pipeline(path,lambda *a,**kw:None)
    assert 'Whisper' not in calls and 'Qwen' not in calls and 'audio' not in calls
    final=read_json(tmp_path/'run/layout/result.json')['track']
    assert final['segments'][0]['text']=='手動で確認した日本語。'
    assert load_run(path)['manual_reviews']
    assert list((tmp_path/'run/merge-1').glob('before-review-*'))


def test_deleted_audio_cache_is_rebuilt_without_repeating_completed_models(config,tmp_path,monkeypatch):
    calls,_=install_fake_engines(monkeypatch,config)
    cached=tmp_path/'regenerable.wav'
    def audio(self,folder):
        calls.append('audio');cached.write_bytes(b'cache');return {'audio':str(cached)}
    monkeypatch.setattr(PipelineRunner,'audio',audio)
    create_run(config,tmp_path/'run');manifest=tmp_path/'run/manifest.json'
    run_pipeline(manifest,lambda *a,**kw:None)
    final=load_run(manifest)['final_track'];cached.unlink();calls.clear()
    run_pipeline(manifest,lambda *a,**kw:None)
    assert calls==['audio'] and cached.exists() and load_run(manifest)['final_track']==final


@pytest.mark.parametrize('format_',['srt','ass','ssa','txt'])
def test_pipeline_exports_selected_format(config,tmp_path,monkeypatch,format_):
    install_fake_engines(monkeypatch,config)
    config['export_format']=format_
    create_run(config,tmp_path/'run');run_pipeline(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    assert (Path(config['output_dir'])/('Japanese.'+format_)).is_file()
    assert (Path(config['output_dir'])/('English.'+format_)).is_file()


@pytest.mark.parametrize('all_fail',[False,True])
def test_rejected_alignment_is_quarantined_and_never_translated(config,tmp_path,monkeypatch,all_fail):
    from studio.pipeline_worker import AsrQualityError
    calls,_=install_fake_engines(monkeypatch,config)
    normal=PipelineRunner.asr
    def asr(self,folder,item,audio):
        if all_fail or item['engine']==1: raise AsrQualityError('Missing word timing')
        return normal(self,folder,item,audio)
    monkeypatch.setattr(PipelineRunner,'asr',asr)
    config['asr_failure_policy']='continue'
    create_run(config,tmp_path/'run');manifest=tmp_path/'run/manifest.json'
    if all_fail:
        with pytest.raises(AsrQualityError,match='Wszystkie'): run_pipeline(manifest,lambda *a,**kw:None)
        assert 'translate' not in calls
        assert load_run(manifest)['status']=='failed'
    else:
        run_pipeline(manifest,lambda *a,**kw:None)
        state=load_run(manifest)
        assert state['status']=='needs_review' and len(state['asr_failures'])==1
        report=read_json(Path(config['output_dir'])/'report.json')
        assert report['asr_failures'][0]['stage']=='asr-1'
        assert 'track' not in read_json(tmp_path/'run/asr-1/result.json')
        calls.clear();run_pipeline(manifest,lambda *a,**kw:None)
        assert not calls and len(load_run(manifest)['asr_failures'])==1


def test_continue_policy_never_hides_memory_or_configuration_errors(config,tmp_path,monkeypatch):
    install_fake_engines(monkeypatch,config)
    config['asr_failure_policy']='continue'
    monkeypatch.setattr(PipelineRunner,'asr',lambda *a: (_ for _ in ()).throw(RuntimeError('out of memory')))
    create_run(config,tmp_path/'run')
    with pytest.raises(RuntimeError,match='out of memory'):run_pipeline(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    state=load_run(tmp_path/'run/manifest.json')
    assert state['stages'][1]['status']=='failed' and 'seconds' in state['stages'][1]
    assert state['stages'][2]['status']=='pending'


def test_decision_batches_are_strict_and_resumable(config,tmp_path,monkeypatch):
    config['decision_batch_size']=4
    create_run(config,tmp_path/'run');runner=PipelineRunner(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    runner.current={'id':'test'};calls=[]
    def ask(instruction,payload,schema,folder):
        calls.append([item['id'] for item in payload['targets']])
        return {key:'b' for key in schema['required']}
    monkeypatch.setattr(runner,'ask',ask)
    folder=tmp_path/'decisions';folder.mkdir()
    items=[{'id':str(i),'jp':'こんにちは'} for i in range(9)]
    result=runner.choices(folder,items,['a','b','a?','b?'],'choose')
    assert result=={str(i):'b' for i in range(9)} and list(map(len,calls))==[4,4,1]
    calls.clear();assert runner.choices(folder,items,['a','b','a?','b?'],'choose')==result
    assert not calls


@pytest.mark.parametrize('verdict',['faithful','uncertain','incorrect'])
def test_pipeline_repair_checks_source_without_english_anchoring(config,tmp_path,monkeypatch,verdict):
    config['source_guard']=True
    create_run(config,tmp_path/'run');runner=PipelineRunner(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    runner.current={'id':'repair'}
    source=Track('source',[Segment(0,2500,'こんにちは。',translation='Wrong.',status='machine',notes=['AI: possible meaning error'])])
    calls=[]
    def ask(instruction,payload,schema,folder):
        calls.append(payload)
        definition=next(iter(schema['properties'].values()))
        if 'enum' not in definition:
            assert 'Wrong.' not in str(payload) and 'current_en' not in str(payload)
            value='Hello.'
        elif 'faithful' in definition['enum']:
            assert payload['targets'][0]['proposed_english']=='Hello.' and 'Wrong.' not in str(payload)
            value=verdict
        else:
            assert verdict=='faithful'
            value='b'
        return {source.segments[0].id:value}
    monkeypatch.setattr(runner,'ask',ask)
    folder=tmp_path/'repair';folder.mkdir();result=runner.repair(folder,source)
    assert result['track']['segments'][0]['translation']==('Hello.' if verdict=='faithful' else 'Wrong.')
    assert len(calls)==(3 if verdict=='faithful' else 2)
    assert bool(result['changes'])==(verdict=='faithful')


def test_asr_combination_keeps_existing_cue_times_without_new_overlap():
    from studio.pipeline import compatible_asr_choices
    left=Track('a',[Segment(0,1000,'一'),Segment(1000,2000,'二')])
    right=Track('b',[Segment(0,900,'壱'),Segment(900,2000,'弐')])
    groups=compare_tracks(left,right)
    requested={group_key(g):side for g,side in zip(groups,('a','b'))}
    decisions=compatible_asr_choices(groups,requested)
    result=select_asr(groups,decisions,'selected')
    assert all(a.end<=b.start for a,b in zip(result.segments,result.segments[1:]))
    assert decisions!=requested
    assert all((s.start,s.end,s.text) in {(x.start,x.end,x.text) for x in left.segments+right.segments} for s in result.segments)


def test_readability_wrap_and_bounded_extension_preserve_manual_times():
    track=Track('source',[Segment(0,500,'これは長い日本語の文章ですが表示の折り返しを確認します。',translation='Hello world.'),
                          Segment(1300,1600,'はい。',translation='Yes.',status='manual'),
                          Segment(2200,2400,'はい。',translation='Yes.')])
    result=format_final(track,ReviewSettings(),False,True,2500)
    assert result.segments[0].start==0 and result.segments[0].end==750
    assert result.segments[1].end==1600
    assert result.segments[2].end==2500
    assert result.segments[0].text.replace('\n','')==track.segments[0].text
    assert all(len(line)<=20 for line in result.segments[0].text.splitlines())
    assert any('ekspozycja' in n for n in result.segments[0].notes)
    assert track.segments[0].end==500


def test_source_question_cannot_be_approved_as_a_statement(config,tmp_path,monkeypatch):
    from studio.pipeline import source_surface_conflicts
    assert source_surface_conflicts('日本の好きじゃないところってある?', 'I dislike some places.')
    assert not source_surface_conflicts('ある？', 'Any places?')
    assert not source_surface_conflicts('そうですね。','Yes.')
    config['source_guard']=True
    create_run(config,tmp_path/'run');runner=PipelineRunner(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    runner.current={'id':'repair'}
    track=Track('source',[Segment(0,2000,'嫌いなところってある?',translation='Is there anything you dislike?',notes=['AI: check'],status='machine')])
    calls=[]
    def ask(instruction,payload,schema,folder):
        calls.append(1)
        return {track.segments[0].id:'I dislike some places.'}
    monkeypatch.setattr(runner,'ask',ask)
    folder=tmp_path/'repair';folder.mkdir();result=runner.repair(folder,track)
    assert result['track']['segments'][0]['translation']=='Is there anything you dislike?'
    assert not result['changes'] and len(calls)==1


def test_jp_only_has_no_llm_assets_calls_or_english_export(config,tmp_path,monkeypatch):
    calls,_=install_fake_engines(monkeypatch,config)
    config.update(transcription_only=True,asr=[{**config['asr'][0],'vad':True}],translations=[],judge_model='',
                  film_context=True,llm_keep_loaded=True,retry_asr={'enabled':False})
    # Even deliberately unusable translator paths must not block transcription.
    config['settings'].update(llm_exe='missing-llm.exe',llm_model='',crisp_vad=config['media'])
    monkeypatch.setattr(PipelineRunner,'ask',lambda *a,**kw:pytest.fail('JP-only must never invoke LLM'))
    create_run(config,tmp_path/'run');run_pipeline(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    state=load_run(tmp_path/'run/manifest.json')
    assert [s['id'] for s in state['stages']]==['audio','asr-0','jp-layout','jp-export']
    assert calls==['audio','Whisper']
    assert (Path(config['output_dir'])/'Japanese.srt').exists()
    assert not (Path(config['output_dir'])/'English.srt').exists()
    assert not any('missing-llm' in a['path'] for a in state['assets'])
    calls.clear();run_pipeline(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    assert not calls


def test_audio_retry_checkpoint_resumes_and_rejects_modified_decision(config,tmp_path,monkeypatch):
    from studio.pipeline import digest
    config['retry_asr']={'enabled':True,'max_targets':1,'auxiliary':config['asr'][1]}
    create_run(config,tmp_path/'run');runner=PipelineRunner(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    runner.current={'id':'asr-retry'}
    base=Track('base',[Segment(0,1000,'最初の文。'),Segment(1200,2200,'間違った文。'),Segment(2400,3400,'最後の文。')])
    scores={base.segments[1].id:{'mean':.4,'low_ratio':.3}}
    calls=[]
    def decode(folder,item,audio,start,end):
        calls.append(item['name'])
        track=Track('retry',[Segment(0,1000,'最初の文。'),Segment(1200,2200,'正しい文。'),Segment(2400,3400,'最後の文。')])
        return {'track':asdict(track),'confidence':{s.id:{'mean':.9} for s in track.segments}}
    monkeypatch.setattr(runner,'retry_decode',decode)
    monkeypatch.setattr(runner,'call',lambda args,folder,name,timeout:Path(args[-1]).write_bytes(b'cached WAV'))
    folder=tmp_path/'retry';folder.mkdir()
    first=runner.retry_asr(folder,base,'source.wav',scores)
    assert len(calls)==2 and len(first['changes'])==1
    assert first['track']['segments'][1]['text']=='正しい文。' and base.segments[1].text=='間違った文。'
    calls.clear();runner.retry_asr(folder,base,'source.wav',scores);assert not calls
    partial=read_json(folder/'partial.json');partial['windows'][0]['applied']=False;write_json(folder/'partial.json',partial)
    with pytest.raises(ValueError,match='decyzję'):runner.retry_asr(folder,base,'source.wav',scores)


def test_source_review_precedes_translation_and_preserves_legacy_plan(config,tmp_path,monkeypatch):
    old=[s['id'] for s in plan(config)]
    assert 'jp-review' not in old
    config['source_review_version']=1
    keys=[s['id'] for s in plan(config)]
    assert keys.index('merge-1')<keys.index('jp-review')<keys.index('en-0')
    install_fake_engines(monkeypatch,config)
    create_run(config,tmp_path/'run');run_pipeline(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    review=read_json(tmp_path/'run/jp-review/result.json')
    assert review['fragments'] and not review['changes']
    assert read_json(Path(config['output_dir'])/'report.json')['jp_review']==review


def test_jp_source_review_pipeline_applies_local_phrases_and_resumes(config,tmp_path,monkeypatch):
    from tests.test_asr_review import example
    base,window,scores=example()
    config.update(source_review_version=1,transcription_only=True,asr=[{**config['asr'][0],'vad':True}],
                  translations=[],judge_model='',retry_asr={'enabled':True})
    config['settings']['crisp_vad']=config['media']
    window['attempts'][0]['model']=config['asr'][0]['model']
    monkeypatch.setattr(PipelineRunner,'audio',lambda *a:{'audio':config['media']})
    monkeypatch.setattr(PipelineRunner,'asr',lambda *a:{'track':asdict(base),'confidence':scores})
    # Legacy retry track must not override the new phrase decision.
    monkeypatch.setattr(PipelineRunner,'retry_asr',lambda *a:{'track':asdict(base),'windows':[window],'changes':[]})
    monkeypatch.setattr(PipelineRunner,'ask',lambda *a,**kw:pytest.fail('No LLM in JP source review'))
    create_run(config,tmp_path/'run');manifest=tmp_path/'run/manifest.json'
    run_pipeline(manifest,lambda *a,**kw:None)
    state=load_run(manifest)
    assert state['jp_review_changes']==2 and state['jp_review_changed_cues']==1
    assert [s['id'] for s in state['stages']]==['audio','asr-0','asr-retry','jp-review','jp-layout','jp-export']
    final=read_json(tmp_path/'run/jp-layout/result.json')['track']
    assert 'いつでも' in final['segments'][1]['text']
    assert [(s['start'],s['end']) for s in final['segments']]==[(s.start,s.end) for s in base.segments]
    monkeypatch.setattr(PipelineRunner,'asr',lambda *a:pytest.fail('Resume must reuse ASR'))
    run_pipeline(manifest,lambda *a,**kw:None)
    artifact=tmp_path/'run/jp-review/result.json';value=read_json(artifact)
    value['fragments'][0]['applied']=True;write_json(artifact,value)
    with pytest.raises(ValueError,match='jp-review'):run_pipeline(manifest,lambda *a,**kw:None)


def test_invalid_utf8_asr_is_a_quality_rejection_not_a_silent_recode(config,tmp_path,monkeypatch):
    from studio import pipeline_worker
    from studio.pipeline_worker import AsrQualityError
    create_run(config,tmp_path/'run');runner=PipelineRunner(tmp_path/'run/manifest.json',lambda *a,**kw:None)
    folder=tmp_path/'native';folder.mkdir()
    monkeypatch.setattr(pipeline_worker,'whisper_command',lambda *a:[])
    def call(args,directory,name,timeout):
        if name=='engine':(directory/'transcript.srt').write_bytes(b'1\n00:00:00,000 --> 00:00:01,000\n\x8d\n')
        return 'ok'
    monkeypatch.setattr(runner,'call',call)
    item={**config['asr'][0],'engine':0}
    with pytest.raises(AsrQualityError,match='uszkodzony tekst'):runner.asr(folder,item,'source.wav')

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from studio.asr_review import review_fragments
from studio.jp_context_review import context_request, review_context
from studio.source_review_v3 import unresolved_windows
from studio.pipeline_worker import read_json,write_json
from tests.test_asr_review import example


def test_third_decoder_corroborates_only_baseline_retry_with_original_guards():
    base,window,scores=example()
    third=deepcopy(window['attempts'][0]);third['model']='third.gguf'
    window['attempts'].append(third)
    v2=review_fragments(base,[window],scores,'large.bin',version=2)
    v3=review_fragments(base,[window],scores,'large.bin',version=3)
    assert len(v3['changes'])>len(v2['changes'])
    changed=next(r for r in v3['changes'] if r['before']=='の開発度')
    assert changed['supporting_models']==['large.bin','third.gguf']
    assert changed['dissenting_models']==['kotoba.bin']
    assert [(s['start'],s['end']) for s in v3['track']['segments']]==[(s.start,s.end) for s in base.segments]
    # Two auxiliaries agreeing cannot outvote the baseline retry.
    window['attempts'][2]=deepcopy(window['attempts'][1]);window['attempts'][2]['model']='third.gguf'
    assert not any(r['before']=='の開発度' for r in review_fragments(base,[window],scores,'large.bin',version=3)['changes'])
    base.segments[1].status='manual'
    assert not review_fragments(base,[window],scores,'large.bin',version=3)['changes']


def test_third_targets_only_unresolved_not_agreement_or_protected_text():
    base,window,scores=example()
    window['cue_ids']=[s.id for s in base.segments]
    assert unresolved_windows(base,[window],scores,'large.bin')==[window]
    window['attempts'][1]=deepcopy(window['attempts'][0]);window['attempts'][1]['model']='kotoba.bin'
    assert not unresolved_windows(base,[window],scores,'large.bin')
    window['attempts'][1]={'usable':False,'error':'bad timing'}
    assert unresolved_windows(base,[window],scores,'large.bin')==[window]
    base.segments[1].review_status='reviewed'
    assert not unresolved_windows(base,[window],scores,'large.bin')


def test_context_flags_shared_error_without_rewriting_and_replays_exact_choices(tmp_path):
    base,window,scores=example();review=review_fragments(base,[window],scores,'large.bin',version=3)
    before=deepcopy(review);calls=[]
    def ask(instruction,payload,schema,folder):
        calls.append(payload)
        return {k:('suspicious' if k=='status' else 'Possible homophone; listen.' if k=='reason' else 'listen') for k in schema['required']}
    runner=SimpleNamespace(ask=ask,progress=lambda *a:None)
    result=review_context(runner,tmp_path,review)
    assert review==before and len(result['flags'])==len(base.segments)
    assert [s['text'] for s in result['track']['segments']]==[s['text'] for s in review['track']['segments']]
    assert all(not f['applied'] for f in result['flags'])
    assert any('Context:' in r['reason'] for r in result['review']['fragments'])
    calls.clear();review_context(runner,tmp_path,review);assert not calls
    saved=read_json(tmp_path/'decisions.json');first=next(iter(saved['decisions']))
    saved['decisions'][first]['status']='invented dialogue';write_json(tmp_path/'decisions.json',saved)
    with pytest.raises(ValueError,match='Invalid Japanese context choice'):review_context(runner,tmp_path,review)


def test_context_exact_option_ids_manual_protection_and_scene_gap(tmp_path):
    base,window,scores=example();base.segments[0].status='manual'
    review=review_fragments(base,[window],scores,'large.bin',version=3)
    review['track']['segments'][2].update(start=50000,end=51000)
    payload,schema=context_request(review,1)
    assert len(payload['scene'])==2
    assert 'target' not in payload
    assert sum(s['is_target'] for s in payload['scene'])==1
    assert len({s['id'] for s in payload['scene']})==len(payload['scene'])
    assert all(field.get('enum',[])[:2]==['keep','listen'] for key,field in schema['properties'].items() if key.startswith('f'))
    calls=[]
    def ask(instruction,payload,schema,folder):
        calls.append(payload)
        return {k:('ok' if k=='status' else 'No textual concern.' if k=='reason' else 'keep') for k in schema['required']}
    result=review_context(SimpleNamespace(ask=ask,progress=lambda *a:None),tmp_path,review)
    assert len(calls)==2 and not result['flags']
    assert not result['track']['segments'][0]['notes']


@pytest.mark.parametrize('failure',[None,'quality','oom'])
def test_grouped_native_call_owns_clip_outputs_and_never_hides_device_failure(tmp_path,monkeypatch,failure):
    from studio import source_review_v3
    from studio.pipeline_worker import PipelineRunner
    from studio.storage import Settings
    from studio.core import Segment,Track,export_srt
    from types import MethodType
    model=tmp_path/'model.bin';model.write_bytes(b'ggml')
    item={'engine':2,'name':'base','kind':'Whisper / GGML','model':str(model),'vad':False}
    runner=SimpleNamespace(settings=Settings(crisp_gpu_backend='cuda'),config={'media_duration':6000},folder=tmp_path)
    runner.parse_asr=MethodType(PipelineRunner.parse_asr,runner)
    monkeypatch.setattr(source_review_v3,'whisper_cpp_command',lambda settings,model,audio,output,*a:
        ['--file',str(audio),'--output-file',str(output/'transcript')])
    calls=[]
    def call(args,folder,name,timeout):
        if name=='version':return '[backends: cuda cpu]'
        if name=='help':return ''
        calls.append(args)
        for i,at in enumerate([i for i,v in enumerate(args) if v=='--output-file']):
            if failure=='quality' and i==1:continue
            export_srt(Track('t',[Segment(0,1000,'日本語です。')]),__import__('pathlib').Path(args[at+1]+'.srt'))
        log='CUDA out of memory' if failure=='oom' else 'word timestamps required' if failure=='quality' else 'CUDA0 buffer'
        (folder/'engine.log').write_text(log,encoding='utf8')
        if failure=='quality':raise RuntimeError(log)
        return log
    runner.call=call
    jobs=[{'folder':tmp_path/f'clip-{i}','audio':tmp_path/f'audio-{i}.wav','start':i*2000,'end':i*2000+1500} for i in range(2)]
    if failure=='oom':
        with pytest.raises(ValueError,match='memory failure'):source_review_v3.decode_batch(runner,tmp_path/'batch',item,jobs)
    else:
        values=source_review_v3.decode_batch(runner,tmp_path/'batch',item,jobs)
        assert len(calls)==1 and calls[0].count('--file')==2
        assert values[0]['usable'] and values[0]['track']['segments'][0]['start']==0
        assert values[1]['usable']==(failure is None)
        if failure is None:assert values[1]['track']['segments'][0]['start']==2000
        assert all(v['timing_scope']=='amortized-batch' for v in values)
        assert read_json(tmp_path/'batch/batch.json')['clips']==2


@pytest.mark.parametrize('bad_markers',[False,True])
def test_batch_alignment_warning_cannot_contaminate_another_clip_or_be_misattributed(bad_markers):
    from studio.source_review_v3 import split_clip_logs
    jobs=[{'start':0,'end':1000},{'start':5000,'end':7000}]
    log='CUDA0 buffer\ncrispasr: audio: 16000 samples (1.0 s) @ 16000 Hz, 4 threads\nalignment collapse\n'
    log+='crispasr: audio: 32000 samples (2.0 s) @ 16000 Hz, 4 threads\nvalid transcript\n'
    if bad_markers:log=log.replace('32000 samples','48000 samples')
    parts=split_clip_logs(log,jobs)
    assert 'alignment collapse' in parts[0] and 'CUDA0' in parts[1]
    assert ('alignment collapse' in parts[1])==bad_markers


def test_cancelled_batch_hypotheses_are_preserved_but_cannot_be_mistaken_for_new_output(tmp_path):
    from studio.source_review_v3 import preserve_uncommitted_outputs
    (tmp_path/'transcript.srt').write_bytes(b'old hypothesis')
    (tmp_path/'transcript.json').write_bytes(b'old confidence')
    (tmp_path/'window.wav').write_bytes(b'audio')
    preserve_uncommitted_outputs(tmp_path)
    assert not list(tmp_path.glob('*.srt')) and not (tmp_path/'transcript.json').exists()
    assert (tmp_path/'window.wav').read_bytes()==b'audio'
    assert next(tmp_path.glob('previous-uncommitted/*/transcript.srt')).read_bytes()==b'old hypothesis'
    preserve_uncommitted_outputs(tmp_path)
    assert len(list(tmp_path.glob('previous-uncommitted/*')))==1


def test_context_resume_rejects_changed_instructions(tmp_path,monkeypatch):
    from studio import jp_context_review
    base,window,scores=example();review=review_fragments(base,[window],scores,'large.bin',version=3)
    def ask(instruction,payload,schema,folder):
        return {k:('ok' if k=='status' else 'Coherent.' if k=='reason' else 'keep') for k in schema['required']}
    runner=SimpleNamespace(ask=ask,progress=lambda *a:None)
    review_context(runner,tmp_path,review)
    monkeypatch.setattr(jp_context_review,'INSTRUCTION',jp_context_review.INSTRUCTION+' Changed policy.')
    with pytest.raises(ValueError,match='Changed Japanese context review source'):review_context(runner,tmp_path,review)

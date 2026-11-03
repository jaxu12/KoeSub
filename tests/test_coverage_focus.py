from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from studio.core import Segment, Track, normalize
from studio.coverage_focus import (alignment_input,combine_candidates,fragment_candidates,
                                   fragment_confidence,text_contains,validate_insertion)
from studio.pipeline_worker import read_json,write_json
from studio.review import ReviewSettings
from studio.storage import Settings
from tests.test_pipeline import config


def decoded(text,start=1000,end=6000):
    cue=Segment(start,end,text)
    return {'usable':True,'text':text,'track':asdict(Track('decode',[cue])),
            'confidence':{cue.id:{'mean':.95}}}


@pytest.mark.parametrize('side',['prefix','suffix'])
def test_new_phrase_is_extracted_from_merged_asr_without_trimming_existing_cue(side):
    base=Track('base',[Segment(5000,7000,'お帰りなさい。',status='manual',translation='Welcome home.')])
    attempt=decoded('待ってください。お帰りなさい。',2000,6500) if side=='prefix' else decoded('お帰りなさい。待ってください。',5500,10000)
    original=asdict(base)
    proposals=fragment_candidates(base,attempt,{'id':'chunk'},0,12000)
    assert len(proposals)==1 and proposals[0]['cue']['text']=='待ってください。'
    assert proposals[0]['nomination']=='anchored-'+side
    assert asdict(base)==original
    cue=proposals[0]['cue']
    assert cue['end']<5000 if side=='prefix' else cue['start']>7000
    assert proposals[0]['source_cue']['text']==attempt['text']


def test_crop_edge_evidence_is_retained_for_focused_verification_not_exported_directly():
    attempt=decoded('待ってください',5000,8000)
    proposals=fragment_candidates(Track('empty'),attempt,{'id':'edge','start':5000,'end':9000},0,12000)
    assert len(proposals)==1
    assert proposals[0]['cue']['start']==5000 and 'verification' not in proposals[0]


def test_fragment_confidence_uses_matching_token_text_despite_invalid_native_times():
    attempt=decoded('待ってください。お帰りなさい。')
    cue=attempt['track']['segments'][0]
    attempt['document']={'transcription':[{'text':cue['text'],'tokens':[
        {'text':'待ってください。','p':.9,'offsets':{'from':-10,'to':-10}},
        {'text':'お帰りなさい。','p':.2,'offsets':{'from':-10,'to':-10}}]}]}
    assert fragment_confidence(attempt,cue,0,len('待ってください。'))==pytest.approx(.9)


def test_text_corroboration_ignores_segmentation_but_rejects_ambiguous_repetitions():
    assert text_contains(decoded('最初。待ってください。最後。'),'待ってください')
    assert not text_contains(decoded('待ってください。待ってください。'),'待ってください')
    assert not text_contains({'usable':False,'text':'待ってください'},'待ってください')
    assert not text_contains(decoded('どうなるんだろうね'),'ろうね')
    assert not text_contains(decoded('COMPLETION'),'PLETION')
    items,target=alignment_input('最初。\n待って、ください。最後。','待ってください')
    assert target==1 and items[target]['text']=='待ってください'
    assert normalize(''.join(i['text'] for i in items))==normalize('最初。待ってください。最後。')
    with pytest.raises(ValueError,match='ambiguous'):alignment_input('はいはい','はい')


def test_duplicate_windows_combine_sources_without_merging_distant_repeated_lines():
    attempt=decoded('待ってください',1000,3000)
    proposals=fragment_candidates(Track('empty'),attempt,{'id':'a'},0,10000)
    near=deepcopy(proposals[0]);near['cue'].update(start=2000,end=4000)
    far=deepcopy(proposals[0]);far['cue'].update(start=6000,end=8000)
    result=combine_candidates(proposals+[near,far])
    assert len(result)==2 and len(result[0]['sources'])==2


@pytest.mark.parametrize('problem',['overlap','crop_edge','zero_words','changed_text'])
def test_alignment_cannot_add_text_over_existing_manual_work_or_invent_word_times(problem):
    base=Track('base',[Segment(5000,7000,'保護された文。',status='manual')])
    entry={'text':'待って','start':2,'end':3,'words':[{'word':'待って','start':2,'end':3}]}
    if problem=='overlap':entry.update(start=5,end=6,words=[{'word':'待って','start':5,'end':6}])
    if problem=='crop_edge':entry.update(start=0,end=1,words=[{'word':'待って','start':0,'end':1}])
    if problem=='zero_words':entry['words'][0].update(start=2,end=2)
    if problem=='changed_text':entry['text']='違う言葉'
    with pytest.raises(ValueError):validate_insertion(base,'待って',entry,0,10000,ReviewSettings())


def test_caption_endpoints_can_survive_an_unattached_internal_zero_without_inventing_word_times():
    entry={'text':'これは日本語です','start':2,'end':4,'words':[
        {'word':'これ','start':2,'end':2.4},{'word':'は','start':2.7,'end':2.7},
        {'word':'日本語','start':3,'end':3.7},{'word':'です','start':3.7,'end':4}]}
    bounds=validate_insertion(Track('empty'),'これは日本語です',entry,0,10000,ReviewSettings())
    assert (bounds['start'],bounds['speech_end'])==(2000,4000)
    assert not bounds['word_timing_complete']
    assert bounds['words'][1]['start']==bounds['words'][1]['end']==2700


def test_confirmed_insertions_select_a_global_nonoverlapping_set_but_do_not_elect_lexical_conflicts():
    from studio.asr_coverage import select_focused
    def record(start,end,text):
        return {'cue':{'start':start,'end':end,'text':text},'eligible':True,'confidence':.95,
                'verification':{'version':2,'alignment':{'bounds':{'word_timing_complete':True}}}}
    rows=[record(0,4000,'最初の言葉'),record(2000,6500,'時間が重なる別の言葉'),record(5000,8000,'最後の長い言葉です')]
    assert select_focused(rows)=={0,2}
    assert 'selected coverage' in rows[1]['reason']
    conflicts=[record(1000,3000,'東京でした'),record(1100,3100,'大阪でした')]
    assert not select_focused(conflicts)
    assert all('Contradictory' in row['reason'] for row in conflicts)


@pytest.mark.parametrize('peer_result',['exact','disagree','third','oom'])
def test_focused_audio_pipeline_aligns_new_phrase_and_replays_without_touching_originals(tmp_path,monkeypatch,peer_result):
    from studio import source_review_v3
    from studio.asr_coverage import search_coverage
    base=Track('base',[Segment(5000,7000,'お帰りなさい。',status='manual',comment='human note')]);before=asdict(base)
    audio=tmp_path/'audio.wav'
    with wave.open(str(audio),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*16000*10)
    for name in ('base.bin','aux.bin','third.bin','align.bin','runtime.exe'):(tmp_path/name).write_bytes(b'local fixture')
    models=[{'engine':2,'vad':False,'model':str(tmp_path/name)} for name in ('base.bin','aux.bin','third.bin')]
    config={'asr_coverage':{'enabled':True,'version':2},'start':0,'duration':10000,'review_settings':{},
            'asr':[models[0]],'retry_asr':{'auxiliary':models[1],'third':models[2]}}
    calls=[]
    def decode(runner,root,item,jobs,**options):
        assert options=={'text_only':True}
        if not jobs:return []
        calls.append(item['model'])
        if peer_result=='oom' and item==models[1]:raise ValueError('CUDA memory failure')
        result=[]
        for job in jobs:
            text='待ってください。お帰りなさい。'
            if item==models[1] and peer_result in ('third','disagree'):text='別の言葉です。'
            if item==models[2] and peer_result=='disagree':text='さらに別の言葉。'
            value=decoded(text,2000,6500);value.update(model=item['model'],directory=str(job['folder']))
            result.append(value)
        return result
    monkeypatch.setattr(source_review_v3,'decode_batch',decode)
    def call(args,folder,name,timeout):
        if name=='crop':Path(args[-1]).write_bytes(audio.read_bytes())
        else:
            transcript=read_json(Path(args[args.index('--text-file')+1]))
            entries=[{'text':item['text'],'start':3,'end':4,'words':[{'word':item['text'],'start':3,'end':4}]} for item in transcript]
            write_json(Path(args[args.index('--align-output')+1]),entries)
        return 'CUDA0 buffer'
    runner=SimpleNamespace(config=config,settings=Settings(crisp_aligner=str(tmp_path/'align.bin'),crisp_exe=str(tmp_path/'runtime.exe'),reserve_gib=0),
                           folder=tmp_path,call=call,event=lambda *a,**k:None,progress=lambda *a:None)
    folder=tmp_path/'coverage';folder.mkdir()
    if peer_result=='oom':
        with pytest.raises(ValueError,match='CUDA memory'):search_coverage(runner,folder,base,audio)
        return
    result=search_coverage(runner,folder,base,audio)
    assert asdict(base)==before
    assert len(result['changes'])==(peer_result!='disagree')
    if result['changes']:
        added=result['changes'][0]['after'];assert added['text']=='待ってください。' and added['end']<5000
        assert result['changes'][0]['verification']['alignment']['bounds']['words']
        assert next(c for c in result['track']['segments'] if c['id']==base.segments[0].id)==before['segments'][0]
    count=len(calls)
    assert search_coverage(runner,folder,base,audio)==result and len(calls)==count
    assert not list(folder.glob('*/window.wav'))
    receipt=next(folder.glob('*/scan/receipt.json'));saved=read_json(receipt);saved['result']['text']='changed';write_json(receipt,saved)
    with pytest.raises(ValueError,match='focused coverage receipt'):search_coverage(runner,folder,base,audio)


def test_full_pipeline_preserves_focused_insertions_through_review_export_and_replay(config,tmp_path,monkeypatch):
    from studio import source_review_v3
    from studio.core import load_srt
    from studio.pipeline import create_run,load_run
    from studio.pipeline_worker import PipelineRunner,run_pipeline
    base=Track('base',[Segment(5000,7000,'お帰りなさい。',status='manual',comment='protected')])
    audio=tmp_path/'real-shape-fixture.wav'
    with wave.open(str(audio),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*16000*10)
    config.update(media=str(audio),duration=10000,media_duration=10000,transcription_only=True,source_review_version=3,
                  translations=[],review='rules',asr=[{**config['asr'][0],'vad':True}],
                  asr_coverage={'enabled':True,'version':2},
                  retry_asr={'enabled':True,'auxiliary':{'engine':1,'model':config['settings']['llm_model']}})
    config['settings'].update(crisp_aligner=str(audio),crisp_vad=str(audio))
    calls=[]
    def decode(runner,root,item,jobs,**kwargs):
        calls.append(len(jobs))
        return [dict(decoded('待ってください。お帰りなさい。',2000,6500),model=item['model'],directory=str(job['folder'])) for job in jobs]
    def call(self,args,folder,name,timeout):
        if name=='crop':Path(args[-1]).write_bytes(audio.read_bytes())
        else:
            units=read_json(Path(args[args.index('--text-file')+1]))
            write_json(Path(args[args.index('--align-output')+1]),[
                {'text':unit['text'],'start':3,'end':4,'words':[{'word':unit['text'],'start':3,'end':4}]} for unit in units])
        return 'CUDA0 buffer'
    monkeypatch.setattr(source_review_v3,'decode_batch',decode)
    monkeypatch.setattr(PipelineRunner,'audio',lambda *a:{'audio':str(audio)})
    monkeypatch.setattr(PipelineRunner,'asr',lambda *a:{'track':asdict(base)})
    monkeypatch.setattr(PipelineRunner,'call',call)
    create_run(config,tmp_path/'run');manifest=tmp_path/'run/manifest.json'
    run_pipeline(manifest,lambda *a,**k:None)
    state=load_run(manifest);report=read_json(tmp_path/'exports/report.json')
    assert all(s['status']=='completed' for s in state['stages'])
    assert len(report['asr_coverage']['changes'])==1 and report['asr_coverage']['version']==2
    cues=load_srt(tmp_path/'exports/Japanese.srt').segments
    assert [s.text for s in cues]==['待ってください。','お帰りなさい。']
    assert (cues[1].start,cues[1].end)==(5000,7000)
    before=list(calls);run_pipeline(manifest,lambda *a,**k:None);assert calls==before

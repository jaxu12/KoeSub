from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
import wave

import pytest

from studio import adaptive_asr
from studio.core import Segment,Track
from studio.pipeline import clone_track,track_from
from studio.pipeline_worker import read_json,write_json
from studio.audio_alignment import alignment_groups


def wav(path,seconds=30):
    with wave.open(str(path),'wb') as audio:
        audio.setparams((1,2,16000,0,'NONE','not compressed'))
        audio.writeframes(b'\0\0'*round(seconds*16000))


def scenario(tmp_path,monkeypatch):
    raw=Track('base',[Segment(0,1000,'魚の話です。'),Segment(5000,9000,'新鮮な魚いつでも国の開発度が一番いいところですね。'),
        Segment(15000,16000,'日本の食べ物です。'),Segment(24000,25000,'最後の文章です。')])
    base=clone_track(raw,'review')
    fragment={'cue_id':raw.segments[1].id,'applied':False,'alternatives':[{'usable':True,'normalized':'甲'},{'usable':True,'normalized':'乙'}]}
    review={'track':asdict(base),'fragments':[fragment]}
    context={'flags':[{'review_cue_id':base.segments[3].id,'status':'suspicious'}]}
    runner=SimpleNamespace(config={'start':0,'duration':30000,'adaptive_retry':{'enabled':True,'max_targets':1},
        'asr':[{'model':'large.bin','name':'Large'}],'retry_asr':{'auxiliary':{'model':'kotoba.bin','name':'Kotoba'}}},
        settings=SimpleNamespace(ffmpeg='ffmpeg'),event=lambda *a,**k:None,progress=lambda *a:None)
    audio=tmp_path/'input.wav';wav(audio);folder=tmp_path/'adaptive';folder.mkdir()
    calls=[]
    def call(args,directory,name,timeout):
        wav(directory/'audio.partial.wav',float(args[args.index('-t')+1]));return ''
    def decode(runner,root,item,jobs):
        calls.append((item['model'],item['vad_options']))
        result=[]
        for job in jobs:
            cue=Segment(5100,8900,'新鮮な魚いつでも国配列道が一番いいところですね。')
            result.append({'usable':True,'track':asdict(Track('retry',[cue])),'model':item['model'],'name':item['name'],
                'directory':str(job['folder']),'seconds':1,'confidence':{cue.id:{'mean':.95}}})
        return result
    runner.call=call;monkeypatch.setattr(adaptive_asr,'decode_batch',decode)
    return runner,folder,base,review,audio,{raw.segments[1].id:{'mean':.6}},context,calls


def test_adaptive_profiles_are_bounded_grouped_and_replay_immutable_receipts(tmp_path,monkeypatch):
    runner,folder,base,review,audio,scores,context,calls=scenario(tmp_path,monkeypatch)
    before=deepcopy(base)
    result=adaptive_asr.adaptive_retry(runner,folder,base,review,audio,scores,context)
    assert len(result['windows'])==1 and len(result['windows'][0]['attempts'])==4
    assert len(calls)==4 and calls[0][1]['speech_pad_ms']!=calls[1][1]['speech_pad_ms']
    assert result['changes'] and any(d['reason']=='Adaptive target budget' for d in result['deferred'])
    assert base==before
    assert [(s['start'],s['end']) for s in result['track']['segments']]==[(s.start,s.end) for s in base.segments]
    calls.clear()
    again=adaptive_asr.adaptive_retry(runner,folder,base,review,audio,scores,context)
    assert not calls and [s['text'] for s in again['track']['segments']]==[s['text'] for s in result['track']['segments']]
    receipt=next(folder.glob('*/*/0/result.json'));value=read_json(receipt);value['result']['usable']=False;write_json(receipt,value)
    with pytest.raises(ValueError,match='receipt'):adaptive_asr.adaptive_retry(runner,folder,base,review,audio,scores,context)


def test_partial_crop_and_changed_full_audio_are_not_silently_reused(tmp_path,monkeypatch):
    runner,folder,base,review,audio,scores,context,calls=scenario(tmp_path,monkeypatch)
    adaptive_asr.adaptive_retry(runner,folder,base,review,audio,scores,context)
    receipt=next(folder.glob('*/*/0/result.json'));receipt.unlink()
    (receipt.parent/'audio.wav').write_bytes(b'corrupt crop')
    with pytest.raises(ValueError,match='crop'):adaptive_asr.adaptive_retry(runner,folder,base,review,audio,scores,context)
    audio.write_bytes(b'different source')
    with pytest.raises((ValueError,wave.Error,EOFError)):adaptive_asr.adaptive_retry(runner,folder,base,review,audio,scores,context)


def test_alignment_blocks_are_short_and_skip_punctuation_manual_and_extremely_long_cues():
    cues=[Segment(i*3000,i*3000+2500,'日本語です。') for i in range(12)]
    cues[4].status='manual';cues[7].text='。'
    track=Track('base',cues);groups=alignment_groups(track,0,40000)
    used=[i for g in groups for i in g['indices']]
    assert 4 not in used and 7 not in used and sorted(used)==[i for i in range(12) if i not in (4,7)]
    assert all(g['end']-g['start']<=25800 for g in groups)
    assert not alignment_groups(Track('long',[Segment(0,40000,'長い文章')]),0,40000)


@pytest.mark.parametrize('failure',['oom','quality','invalid_json','missing_segments'])
def test_native_alignment_block_failure_is_isolated_but_cuda_oom_is_fatal(tmp_path,failure):
    from studio.audio_alignment import align_final
    from studio.review import ReviewSettings
    source=tmp_path/'input.wav';wav(source,3)
    folder=tmp_path/'alignment';folder.mkdir()
    runner=SimpleNamespace(config={'start':0,'duration':3000,'jp_alignment':{'enabled':True,'split':True}},
        settings=SimpleNamespace(ffmpeg='ffmpeg',crisp_exe='crisp',crisp_aligner='model.gguf',crisp_gpu_backend='cuda'),
        rules=ReviewSettings(),event=lambda *a,**k:None,progress=lambda *a:None)
    def call(args,directory,name,timeout):
        if name=='version':return '[backends: cuda cpu]'
        if name=='help':return '--align-only --aligner-model --file --text-file --align-format --align-granularity --align-output --gpu-backend --cache-dir'
        if name=='crop':wav(directory/'audio.partial.wav',float(args[args.index('-t')+1]));return ''
        if failure in ('oom','quality'):
            log=('CUDA out of memory\n' if failure=='oom' else '')+'alignment failed or produced no words'
            (directory/'engine.log').write_text(log,encoding='utf8')
            # Mimic a truncated runtime exception while preserving the full log.
            raise RuntimeError('alignment failed or produced no words')
        (directory/'aligned.json').write_text('invalid' if failure=='invalid_json' else '[]',encoding='utf8')
        return 'CUDA0'
    runner.call=call;base=Track('base',[Segment(500,2500,'日本語です。')])
    if failure=='oom':
        with pytest.raises(RuntimeError,match='device/memory'):align_final(runner,folder,base,source)
    else:
        result=align_final(runner,folder,base,source)
        assert result['block_failures'] and not result['changes']
        assert [(s['start'],s['end'],s['text']) for s in result['track']['segments']]==[(500,2500,'日本語です。')]

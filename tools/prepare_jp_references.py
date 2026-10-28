"""Small local reference bank. Audio is shared by ASR/review records; no model sees reference text."""
import hashlib
import json
from pathlib import Path
import subprocess

from studio.core import atomic_text, load_srt
from studio.storage import Settings,check_space


def write_review_views(root):
    records=[]
    for filename in ('review_examples.jsonl','review_real_asr_examples.jsonl'):
        file=root/filename
        if file.exists():records.extend(json.loads(line) for line in file.read_text(encoding='utf8').splitlines() if line.strip())
    inputs=[{'id':r['id'],'split':r['split'],'hypothesis_jp':r['hypothesis_jp'],
             'audio':r['audio'],'audio_available_to_text_only_model':False} for r in records]
    labels=[{'id':r['id'],'split':r['split'],'expected_action':r['expected_action'],'reference_jp':r['reference_jp'],
             'kind':r['kind'],'human_audio_verified':False,'training_ready':False} for r in records]
    for filename,items in (('review_inputs.jsonl',inputs),('review_labels.jsonl',labels)):
        atomic_text(root/filename,'\n'.join(json.dumps(r,ensure_ascii=False) for r in items)+'\n')


def main():
    source=Path('D:/models/test-media/mcdc-japanese')
    video=source/'MCDC-Japanese-23m-240p.webm'
    subtitle=source/'reference.ja.srt'
    all_cues=load_srt(subtitle).segments
    cues=[s for s in all_cues if 69380<=s.start and s.end<=181680]
    assert len(cues)==22
    root=Path('D:/models/datasets/subtitle-studio-references-v1');root.mkdir(parents=True,exist_ok=True)
    check_space(root,64*1024**2,2)
    blocks=[cues[:4],cues[4:8],cues[8:12],cues[12:16],cues[16:]]
    current=[]
    for cue in all_cues:
        if cue.start<185000:continue
        if current and (len(current)>=4 or cue.end-current[0].start>30000):
            blocks.append(current);current=[]
            if len(blocks)==30:break
        if cue.end-cue.start<=30000:current.append(cue)
    if len(blocks)<30 and current:blocks.append(current)
    assert len(blocks)==30,'Insufficient disjoint reference ranges'
    groups=[];asr_records=[];review_records=[]
    for i,block in enumerate(blocks):
        start,end=block[0].start,block[-1].end
        name=f'mcdc-{i+1:02d}';audio=root/(name+'.flac')
        if not audio.exists():
            subprocess.run([Settings.load().ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                '-ss',str(start/1000),'-i',str(video),'-map','0:a:0','-t',str((end-start)/1000),
                '-vn','-ar','16000','-ac','1','-c:a','flac',str(audio)],check=True,timeout=120)
        split=('development' if i<2 else 'control') if i<5 else ('control' if i%3==0 else 'development')
        text='\n'.join(c.text for c in block)
        record={'id':name,'split':split,'audio':str(audio),'source_media':str(video),'source_range_ms':[start,end],
            'reference_jp':text,'reference_source':str(subtitle),'reference_cues':len(block),
            'reference_status':'external-community-subtitles; not manually checked against audio',
            'human_audio_verified':False,'audio_sha256':hashlib.sha256(audio.read_bytes()).hexdigest()}
        groups.append(record)
        asr_records.append({'id':name,'split':split,'audio':str(audio),'text':text,'training_ready':False})
        review_records.append({'id':name+'-clean','split':split,'audio':str(audio),'hypothesis_jp':text,
            'expected_action':'keep','reference_jp':text,'kind':'clean-reference-control','human_audio_verified':False})
        # A labelled mechanical corruption tests whether review fixes repetition
        # without teaching any movie-specific names or invented semantic corrections.
        damaged=block[0].text+'\n'+text
        review_records.append({'id':name+'-synthetic-repeat','split':split,'audio':str(audio),
            'hypothesis_jp':damaged,'expected_action':'fix','issue':'repetition',
            'reference_jp':text,'kind':'synthetic-corruption-not-real-asr','human_audio_verified':False})
    index={'version':1,'samples':groups,'evaluation_core':[r['id'] for r in groups[:5]],
        'source_subtitle_sha256':hashlib.sha256(subtitle.read_bytes()).hexdigest(),
        'split_policy':'30 disjoint time ranges, development/control labels, within ONE recording; not speaker/source independent. Five fixed core clips for the initial runtime comparison.',
        'purpose':'Evaluation and label audit; not an automatic training job. Human-audio verification required before trusted training export.',
        'model_input_policy':'Only audio is passed to ASR. Reference Japanese is read afterwards for scoring.'}
    atomic_text(root/'index.json',json.dumps(index,ensure_ascii=False,indent=2))
    for name,records in [('asr_examples.jsonl',asr_records),('review_examples.jsonl',review_records)]:
        atomic_text(root/name,'\n'.join(json.dumps(r,ensure_ascii=False) for r in records)+'\n')
    write_review_views(root)
    print('References:',root,'clips:',len(groups),'review examples:',len(review_records),flush=True)


if __name__=='__main__':main()

"""Compare Japanese ASR hypotheses with an external SRT using exact character edit distance."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from studio.core import atomic_text,load_srt
from studio.pipeline import load_run,track_from
from studio.pipeline_worker import read_json
from studio.evaluation_text import normalize_text,score_text


def compare(manifest,reference_path,output):
    state=load_run(manifest)
    c=state['config'];start=c['start'];end=start+c['duration']
    reference=load_srt(reference_path)
    # Never compare a clipped sentence with a complete reference sentence silently.
    crossing=[s for s in reference.segments if s.start<end and s.end>start and not (s.start>=start and s.end<=end)]
    if crossing: raise ValueError('Evaluation boundaries cross a reference cue; use complete cue boundaries')
    selected=[s for s in reference.segments if start<=s.start and s.end<=end]
    if not selected: raise ValueError('No reference cues in matching audio range')
    text=''.join(s.text for s in selected)
    results=[]
    seen=set()
    for stage in state['stages']:
        if stage['status']!='completed' or not (stage['id'].startswith(('asr-','merge-')) or stage['id']=='layout'): continue
        track=track_from(read_json(stage['artifact'])['track'])
        fingerprint=hashlib.sha256(''.join(s.text for s in track.segments).encode()).hexdigest()
        metrics=score_text(text,''.join(s.text for s in track.segments))
        results.append({'stage':stage['id'],'label':stage['label'],'cues':len(track.segments),
                        'duplicate_text_of_previous_track':fingerprint in seen,**metrics})
        seen.add(fingerprint)
    result={'manifest':str(manifest),'reference':str(reference_path),'range_ms':[start,end],
            'reference_cues':len(selected),'reference_sha256':hashlib.sha256(Path(reference_path).read_bytes()).hexdigest(),
            'normalization':'Unicode NFKC + casefold; strip punctuation, symbols, whitespace and music/applause labels; no Kanji/kana or number-word equivalence',
            'limitation':'Difference from community subtitles, not independently verified audio ground truth. CER is not translation accuracy.',
            'results':results}
    atomic_text(output,json.dumps(result,ensure_ascii=False,indent=2))
    for r in results: print(r['stage'],f'CER={r["cer"]:.2%}',r['edit_distance'],'edits /',r['reference_characters'],'reference characters',flush=True)
    print('Comparison:',output,flush=True)
    return result


def main():
    sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('reference',type=Path);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    compare(args.manifest,args.reference,args.out)


if __name__=='__main__': main()

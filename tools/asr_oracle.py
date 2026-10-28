"""Evaluation-only, reference-guided selection from a fixed hypothesis lattice.

Never import this module into production review. Gold is used to measure the
remaining selection opportunity, not to generate deployable subtitles.
"""
from difflib import SequenceMatcher

from tools.compare_reference import normalize_text, score_text


def _script(char):
    if '\u3040'<=char<='\u309f': return 'hiragana'
    if '\u30a0'<=char<='\u30ff': return 'katakana'
    if '\u3400'<=char<='\u9fff': return 'kanji'
    return 'other'


def _unit(text,start,end):
    if start==end: return start,end
    while start and _script(text[start-1])==_script(text[start])!='other': start-=1
    while end<len(text) and _script(text[end-1])==_script(text[end])!='other': end+=1
    return start,end


def _boundary(opcodes,position):
    values=set()
    for tag,i,j,k,l in opcodes:
        if tag=='equal' and i<=position<=j: values.add(k+position-i)
        elif position==i: values.add(k)
        elif position==j: values.add(l)
    return next(iter(values)) if len(values)==1 else None


def hypothesis_lattice(hypotheses,baseline):
    """Partition using hypotheses only; no reference argument is accepted."""
    if baseline not in hypotheses: raise ValueError('Missing baseline hypothesis')
    normalized={name:normalize_text(text) for name,text in hypotheses.items()}
    text=normalized[baseline]
    if max(map(len,normalized.values()),default=0)>2000: raise ValueError('Use shorter matching evaluation clips')
    alignments={};intervals=set()
    for name,candidate in normalized.items():
        ops=SequenceMatcher(None,text,candidate,autojunk=False).get_opcodes();alignments[name]=ops
        for tag,i,j,_,_ in ops:
            if tag!='equal': intervals.add(_unit(text,i,j))
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]: merged[-1][1]=max(end,merged[-1][1])
        else: merged.append([start,end])
    parts=[];cursor=0
    def fixed(start,end):
        if end>start: parts.append({'start':start,'end':end,'options':[{'source':baseline,'text':text[start:end]}]})
    for start,end in merged:
        fixed(cursor,start)
        options=[{'source':baseline,'text':text[start:end]}]
        seen={text[start:end]}
        for name,candidate in normalized.items():
            a,b=_boundary(alignments[name],start),_boundary(alignments[name],end)
            if a is None or b is None or a>b: continue
            fragment=candidate[a:b]
            if fragment not in seen:
                options.append({'source':name,'text':fragment,'source_start':a,'source_end':b});seen.add(fragment)
        parts.append({'start':start,'end':end,'options':options});cursor=end
    fixed(cursor,len(text))
    return parts


def lattice_oracle(reference,parts):
    """Exact edit-distance DP through complete option strings, with provenance.

    Choosing isolated characters from options is forbidden: every selected edge
    consumes one complete phrase. Backtracking yields one realizable path.
    """
    ref=normalize_text(reference)
    if not ref: raise ValueError('Empty normalized reference')
    if len(ref)>2000: raise ValueError('Use shorter matching evaluation clips')
    states=[(i,()) for i in range(len(ref)+1)]
    for part in parts:
        if not part['options']: raise ValueError('Empty lattice branch')
        best=None
        for index,option in enumerate(part['options']):
            current=states
            for char in option['text']:
                following=[(current[0][0]+1,current[0][1])]
                for i,expected in enumerate(ref,1):
                    choices=[(current[i-1][0]+(expected!=char),current[i-1][1]),
                             (current[i][0]+1,current[i][1]),(following[i-1][0]+1,following[i-1][1])]
                    following.append(min(choices,key=lambda state:state[0]))
                current=following
            extended=[(cost,path+(index,)) for cost,path in current]
            if best is None: best=extended
            else: best=[a if a[0]<=b[0] else b for a,b in zip(best,extended)]
        states=best
    cost,path=states[-1]
    chosen=[{**part['options'][index],'baseline_range':[part['start'],part['end']]} for part,index in zip(parts,path)]
    text=''.join(p['text'] for p in chosen)
    score=score_text(reference,text)
    if score['edit_distance']!=cost: raise AssertionError('Oracle backtracking is not a realizable path')
    return {'hypothesis_jp':text,'score':score,'choices':chosen}


def evaluate_oracle(reference,hypotheses,baseline='large-v3'):
    if not hypotheses: raise ValueError('No usable hypotheses')
    parts=hypothesis_lattice(hypotheses,baseline)
    fused=lattice_oracle(reference,parts)
    whole=min(({'source':name,'hypothesis_jp':text,'score':score_text(reference,text)}
               for name,text in hypotheses.items()),key=lambda row:row['score']['edit_distance'])
    result=fused if fused['score']['edit_distance']<whole['score']['edit_distance'] else {
        **whole,'choices':[{'source':whole['source'],'text':normalize_text(whole['hypothesis_jp'])}]}
    return {**result,'best_whole_hypothesis':whole,'lattice_parts':parts,
            'selection':'phrase-lattice' if result is fused else 'whole-hypothesis',
            'reference_used':True,'deployable':False,
            'scope':'Minimum CER in this reference-free partition lattice plus whole-hypothesis paths; not an unrestricted audio upper bound'}

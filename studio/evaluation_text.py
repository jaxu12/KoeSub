"""Stable character-difference metrics; these do not classify semantic errors."""
import re
import unicodedata

def normalize_text(text):
    text=re.sub(r'<[^>]*>|\{[^}]*\}|\[(?:音楽|拍手|笑い|music|applause)\]','',text,flags=re.I)
    return ''.join(c for c in unicodedata.normalize('NFKC',text).casefold()
                   if unicodedata.category(c)[0] not in {'P','S','Z','C'})


def score_text(reference,hypothesis):
    ref,hyp=normalize_text(reference),normalize_text(hypothesis)
    if not ref: raise ValueError('Empty normalized reference')
    # Exact Levenshtein distance; a byte/cell retains the alignment for examples.
    width=len(hyp)+1
    if len(ref)*len(hyp)>50_000_000: raise ValueError('Use a smaller, matching evaluation range')
    directions=bytearray((len(ref)+1)*width)
    previous=list(range(width))
    for i,a in enumerate(ref,1):
        current=[i]+[0]*len(hyp)
        for j,b in enumerate(hyp,1):
            diag=previous[j-1]+(a!=b)
            deletion=previous[j]+1
            insertion=current[j-1]+1
            best=min(diag,deletion,insertion)
            current[j]=best
            directions[i*width+j]=(0 if a==b else 1) if best==diag else 2 if best==deletion else 3
        previous=current
    i,j=len(ref),len(hyp)
    counts={'substitutions':0,'deletions':0,'insertions':0}
    changes=[]
    while i or j:
        op=directions[i*width+j] if i and j else 2 if i else 3
        if op==0: i-=1;j-=1
        elif op==1:
            counts['substitutions']+=1;changes.append((i-1,j-1,'substitution'));i-=1;j-=1
        elif op==2:
            counts['deletions']+=1;changes.append((i-1,j,'deletion'));i-=1
        else:
            counts['insertions']+=1;changes.append((i,j-1,'insertion'));j-=1
    examples=[]
    for a,b,kind in reversed(changes):
        if examples and abs(a-examples[-1]['reference_position'])<10: continue
        examples.append({'kind':kind,'reference_position':a,'hypothesis_position':b,
                         'reference_context':ref[max(0,a-10):a+15],'hypothesis_context':hyp[max(0,b-10):b+15]})
        if len(examples)>=20: break
    return {**counts,'reference_characters':len(ref),'hypothesis_characters':len(hyp),
            'edit_distance':previous[-1],'cer':previous[-1]/len(ref),'examples':examples}

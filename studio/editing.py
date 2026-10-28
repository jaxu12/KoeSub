"""Previewable editing operations. Never treat technical time repair as audio alignment."""
import copy
import re
from dataclasses import asdict

from .core import merge_segments
from .review import char_count, metrics


def processing_digest(track):
    from .pipeline import digest
    value = asdict(track)
    for segment in value['segments']:
        for key in ('review_status','bookmarked','comment'):
            segment.pop(key,None)
    return digest(value)


def shift_track(track,offset,indices=None):
    result = copy.deepcopy(track)
    indices = set(range(len(result.segments))) if indices is None else set(indices)
    for i in indices:
        if i<0 or i>=len(result.segments):
            raise ValueError('Nieprawidłowy wybór napisów.')
        segment = result.segments[i]
        if segment.start+offset<0 or segment.end+offset<=segment.start+offset:
            raise ValueError('Przesunięcie utworzyłoby ujemny lub nieprawidłowy czas. Nic nie zmieniono.')
        segment.start+=offset
        segment.end+=offset
        segment.review_status='unreviewed'
    return result


def clean_whitespace(text):
    return '\n'.join(line.rstrip() for line in text.replace('\r\n','\n').replace('\r','\n').strip().split('\n'))


def propose_cleanup(track,rules,media_duration=0,whitespace=True,merge_short=False,timing=False):
    result = copy.deepcopy(track)
    changes,unresolved = [],[]
    if whitespace:
        for i,s in enumerate(result.segments):
            jp,en = clean_whitespace(s.text),clean_whitespace(s.translation)
            if (jp,en)!=(s.text,s.translation):
                s.text,s.translation,s.review_status = jp,en,'unreviewed'
                if en:
                    s.status,s.translation_key='manual',''
                changes.append(f'#{i+1}: uporządkowano białe znaki')
    if merge_short:
        merged = []
        i = 0
        while i<len(result.segments):
            a = result.segments[i]
            if i+1<len(result.segments):
                b = result.segments[i+1]
                speaker_marker = any(re.match(r'^\s*(?:[-—–]|[^\s:：]{1,24}[:：])',t) for t in (a.text,b.text,a.translation,b.translation) if t)
                same_en = bool(a.translation.strip())==bool(b.translation.strip())
                small = min(a.end-a.start,b.end-b.start)<min(rules.min_ms,700)
                combined = b.end-a.start
                if (small and not speaker_marker and same_en and a.start<=a.end<=b.start<=b.end and
                        0<=b.start-a.end<=120 and rules.min_ms<=combined<=rules.max_ms and
                        char_count(a.text+b.text)<=rules.jp_line*rules.max_lines and
                        char_count(a.translation+' '+b.translation)<=rules.en_line*rules.max_lines):
                    candidate = merge_segments([a,b])
                    candidate.bookmarked = a.bookmarked or b.bookmarked
                    candidate.comment='\n'.join(t for t in (a.comment,b.comment) if t)
                    merged.append(candidate)
                    changes.append(f'#{i+1} + #{i+2}: scalono krótki sąsiedni napis (bez markerów mówców)')
                    i+=2
                    continue
            merged.append(a)
            i+=1
        result.segments=merged
    if timing:
        ordered = sorted(result.segments,key=lambda s:(s.start,s.end))
        max_previous_end=0
        for i,s in enumerate(ordered):
            next_start = ordered[i+1].start if i+1<len(ordered) else media_duration or s.end
            previous_end = max_previous_end
            desired = s.end
            if s.end<=s.start and s.start>=previous_end:
                needed = max(rules.min_ms,round(max(char_count(s.text)/rules.jp_cps,
                                                   char_count(s.translation)/rules.en_cps)*1000))
                if s.start+needed<=next_start and s.start>=0:
                    desired=s.start+needed
            elif s.end>next_start and s.end-next_start<=150:
                desired=next_start
            elif 0<s.end-s.start<rules.min_ms and rules.min_ms-(s.end-s.start)<=250:
                desired=min(s.start+rules.min_ms,next_start)
            if desired!=s.end and desired>s.start and s.start>=0 and (not media_duration or desired<=media_duration):
                jp,en=metrics(s.text,desired-s.start),metrics(s.translation,desired-s.start)
                if jp['cps']<=rules.jp_cps and en['cps']<=rules.en_cps:
                    old=s.end
                    s.end,s.review_status=desired,'unreviewed'
                    s.notes=list(dict.fromkeys(s.notes+['Korekta techniczna czasu — sprawdź odsłuch']))
                    changes.append(f'{s.id[:8]}: koniec {old} → {desired} ms')
            max_previous_end=max(max_previous_end,s.end)
        result.segments=ordered
    for i,s in enumerate(result.segments):
        if not s.text.strip():
            unresolved.append(f'#{i+1}: pusty JP; tekst pozostawiono')
        if s.start<0 or s.end<=s.start:
            unresolved.append(f'#{i+1}: czas wymaga ręcznej korekty; brak bezpiecznej propozycji')
    return result,changes,unresolved

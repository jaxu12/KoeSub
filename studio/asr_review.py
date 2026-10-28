"""Local comparison of audio-derived hypotheses, before any translation.

Agreement is evidence, never a reference transcript. Keep timing and manual text;
only replace bounded phrases corroborated by a baseline retry and another model.
"""
from dataclasses import asdict
from difflib import SequenceMatcher
import re
import math

from .core import normalize
from .pipeline import clone_track

VERSION = 3


def _surface(cues):
    text = ''; positions = []
    for cue in cues:
        for offset, char in enumerate(cue['text']):
            value = normalize(char)
            text += value
            positions.extend((cue, offset) for _ in value)
    return text, positions


def _script(char):
    if '\u3040' <= char <= '\u309f': return 'hiragana'
    if '\u30a0' <= char <= '\u30ff' or char == 'ー': return 'katakana'
    if '\u3400' <= char <= '\u9fff': return 'kanji'
    return 'other'


def _unit(text, start, end):
    # Do not turn shared characters inside conflicting kanji words into a vote.
    if start == end: return start, end
    while start and _script(text[start-1]) == _script(text[start]) != 'other': start -= 1
    while end < len(text) and _script(text[end-1]) == _script(text[end]) != 'other': end += 1
    return start, end


def _boundary(opcodes, position):
    values = set()
    for tag, i, j, k, l in opcodes:
        if tag == 'equal' and i <= position <= j: values.add(k + position-i)
        elif position == i: values.add(k)
        elif position == j: values.add(l)
    # Insertions at a boundary have two possible interpretations: don't guess.
    return values.pop() if len(values) == 1 else None


def _anchors(opcodes, start, end):
    left = right = False
    for tag, i, j, _, _ in opcodes:
        if tag != 'equal': continue
        left |= min(j, start)-max(i, start-12) >= 2
        right |= min(j, end+12)-max(i, end) >= 2
    return left and right


def _model(path):
    return str(path or '').replace('\\', '/').casefold()


def review_fragments(base, windows, confidence, baseline_model,version=1):
    if version not in (1,2,3): raise ValueError('Unsupported source review version')
    result = clone_track(base, 'Pipeline • review transkrypcji JP')
    targets = {s.parents[0]: s for s in result.segments}
    originals = {s.id: s for s in base.segments}
    records = []; patches = {}
    for window in windows:
        before = window['before']
        if any(s['id'] not in originals or (s['text'],s['start'],s['end']) !=
               (originals[s['id']].text,originals[s['id']].start,originals[s['id']].end) for s in before):
            raise ValueError('Zmieniono tekst lub czasy źródła review JP.')
        text, positions = _surface(before)
        aligned = []; intervals = set()
        for attempt in window['attempts']:
            cues = attempt.get('track', {}).get('segments', [])
            valid = (attempt.get('usable', False) and bool(cues)
                     and all(window['start'] <= c['start'] < c['end'] <= window['end'] for c in cues)
                     and all(a['end'] <= b['start'] for a, b in zip(cues, cues[1:])))
            candidate, mapping = _surface(cues) if valid else ('', [])
            opcodes = SequenceMatcher(None, text, candidate, autojunk=False).get_opcodes()
            if valid:
                for tag, i, j, _, _ in opcodes:
                    if tag != 'equal': intervals.add(_unit(text, i, j))
            aligned.append((attempt, valid, candidate, mapping, opcodes))
        # Conflicting edit boundaries must be considered as one phrase.
        merged = []
        for start, end in sorted(intervals):
            if merged and start < merged[-1][1]: merged[-1][1] = max(end, merged[-1][1])
            else: merged.append([start, end])
        for start, end in merged:
            if not positions: continue
            insertion = start == end
            first, last = positions[min(start,len(positions)-1)], positions[min(max(start,end-1),len(positions)-1)] if end else positions[0]
            structural = insertion or first[0]['id'] != last[0]['id']
            cue = originals.get(first[0]['id'])
            if cue is None: continue
            if window.get('target_id',cue.id) != cue.id: continue
            lo, hi = first[1], last[1]+1
            if insertion: lo = hi = first[1]+(start == len(positions))
            alternatives = []
            for attempt, valid, candidate, mapping, opcodes in aligned:
                a, b = _boundary(opcodes, start), _boundary(opcodes, end)
                available = valid and a is not None and b is not None and a < b
                source_cues = {p[0]['id']: p[0] for p in mapping[a:b]}.values() if available else []
                temporal = bool(source_cues) and all(
                    min(s['end'], cue.end)-max(s['start'], cue.start) >= .3*min(s['end']-s['start'], cue.end-cue.start)
                    for s in source_cues)
                scores = [attempt.get('confidence', {}).get(s['id'], {}).get('mean') for s in source_cues]
                score = min(scores) if scores and all(isinstance(s, (int, float)) for s in scores) else None
                raw = ''
                if available:
                    # Only a contiguous, verbatim fragment from one decoded cue is eligible.
                    p, q = mapping[a], mapping[b-1]
                    if p[0]['id'] == q[0]['id']: raw = p[0]['text'][p[1]:q[1]+1]
                alternatives.append({'model': attempt.get('model', ''), 'name': attempt.get('name', ''),
                    'text': raw, 'normalized': candidate[a:b] if available else '',
                    'cue_ids': [s['id'] for s in source_cues], 'confidence': score,
                    'anchored': available and _anchors(opcodes, start, end), 'temporal': temporal,
                    'directory': attempt.get('directory', ''), 'usable': valid})
            baseline_score = confidence.get(cue.id, {})
            disagreement=version>=2 and any(s['id']==cue.id and 'asr_disagreement' in s.get('signals',[]) for s in window.get('suspects',[]))
            usable = [a for a in alternatives if a['usable']]
            candidate = alternatives[0] if alternatives else {}
            same = (len(usable) >= 2 and len({_model(a['model']) for a in usable if a['model']}) >= 2
                    and _model(candidate.get('model')) == _model(baseline_model) != ''
                    and all(a['normalized'] == candidate.get('normalized') and a['text']
                            and a['anchored'] and a['temporal'] for a in usable))
            # Version 3 permits a third decoder to corroborate the baseline
            # retry despite a dissenting auxiliary. Never elect an auxiliary
            # majority against the baseline retry or relax the phrase guards.
            if version >= 3 and len(alternatives) == 3:
                supporters = [a for a in usable if a['normalized'] == candidate.get('normalized')
                              and a['text'] and a['anchored'] and a['temporal']]
                same = (candidate in supporters and _model(candidate.get('model')) == _model(baseline_model) != ''
                        and len({_model(a['model']) for a in supporters if a['model']}) >= 2)
            reason = 'Rozbieżne lub niepełne hipotezy; zachowano bazę'
            approved = False
            if structural: reason = 'Dodanie tekstu lub zmiana przez granice napisów — wymaga odsłuchu'
            elif cue.status == 'manual' or cue.review_status == 'reviewed': reason = 'Ręcznie sprawdzony tekst — bez zmian'
            elif not same: pass
            elif not (disagreement or baseline_score.get('mean', 1) < .78 or baseline_score.get('low_ratio', 0) >= .2):
                reason = 'Baza bez sygnału niskiej pewności; propozycja do odsłuchu'
            elif candidate.get('confidence') is None or not math.isfinite(candidate['confidence']) or candidate['confidence'] < .8:
                reason = 'Brak wystarczającej pewności ponowienia bazy'
            elif not (2 <= end-start <= 20 and .5 <= len(candidate['normalized'])/(end-start) <= 2):
                reason = 'Zmiana zbyt mała lub rozległa do automatycznej zamiany'
            elif re.search(r'[a-zA-Z0-9]', cue.text[lo:hi]+candidate['text']):
                reason = 'Nazwa lub liczba — wymaga odsłuchu'
            elif candidate['normalized'] == text[start:end]: reason = 'Potwierdzono bazę'
            else:
                approved = True
                reason = 'Zgodna lokalna fraza: ponowienie bazy i inny model; czasy zachowane'
            original = text[start:end] if structural else cue.text[lo:hi]
            record = {'window': window['id'], 'cue_id': cue.id,
                      'start': window['start'] if structural else cue.start, 'end': window['end'] if structural else cue.end,
                      'text_start': lo, 'text_end': hi, 'before': original,
                      'after': candidate.get('text', '') if approved else original,
                      'alternatives': alternatives, 'applied': approved, 'reason': reason,
                      'context': ' '.join(s['text'] for s in before) if structural else cue.text,
                      'baseline_confidence': baseline_score}
            if version >= 3:
                record['supporting_models'] = [a['model'] for a in usable
                    if a['normalized'] == candidate.get('normalized') and a['anchored'] and a['temporal']]
                record['dissenting_models'] = [a['model'] for a in usable
                    if a['normalized'] != candidate.get('normalized')]
            records.append(record)
            if approved: patches.setdefault(cue.id, []).append(record)
    for cue_id, changes in patches.items():
        target = targets[cue_id]
        ordered = sorted(changes, key=lambda r: r['text_start'])
        if any(a['text_end'] > b['text_start'] for a, b in zip(ordered, ordered[1:])):
            for r in changes: r.update(applied=False, after=r['before'], reason='Nakładające się propozycje — zachowano bazę')
            continue
        for r in reversed(ordered): target.text = target.text[:r['text_start']]+r['after']+target.text[r['text_end']:]
        target.translation = ''; target.translation_key = ''; target.review_status = 'unreviewed'
        target.source = 'asr-local-consensus'
        target.notes.append('ASR: lokalna zgodność ponowienia bazy i modelu pomocniczego — sprawdź odsłuch')
    unresolved = {r['cue_id'] for r in records if not r['applied']}
    for cue_id in unresolved:
        if cue_id in targets and originals[cue_id].status != 'manual' and originals[cue_id].review_status != 'reviewed':
            targets[cue_id].notes.append('ASR: nierozstrzygnięte różnice fraz — porównaj hipotezy i odsłuchaj')
    if version >= 3:
        for window in windows:
            if any(not a.get('usable') for a in window['attempts']):
                for suspect in window.get('suspects',[]):
                    cue_id=suspect['id']
                    if cue_id in targets and originals[cue_id].status!='manual' and originals[cue_id].review_status!='reviewed':
                        targets[cue_id].notes.append('ASR: an audio hypothesis failed quality checks; listen to this cue')
    return {'version': version, 'track': asdict(result), 'fragments': records,
            'changes': [r for r in records if r['applied']], 'changed_cues': len({r['cue_id'] for r in records if r['applied']}),
            'scope': 'JP source review before translation; text-only comparison of audio-derived hypotheses; agreement can be wrong'}

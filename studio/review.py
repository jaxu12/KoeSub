"""Deterministic readability checks; suggested times do not imply speech alignment."""
from __future__ import annotations

import math
import re
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass, fields

from .core import Segment, Track, issues_for


@dataclass(frozen=True)
class ReviewSettings:
    en_cps: float = 20
    jp_cps: float = 8
    en_line: int = 42
    jp_line: int = 20
    max_lines: int = 2
    min_ms: int = 834
    max_ms: int = 7000
    gap_ms: int = 80

    @classmethod
    def load(cls, values):
        result = cls(**{f.name: values[f.name] for f in fields(cls) if f.name in values})
        if min(result.en_cps, result.jp_cps, result.en_line, result.jp_line, result.max_lines, result.min_ms) <= 0:
            raise ValueError('Limity review muszą być dodatnie.')
        if result.max_ms < result.min_ms or result.gap_ms < 0:
            raise ValueError('Nieprawidłowe limity czasu review.')
        return result


def plain(text):
    return re.sub(r'<[^>]*>|\{[^}]*\}', '', text).replace('\r\n', '\n').replace('\r', '\n')


def char_count(text):
    # NFC avoids double counting a decomposed accent; spaces count, newlines do not.
    return len(unicodedata.normalize('NFC', plain(text)).replace('\n', ''))


def metrics(text, duration_ms):
    lines = plain(text).splitlines() if text.strip() else []
    count = char_count(text)
    return {'chars': count, 'lines': len(lines),
            'line': max((char_count(line) for line in lines), default=0),
            'cps': count * 1000 / duration_ms if duration_ms > 0 else None}


def split_position(text):
    """Prefer punctuation, then spaces, and permit Japanese character boundaries."""
    if len(text.strip()) < 2:
        return None
    candidates = []
    japanese = bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff]', text))
    first = len(text) - len(text.lstrip())
    last = len(text.rstrip())
    for i in range(max(1, first + 1), min(len(text), last)):
        punctuation = text[i-1] in '。！？!?;；、，,.'
        whitespace = text[i-1].isspace() or text[i].isspace()
        if not (punctuation or whitespace or japanese):
            continue
        # Sentence boundaries win when reasonably close to the middle.
        balance = abs(2 * i - len(text)) / len(text)
        score = balance + (0 if punctuation else .18 if whitespace else .4)
        candidates.append((score, i))
    return min(candidates)[1] if candidates else None


def split_proposal(segment, settings):
    jp = split_position(segment.text)
    en = split_position(segment.translation) if segment.translation else None
    if jp is None or (segment.translation and en is None) or segment.end <= segment.start + 1:
        return None
    left = char_count(segment.text[:jp]) / settings.jp_cps
    right = char_count(segment.text[jp:]) / settings.jp_cps
    if en is not None:
        left = max(left, char_count(segment.translation[:en]) / settings.en_cps)
        right = max(right, char_count(segment.translation[en:]) / settings.en_cps)
    ratio = left / (left + right) if left + right else .5
    at = max(segment.start + 1, min(segment.end - 1, segment.start + round((segment.end - segment.start) * ratio)))
    return jp, en, at


def reflow_english(text, limit):
    """Whitespace-only layout change. Never split a word or drop text."""
    lines = []
    for original in text.splitlines():
        line = ''
        for word in original.split():
            if line and len(line) + 1 + len(word) > limit:
                lines.append(line)
                line = word
            else:
                line = (line + ' ' + word).strip()
        if line:
            lines.append(line)
    return '\n'.join(lines)


def reflow_japanese(text, limit, max_lines=2):
    """Wrap a short JP caption without changing characters or breaking Latin words."""
    flat=text.replace('\r','').replace('\n','')
    if not re.search(r'[\u3040-\u30ff\u3400-\u9fff]',flat) or len(flat)>limit*max_lines:
        return text
    if len(flat)<=limit: return flat
    if max_lines!=2: return text
    candidates=[]
    for at in range(max(1,len(flat)-limit),min(limit,len(flat)-1)+1):
        if flat[at] in '、。，！？!?）」』】' or flat[at-1] in '（「『【': continue
        if flat[at-1].isascii() and flat[at].isascii() and flat[at-1].isalnum() and flat[at].isalnum(): continue
        candidates.append((abs(at-len(flat)/2)+(0 if flat[at-1] in '、。！？!?' else 1),at))
    if not candidates: return text
    at=min(candidates)[1]
    return flat[:at]+'\n'+flat[at:]


def review_track(track: Track | None, settings: ReviewSettings, media_duration=0):
    if not track:
        return []
    chronological = sorted(enumerate(track.segments), key=lambda item: (item[1].start, item[1].end))
    starts = [segment.start for _, segment in chronological]
    rows = {}
    max_end = None
    for n, (index, segment) in enumerate(chronological):
        duration = segment.end - segment.start
        jp, en = metrics(segment.text, duration), metrics(segment.translation, duration)
        warnings = []
        if segment.start < 0 or duration <= 0:
            warnings.append('Nieprawidłowy czas')
        elif duration < settings.min_ms:
            warnings.append(f'Za krótko: {duration / 1000:.2f} s < {settings.min_ms / 1000:.2f} s')
        elif duration > settings.max_ms:
            warnings.append(f'Za długo: {duration / 1000:.2f} s > {settings.max_ms / 1000:.2f} s')
        next_start = chronological[n+1][1].start if n+1 < len(chronological) else None
        if (max_end is not None and max_end > segment.start) or (next_start is not None and segment.end > next_start):
            warnings.append('Nakładanie napisów')
        following = bisect_left(starts, segment.end)
        gap_start = starts[following] if following < len(starts) else None
        if gap_start is not None and 0 < gap_start - segment.end < settings.gap_ms:
            warnings.append(f'Mała przerwa: {gap_start - segment.end} ms')
        if media_duration > 0 and segment.end > media_duration:
            warnings.append('Koniec poza filmem')
        for language, m, cps, width in [('JP', jp, settings.jp_cps, settings.jp_line),
                                       ('EN', en, settings.en_cps, settings.en_line)]:
            if m['cps'] is not None and m['cps'] > cps:
                warnings.append(f'{language}: za szybko — {m["cps"]:.1f} > {cps:g} znaków/s')
            if m['line'] > width:
                warnings.append(f'{language}: długi wiersz — {m["line"]} > {width} znaków')
            if m['lines'] > settings.max_lines:
                warnings.append(f'{language}: {m["lines"]} wiersze > {settings.max_lines}')
        # Keep content diagnostics, replacing the old fixed timing/line thresholds.
        warnings += [issue for issue in issues_for(segment) if not issue.startswith(
            ('Nieprawidłowy czas', 'Krótki czas', 'Długi czas', 'Długa linia'))]
        needed = math.ceil(max(jp['chars'] / settings.jp_cps, en['chars'] / settings.en_cps) * 1000)
        proposal = split_proposal(segment, settings)
        advice = []
        if needed > duration:
            advice.append(f'Potrzeba około {needed / 1000:.2f} s przy tych limitach. '
                          'Skróć tekst lub sprawdź czasy po odsłuchu; sam podział nie obniża tempa czytania.')
        if en['line'] > settings.en_line:
            advice.append('Rozważ łamanie wierszy EN bez zmiany czasu.')
        if proposal:
            if duration >= 2 * settings.min_ms:
                advice.append('Można rozważyć dwa napisy. Punkt i zgodność JP/EN sprawdź w podglądzie oraz odsłuchu.')
            else:
                advice.append('Za mało czasu na dwie części o zalecanej minimalnej długości.')
        else:
            advice.append('Brak bezpiecznej propozycji podziału tekstu; popraw go ręcznie.')
        rows[index] = {'index': index, 'id': segment.id, 'duration': duration, 'jp': jp, 'en': en,
                       'issues': list(dict.fromkeys(warnings)), 'advice': ' '.join(advice),
                       'needed': needed, 'proposal': proposal}
        max_end = max(segment.end, max_end) if max_end is not None else segment.end
    return [rows[i] for i in range(len(track.segments))]

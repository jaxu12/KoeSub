from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import pysubs2


def uid() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Segment:
    start: int
    end: int
    text: str
    id: str = field(default_factory=uid)
    translation: str = ""
    source: str = "manual"
    parents: list[str] = field(default_factory=list)
    translation_key: str = ""
    status: str = "unchecked"
    notes: list[str] = field(default_factory=list)
    review_status: str = 'unreviewed'
    bookmarked: bool = False
    comment: str = ''


@dataclass
class Track:
    name: str
    segments: list[Segment] = field(default_factory=list)
    id: str = field(default_factory=uid)
    origin: dict = field(default_factory=dict)


@dataclass
class Project:
    name: str = "Nowy projekt"
    media: str = ""
    tracks: list[Track] = field(default_factory=list)
    active_track: str = ""
    audio_track: int = 0
    duration: int = 0
    jobs: list[dict] = field(default_factory=list)
    originals: dict = field(default_factory=dict)
    review_settings: dict = field(default_factory=dict)
    pipeline_prefs: dict = field(default_factory=dict)
    ai_reviews: dict = field(default_factory=dict)
    version: int = 1

    @property
    def active(self) -> Track | None:
        return next((t for t in self.tracks if t.id == self.active_track), None)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Project:
        data = copy.deepcopy(data)
        if data.get("version", 1) != 1:
            raise ValueError("Projekt pochodzi z nieobsługiwanej wersji aplikacji.")
        data["tracks"] = [Track(**{**t, "segments": [Segment(**s) for s in t["segments"]]})
                          for t in data.get("tracks", [])]
        return cls(**data)

    def add_track(self, track: Track) -> None:
        self.tracks.append(track)
        self.active_track = track.id
        self.originals[track.id] = asdict(track)


def time_text(ms: int) -> str:
    sign = "-" if ms < 0 else ""
    seconds, millis = divmod(abs(ms), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{sign}{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def parse_time(value: str) -> int:
    match = re.fullmatch(r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError("Czas musi mieć format 00:00:00,000.")
    h, m, s, ms = map(int, match.groups())
    if m >= 60 or s >= 60:
        raise ValueError("Minuty i sekundy muszą być mniejsze niż 60.")
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def load_srt(path: Path, encoding: str = "utf-8-sig") -> Track:
    text = path.read_text(encoding=encoding)
    # pysubs2 is intentionally permissive; detect blocks it would silently skip.
    blocks = [b for b in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()) if b.strip()]
    timing = re.compile(r"^\d{1,3}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,3}:\d{2}:\d{2}[,.]\d{3}(?:\s+.*)?$")
    for n, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if not any(timing.fullmatch(line.strip()) for line in lines[:2]):
            raise ValueError(f"Nieprawidłowy blok SRT nr {n}. Sprawdź znaczniki czasu.")
    subs = pysubs2.SSAFile.from_string(text, format_="srt")
    if len(subs) != len(blocks):
        raise ValueError("Nie wszystkie bloki SRT zostały odczytane. Import przerwany.")
    return Track(path.stem, [Segment(s.start, s.end, s.plaintext, source=str(path)) for s in subs],
                 origin={"file": str(path.resolve()), "encoding": encoding, "imported": now()})


def load_subtitles(path: Path, encoding='utf-8-sig') -> Track:
    if path.suffix.lower()=='.srt':
        return load_srt(path,encoding)
    if path.suffix.lower() not in {'.ass','.ssa'}:
        raise ValueError('Obsługiwany import: SRT, ASS i SSA.')
    subs = pysubs2.SSAFile.from_string(path.read_text(encoding=encoding),format_=path.suffix[1:].lower())
    events = [s for s in subs if not s.is_comment]
    if not events:
        raise ValueError('Plik nie zawiera napisów dialogowych.')
    return Track(path.stem,[Segment(s.start,s.end,s.plaintext,source=str(path)) for s in events],
                 origin={'file':str(path.resolve()),'encoding':encoding,'imported':now(),
                         'format':path.suffix[1:].lower(),'style_import':'plaintext_only'})


def _windows_file_conflict(exc: PermissionError) -> bool:
    # Python's buffered file IO can report EACCES without a winerror, unlike
    # os.replace. Both forms occur while Windows replaces a checkpoint.
    code = getattr(exc, 'winerror', None)
    return os.name == 'nt' and (code in {5, 32, 33} or
                                (code is None and exc.errno in {errno.EACCES, errno.EPERM}))


def read_json_file(path: Path):
    # Windows may briefly deny opening the destination while another process
    # replaces it atomically. Retry opening, but never hide invalid JSON or a
    # permanent permissions failure and never return an older in-memory state.
    for attempt in range(8):
        try:
            text = Path(path).read_text(encoding='utf8')
            break
        except PermissionError as exc:
            if not _windows_file_conflict(exc) or attempt==7:
                raise
            time.sleep(min(.01*2**attempt,.16))
    return json.loads(text)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".studio-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers/antivirus can briefly deny FILE_SHARE_DELETE. Keep the old
        # file intact and retry the atomic replace, never fall back to truncation.
        for attempt in range(8):
            try:
                os.replace(name, path)
                break
            except PermissionError as exc:
                if not _windows_file_conflict(exc) or attempt==7:
                    raise
                time.sleep(min(.01*2**attempt,.16))
    finally:
        Path(name).unlink(missing_ok=True)


def export_srt(track: Track, path: Path, english: bool = False) -> None:
    export_subtitles(track,path,english,format_='srt')


def export_subtitles(track: Track, path: Path, english=False, format_=None) -> None:
    if not track.segments:
        raise ValueError("Ścieżka nie zawiera napisów.")
    if any(s.start < 0 or s.end <= s.start for s in track.segments):
        raise ValueError("Przed eksportem popraw zerowe, odwrócone lub ujemne czasy.")
    if english and any(not s.translation.strip() for s in track.segments):
        raise ValueError("Brakuje tłumaczeń. Uzupełnij je przed eksportem EN.")
    format_ = format_ or path.suffix[1:].lower()
    if format_ not in {'srt','ass','ssa','txt'}:
        raise ValueError('Obsługiwany eksport: SRT, ASS, SSA i TXT.')
    if format_=='txt':
        atomic_text(path,'\n\n'.join(f'{time_text(s.start)} → {time_text(s.end)}\n'+
                                    (s.translation if english else s.text) for s in track.segments)+'\n')
        return
    subs = pysubs2.SSAFile()
    for s in track.segments:
        event = pysubs2.SSAEvent(start=s.start, end=s.end)
        event.plaintext = s.translation if english else s.text
        subs.append(event)
    atomic_text(path, subs.to_string(format_))


class ProjectStore:
    def __init__(self, path: Path):
        self.path = path

    def save(self, project: Project, reason: str = "autosave") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(project.to_dict(), ensure_ascii=False)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE IF NOT EXISTS project (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, created TEXT, reason TEXT, payload TEXT)")
            old = db.execute("SELECT payload FROM project WHERE id=1").fetchone()
            if old and old[0] == payload:
                return
            # Machine checkpoints update the current state only. A full history snapshot per
            # translated cue would grow quadratically for long films and waste disk space.
            if reason not in {"autosave", "translation checkpoint"}:
                db.execute("INSERT INTO history(created,reason,payload) VALUES(?,?,?)", (now(), reason, payload))
            db.execute("INSERT INTO project VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (payload,))

    def load(self) -> Project:
        if not self.path.is_file():
            raise ValueError("Nie znaleziono projektu.")
        with sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True) as db:
            row = db.execute("SELECT payload FROM project WHERE id=1").fetchone()
        if not row:
            raise ValueError("Plik nie zawiera projektu KoeSub.")
        return Project.from_dict(json.loads(row[0]))


def invalidate(segment: Segment) -> None:
    segment.translation_key = ""
    segment.status = "stale" if segment.translation else "unchecked"
    segment.review_status = 'unreviewed'


def merge_segments(segments: list[Segment]) -> Segment:
    if len(segments) < 2:
        raise ValueError("Wybierz co najmniej dwa sąsiednie napisy.")
    has_translation = all(s.translation.strip() for s in segments)
    if any(s.translation.strip() for s in segments) and not has_translation:
        raise ValueError('Scalenie utraciłoby częściowy EN. Najpierw uzupełnij brakujące tłumaczenia.')
    return Segment(min(s.start for s in segments), max(s.end for s in segments),
                   "\n".join(s.text for s in segments), source="merge",
                   parents=[s.id for s in segments],
                   translation="\n".join(s.translation for s in segments) if has_translation else "",
                   notes=list(dict.fromkeys(note for s in segments for note in s.notes)),
                   bookmarked=any(s.bookmarked for s in segments),
                   comment='\n'.join(dict.fromkeys(s.comment for s in segments if s.comment)),
                   status="stale" if has_translation else "unchecked")


def split_segment(s: Segment, position: int, at_ms: int,
                  translation_position: int | None = None) -> tuple[Segment, Segment]:
    if not 0 < position < len(s.text) or not s.start < at_ms < s.end:
        raise ValueError("Ustaw kursor wewnątrz tekstu i odtwarzacz wewnątrz czasu napisu.")
    a, b = s.text[:position].strip(), s.text[position:].strip()
    if not a or not b:
        raise ValueError("Obie części muszą zawierać tekst.")
    en_a, en_b = '', ''
    if s.translation:
        if translation_position is None or not 0 < translation_position < len(s.translation):
            raise ValueError('Wskaż również punkt podziału EN, aby zachować tłumaczenie.')
        en_a, en_b = s.translation[:translation_position].strip(), s.translation[translation_position:].strip()
        if not en_a or not en_b:
            raise ValueError('Obie części EN muszą zawierać tekst.')
    return (Segment(s.start, at_ms, a, translation=en_a, source="split", parents=[s.id],
                    notes=list(s.notes),
                    bookmarked=s.bookmarked,comment=s.comment,
                    status='stale' if en_a else 'unchecked'),
            Segment(at_ms, s.end, b, translation=en_b, source="split", parents=[s.id],
                    notes=list(s.notes),
                    bookmarked=s.bookmarked,comment=s.comment,
                    status='stale' if en_b else 'unchecked'))


def issues_for(s: Segment, previous: Segment | None = None) -> list[str]:
    issues = list(s.notes)
    if s.start < 0 or s.end <= s.start:
        issues.append("Nieprawidłowy czas")
    elif s.end - s.start < 400:
        issues.append("Krótki czas (<400 ms)")
    elif s.end - s.start > 10000:
        issues.append("Długi czas (>10 s)")
    if previous and previous.end > s.start:
        issues.append("Nakładanie napisów")
    if not s.text.strip():
        issues.append("Pusty tekst")
    if re.search(r"(.{1,8}?)\1{3,}", s.text.replace(" ", "")):
        issues.append("Powtórzenia — sprawdź odsłuch")
    if re.fullmatch(r"[.\s…?!？！]+", s.text):
        issues.append("Sama interpunkcja")
    if s.translation:
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", s.translation):
            issues.append("Japońskie znaki w EN")
        if re.search(r"\b(i (cannot|can't|won't)|i am unable|as an ai|i'm sorry)\b", s.translation, re.I):
            issues.append("Możliwa odmowa tłumaczenia")
        if re.search(r"<think>|</think>", s.translation, re.I):
            issues.append("Tekst rozumowania w EN")
        if len(s.translation) > max(100, len(s.text) * 6):
            issues.append("Nietypowa długość EN — sprawdź treść")
        if any(len(line) > 50 for line in s.translation.splitlines()):
            issues.append("Długa linia EN")
    if s.status == "stale":
        issues.append("EN wymaga ponownej kontroli")
    return issues


def translation_key(segment: Segment, context: list[Segment], model: str, prompt: str) -> str:
    payload = [segment.id, segment.text, [(s.id, s.text) for s in context], model, prompt]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).casefold()


def compare_tracks(a: Track, b: Track, tolerance: int = 150) -> list[dict]:
    """Time overlap components support 1:N and N:1; text similarity is diagnostic only."""
    left = sorted(a.segments, key=lambda s: (s.start, s.end))
    right = sorted(b.segments, key=lambda s: (s.start, s.end))
    parent = list(range(len(left) + len(right)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    matched_left, matched_right = set(), set()
    j = 0
    for i, x in enumerate(left):
        if x.end <= x.start:
            continue
        while j < len(right) and right[j].end <= x.start - tolerance:
            j += 1
        k = j
        while k < len(right) and right[k].start < x.end + tolerance:
            y = right[k]
            overlap = min(x.end, y.end) - max(x.start, y.start)
            shorter = min(x.end-x.start, y.end-y.start)
            # Small boundary jitter must not connect every adjacent cue into one group.
            if shorter > 0 and overlap > 0 and overlap / shorter >= 0.2:
                parent[root(i)] = root(len(left) + k)
                matched_left.add(i)
                matched_right.add(k)
            k += 1
    # Only unmatched short cues use a small timestamp tolerance, with mutual nearest pairing.
    unmatched_right = {k for k in range(len(right)) if k not in matched_right and right[k].end > right[k].start}
    for i, x in enumerate(left):
        if i in matched_left or x.end <= x.start or not unmatched_right:
            continue
        k = min(unmatched_right, key=lambda k: abs(x.start-right[k].start) + abs(x.end-right[k].end))
        y = right[k]
        if abs(x.start-y.start) <= tolerance and abs(x.end-y.end) <= tolerance:
            parent[root(i)] = root(len(left)+k)
            unmatched_right.remove(k)
    groups: dict[int, dict] = {}
    for side, values, offset in (("a", left, 0), ("b", right, len(left))):
        for i, s in enumerate(values):
            groups.setdefault(root(offset+i), {"a": [], "b": []})[side].append(s)
    result = []
    for g in groups.values():
        all_s = g["a"] + g["b"]
        ta = " ".join(s.text for s in g["a"])
        tb = " ".join(s.text for s in g["b"])
        score = SequenceMatcher(None, normalize(ta), normalize(tb)).ratio() if g["a"] and g["b"] else 0
        g.update(start=min(s.start for s in all_s), end=max(s.end for s in all_s), similarity=score,
                 kind="Brak odpowiednika" if not g["a"] or not g["b"] else
                 "Zgodne" if normalize(ta) == normalize(tb) else "Różna treść / podział")
        result.append(g)
    return sorted(result, key=lambda g: g["start"])

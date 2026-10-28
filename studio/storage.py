from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .core import atomic_text

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


@dataclass
class Settings:
    subtitle_edit: str = ""
    model_roots: list[str] = field(default_factory=list)
    cache_dir: str = str(DATA / "cache")
    ffmpeg: str = ""
    whisper_exe: str = ""
    crisp_exe: str = ""
    crisp_gpu_backend: str = "vulkan"
    crisp_aligner: str = ""
    crisp_vad: str = ""
    translation_backend: str = "embedded"
    llm_exe: str = ""
    llm_model: str = ""
    llm_device: str = "vulkan"
    llm_context: int = 4096
    llm_batch_size: int = 6
    lm_url: str = "http://127.0.0.1:1234"
    reserve_gib: float = 2.0

    @classmethod
    def load(cls):
        file = DATA / "settings.json"
        if file.exists():
            return cls(**json.loads(file.read_text("utf-8")))
        settings = cls()
        candidates = [Path.home() / "Desktop" / "SubtitleEdit-Windows-x64",
                      Path.home() / "Downloads" / "SubtitleEdit-Windows-x64",
                      Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Subtitle Edit",
                      Path(os.environ.get("APPDATA", str(Path.home()))) / "Subtitle Edit"]
        for path in candidates:
            if (path / "SpeechToText").is_dir() or (path / "SubtitleEdit.exe").is_file():
                settings.set_subtitle_edit(path)
                break
        lm_models = Path.home() / ".lmstudio" / "models"
        if lm_models.is_dir():
            settings.model_roots.append(str(lm_models))
        return settings

    def set_subtitle_edit(self, path: Path):
        self.subtitle_edit = str(path.resolve())
        for target, candidate in (
            ("ffmpeg", path / "ffmpeg" / "ffmpeg.exe"),
            ("whisper_exe", path / "SpeechToText" / "Purfview-Faster-Whisper-XXL" / "faster-whisper-xxl.exe"),
            ("crisp_exe", path / "CrispASR" / "crispasr.exe"),
        ):
            if candidate.is_file():
                setattr(self, target, str(candidate.resolve()))
        if str(path.resolve()) not in self.model_roots:
            self.model_roots.insert(0, str(path.resolve()))

    def save(self):
        atomic_text(DATA / "settings.json", json.dumps(asdict(self), ensure_ascii=False, indent=2))


@dataclass
class Model:
    name: str
    path: str
    kind: str
    size: int


def discover_models(roots: list[str], max_depth: int = 7) -> list[Model]:
    """Inspect only configured folders. Never follow links, copy, move or download."""
    found, seen = [], set()
    for base in roots:
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        stack = [(base_path, 0)]
        while stack:
            folder, depth = stack.pop()
            try:
                items = list(folder.iterdir())
            except OSError:
                continue
            model_bin = folder / "model.bin"
            if model_bin.is_file() and (folder / "config.json").is_file():
                key = os.path.normcase(str(folder.resolve()))
                if key not in seen:
                    seen.add(key)
                    size = sum(p.stat().st_size for p in items if p.is_file())
                    found.append(Model(folder.name, str(folder.resolve()), "Whisper / CTranslate2", size))
                continue
            for item in items:
                try:
                    if item.is_symlink() or item.is_junction():
                        continue
                    if item.is_dir() and depth < max_depth and item.name not in {".git", "node_modules", ".venv"}:
                        stack.append((item, depth + 1))
                    elif item.is_file() and item.suffix.lower() == ".gguf":
                        key = os.path.normcase(str(item.resolve()))
                        if key in seen:
                            continue
                        seen.add(key)
                        name = item.name.lower()
                        kind = ("ReazonSpeech / GGUF" if "reazonspeech" in name else "Qwen ASR" if "asr" in name else "Aligner" if "aligner" in name else
                                "Audio / inny" if any(t in name for t in ("roformer", "diarization")) else "LLM / GGUF")
                        found.append(Model(item.name, str(item.resolve()), kind, item.stat().st_size))
                    elif item.is_file() and item.suffix.lower() == ".bin" and item.name.startswith("ggml-") and "silero" not in item.name.lower():
                        key = os.path.normcase(str(item.resolve()))
                        if key not in seen:
                            seen.add(key)
                            found.append(Model(item.name, str(item.resolve()), "Whisper / GGML", item.stat().st_size))
                except OSError:
                    continue
    return sorted(found, key=lambda m: (m.kind, m.name))


def existing_parent(path: Path) -> Path:
    path = path.resolve()
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def check_space(path: Path, needed: int, reserve_gib: float = 2.0) -> int:
    free = shutil.disk_usage(existing_parent(path)).free
    required = needed + int(reserve_gib * 1024**3)
    if free < required:
        raise ValueError(f"Za mało miejsca na {path}: wolne {free/1024**3:.2f} GiB; "
                         f"potrzeba {required/1024**3:.2f} GiB łącznie z rezerwą. Wybierz inny folder cache.")
    return free


def audio_cache_path(settings: Settings, media: Path, track: int, start: int = 0, duration: int = 0) -> Path:
    stat = media.stat()
    key = f"{media.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{track}|{start}|{duration}|pcm16-16k-v1"
    name = hashlib.sha256(key.encode()).hexdigest()[:24]
    return Path(settings.cache_dir) / f"audio-{name}.wav"


def offline_env() -> dict[str, str]:
    return {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "PYTHONUTF8": "1"}


def audio_metadata(log: str) -> tuple[int, list[str]]:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", log)
    duration = 0
    if match:
        h, m, s, fraction = match.groups()
        duration = ((int(h)*60+int(m))*60+int(s))*1000 + int(fraction[:3].ljust(3, "0"))
    tracks = [line.strip() for line in log.splitlines() if re.search(r"Stream #\d+:\d+.*Audio:", line)]
    return duration, tracks

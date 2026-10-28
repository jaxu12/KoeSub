from __future__ import annotations

import re
from pathlib import Path

from .storage import Model, Settings


def crisp_backends(build_text: str) -> tuple[str, ...]:
    match = re.search(r'ggml backends\s*:\s*([^\r\n]+)|\[backends:\s*([^\]]+)\]', build_text, re.I)
    if not match:
        raise ValueError('Nie można ustalić backendów silnika CrispASR. Sprawdź wynik --version.')
    values = re.split(r'[,\s]+', (match.group(1) or match.group(2)).lower().strip())
    return tuple(value for value in ('cuda', 'vulkan', 'cpu') if value in values)


def validate_crisp_backend(backend: str, build_text: str) -> None:
    available = crisp_backends(build_text)
    if backend not in available:
        raise ValueError(f'Ten silnik ASR nie obsługuje {backend.upper()}. '
                         f'Dostępne backendy: {", ".join(available)}. Wybierz zgodny backend w ustawieniach ASR.')


def validate_flags(help_text: str, args: list[str]) -> None:
    supported = set(re.findall(r"(?<!\w)--[a-zA-Z][\w-]*", help_text))
    supported.update(re.findall(r"(?<![\w-])-[a-zA-Z][\w-]*", help_text))
    missing = [arg for arg in args if arg.startswith("-") and arg not in supported]
    if missing:
        raise ValueError("Zainstalowany silnik nie obsługuje parametrów: " + ", ".join(missing))


def whisper_command(settings: Settings, model: Model, audio: Path, output: Path,
                    compute: str, device: str, vad: bool, help_text: str) -> list[str]:
    folder = Path(model.path).resolve()
    if not (folder / "model.bin").is_file() or not (folder / "config.json").is_file():
        raise ValueError("Nie znaleziono kompletnego lokalnego modelu CTranslate2. Pobieranie jest wyłączone.")
    if not folder.name.startswith("faster-whisper-"):
        raise ValueError("To wydanie XXL wymaga folderu o nazwie faster-whisper-NAZWA. "
                         "Wybierz model z folderu _models Subtitle Edit. Aplikacja nie zmienia ani nie kopiuje modeli.")
    model_name = folder.name.removeprefix("faster-whisper-")
    args = [str(audio.resolve()), "--model", model_name, "--model_dir", str(folder.parent),
            "--output_dir", str(output.resolve()), "--language", "ja", "--task", "transcribe",
            "--device", device, "--compute_type", compute, "--beam_size", "5", "--best_of", "5",
            "--temperature", "0", "--condition_on_previous_text", "False", "--initial_prompt", "None",
            "--vad_filter", str(vad), "--word_timestamps", "True", "--standard_asia", "--beep_off",
            "--output_format", "srt", "json"]
    validate_flags(help_text, args)
    return args


def crisp_command(settings: Settings, model: Model, audio: Path, output: Path,
                  vad: bool, help_text: str) -> list[str]:
    if not Path(model.path).is_file():
        raise ValueError("Nie znaleziono lokalnego modelu Qwen3-ASR.")
    args = ["--backend", "qwen3", "--model", str(Path(model.path).resolve()),
            "--file", str(audio.resolve()), "--language", "ja", "--max-len", "50", "--split-on-punct",
            "--suppress-nst", "--frequency-penalty", "0.2", "--gpu-backend", settings.crisp_gpu_backend,
            "--cache-dir", str((Path(settings.cache_dir) / "crispasr").resolve()),
            "--output-srt", "--output-json", "--output-file", str((output / "transcript").resolve())]
    root = Path(settings.crisp_exe).parent
    if settings.crisp_gpu_backend not in {"cuda", "vulkan", "cpu"}:
        raise ValueError("Nieobsługiwany backend GPU CrispASR.")
    aligners = [Path(settings.crisp_aligner)] if settings.crisp_aligner else list((root / "models").glob("qwen3-forced-aligner*.gguf"))
    if aligners:
        if not aligners[0].is_file():
            raise ValueError("Nie znaleziono wskazanego lokalnego alignera. Sprawdź ustawienia folderów.")
        args += ["--aligner-model", str(aligners[0].resolve())]
    if vad:
        files = [Path(settings.crisp_vad)] if settings.crisp_vad else list(root.glob("*silero*.bin"))
        if not files or not files[0].is_file():
            raise ValueError("Brak lokalnego modelu VAD. Wyłącz VAD lub dodaj model w folderze CrispASR.")
        args += ["--vad", "--vad-model", str(files[0].resolve())]
    # A broken auxiliary stage must not silently produce plausible-looking timestamps.
    if "--strict-pipeline" in help_text:
        args += ["--strict-pipeline"]
    validate_flags(help_text, args)
    return args


def whisper_cpp_command(settings: Settings, model: Model, audio: Path, output: Path,
                        vad: bool, help_text: str) -> list[str]:
    path = Path(model.path).resolve()
    if not path.is_file() or model.kind != "Whisper / GGML":
        raise ValueError("Wybierz lokalny model Whisper GGML (.bin).")
    if settings.crisp_gpu_backend not in {"cuda", "vulkan", "cpu"}:
        raise ValueError("Nieobsługiwany backend Whisper.cpp.")
    args = ["--backend", "whisper", "--model", str(path), "--file", str(audio.resolve()),
            "--language", "ja", "--beam-size", "5", "--max-len", "32", "--split-on-punct",
            "--gpu-backend", settings.crisp_gpu_backend, "--output-srt", "--output-json-full",
            "--cache-dir", str((Path(settings.cache_dir)/"crispasr").resolve()),
            "--output-file", str((output/"transcript").resolve())]
    if vad:
        vad_path = Path(settings.crisp_vad)
        if not settings.crisp_vad or not vad_path.is_file():
            raise ValueError("Wskaż lokalny model VAD w ustawieniach.")
        args += ["--vad", "--vad-model", str(vad_path.resolve())]
    if any(tag in path.name.lower() for tag in ('kotoba','anime-whisper')):
        aligner=Path(settings.crisp_aligner)
        if not settings.crisp_aligner or not aligner.is_file():
            raise ValueError('Kotoba/Anime-Whisper wymaga lokalnego alignera do czasów napisów. Wskaż go w ustawieniach ASR.')
        args += ['--aligner-model',str(aligner.resolve()),'--force-aligner']
    if "--strict-pipeline" in help_text:
        args += ["--strict-pipeline"]
    validate_flags(help_text,args)
    return args


def reazonspeech_command(settings,model,audio,output,vad,help_text):
    if not Path(model.path).is_file():raise ValueError('Brak lokalnego modelu ReazonSpeech.')
    args=['--backend','reazonspeech','--model',str(Path(model.path).resolve()),'--file',str(audio.resolve()),
          '--language','ja','--gpu-backend',settings.crisp_gpu_backend,'--max-len','50','--split-on-punct',
          '--cache-dir',str((Path(settings.cache_dir)/'crispasr').resolve()),'--output-srt','--output-json-full',
          '--output-file',str((output/'transcript').resolve())]
    if vad:
        if not Path(settings.crisp_vad).is_file():raise ValueError('Brak lokalnego VAD.')
        args+=['--vad','--vad-model',str(Path(settings.crisp_vad).resolve())]
    if '--strict-pipeline' in help_text:args+=['--strict-pipeline']
    validate_flags(help_text,args)
    return args

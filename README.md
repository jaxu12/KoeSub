# KoeSub

**Local transcription. Better subtitles.**

KoeSub is an open-source Windows desktop app for turning Japanese speech into editable, reviewable subtitles. We are building it step by step, with an emphasis on comparing ASR hypotheses, combining corroborated phrases, and reviewing the original transcript **before translation**.

The current priority is Japanese transcription. English translation is optional. Japanese transcription can run without an LLM; optional scene-context review uses a local model to flag concerns and recommend existing ASR alternatives. This is a working prototype, and difficult recordings still need human review.

## Features

- Video playback, waveform navigation, cue playback, editing, undo/redo, and SQLite projects.
- Local Whisper Large V3 inference through whisper.cpp/CrispASR, VAD, and an explicit GPU backend.
- A one-click Japanese pipeline: **audio → baseline ASR → optional auxiliary scan → grouped retries → third ASR for unresolved windows → phrase review → optional JP scene review → adaptive contexts → final audio alignment → layout → subtitles and report**.
- Bounded third-model work, normally Qwen3-ASR JA Anime/Galgame. A third decoder can corroborate a baseline retry; two auxiliaries cannot outvote it. Timing, phrase boundaries, confidence and manual-edit guards still apply.
- Several retry clips can share one native process per model. Models run sequentially; per-clip logs, confidence, native output and resume receipts are retained.
- Japanese context review checks nearby dialogue for suspicious words, names and continuity, with exact ASR-choice recommendations. It does not translate or automatically rewrite dialogue.
- Local comparison of ASR phrases with surrounding text and timestamps. Corroborated retries can correct a phrase while disputed text remains available for listening and comparison.
- Optional short/wide audio contexts with different VAD boundaries, bounded target budgets and corroboration across two model weights.
- Final-text forced alignment, non-overlapping timing selection and word-boundary splitting of long cues, with reading-exposure and manual-edit protection. Original timings remain available.
- Protection for manually edited or reviewed cues, with source provenance and before/after records.
- Explicit human phrase selection with saved provenance and undo. New disagreement targets cannot displace earlier low-confidence windows.
- Timing, overlap, reading-speed, and line-length checks; SRT, ASS, SSA, and TXT support. Imported ASS/SSA styling is not preserved.
- Optional local GGUF translation through llama.cpp; LM Studio is a secondary backend.
- Logs, resumable stages, cancellation, and validation of completed artifacts.
- An offline **Source quality** workbench: reference listening, baseline/after-review comparison, explicit omission/addition/name/meaning labels, paired coverage and JSON/Markdown reports. Unassessed content errors are not counted as zero.

Model agreement is evidence, not proof of what was said. Review compares text produced from audio; it can miss errors shared by several models. Model support also depends on conversion quality and timestamp alignment.

## Getting started

Tested environment: **Windows and Python 3.12 x64**. The interface uses PySide6. External runtimes and model weights are installed separately.

```powershell
git clone https://github.com/jaxu12/KoeSub.git
cd KoeSub
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
.\.venv\Scripts\python.exe -m studio
```

Alternatively, run **Install.bat**, followed by **Run.bat**. The installer installs Python dependencies; **it does not download model weights**. Legacy launcher filenames remain available for existing local setups.

In the app settings:

1. Select FFmpeg, an ASR runtime, and existing local model files.
2. Choose a backend supported by that runtime. Current hardware tests use CUDA.
3. Put models and cache on a drive with sufficient free space, for example `D:\models` and `D:\models\.cache`.
4. Import a recording and select the Japanese transcription preset with Large V3 and targeted retries. Start with a short interval.

The demo opens small synthetic subtitles from `samples/` without requiring models. Some interface labels are currently Polish; English UI localization remains planned. All repository documentation is maintained in English.

See [MODEL_SETUP.md](MODEL_SETUP.md) for runtime and model configuration. Paths in development reports describe the test machine and should be adapted to your computer.

## Models, media, and disk use

This repository contains source code, documentation, tests, and synthetic subtitle examples. It does not include model weights, native runtimes, recordings, caches, local settings, or private project databases.

KoeSub reads existing model files without copying their weights. The separate `tools/fetch_*.py` utilities perform explicit downloads; the GUI does not invoke them automatically. Jobs check free space, but cache storage does not yet have an automatic total-size limit.

Dependencies, models, and media retain their own licenses. See [THIRD_PARTY.md](THIRD_PARTY.md).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The current suite contains **272 passing tests**, also verified on a clean source-only copy without developer data or models. It covers editing, persistence, manual-change protection, ASR comparison, third-model routing, grouped output ownership and failure isolation, context-choice validation, evaluation-only oracle selection, stage ordering, exports, and resume behavior. Unit tests do not require model weights or a GPU. Hardware verification scripts in `tools/` require separately prepared runtimes, models, and media.

The latest frozen 17-case CUDA check found no text improvement on ten new read-speech clips or four paired noise variants, and a small reference-distance regression in an additional meeting interval. It also exposed no-speech completion and whitespace round-trip issues. See the report for coverage and limits; successful execution alone is not transcription-quality evidence.

Recorded experiments and their limitations:

- [Adaptive audio, final alignment, exposure safeguards and CUDA verification](ADAPTIVE_AUDIO_AND_ALIGNMENT.md)
- [Frozen 17-case production benchmark, regressions and next priorities](CURRENT_PIPELINE_BENCHMARK.md)

- [Source-quality measurement and audio reference audit workflow](SOURCE_QUALITY_EVALUATION.md)

- [Third ASR, Japanese context review, grouped CUDA inference, and reference checks](SOURCE_REVIEW_V3.md)
- [Auxiliary scan, editable review, additional clips, and full-movie regression checks](ASR_SCAN_REVIEW_V2.md)
- [Ten-clip ASR/fusion benchmark and reference-guided selection opportunity](ASR_FUSION_BENCHMARK.md)
- [Japanese phrase review and transcript fusion](JP_SOURCE_REVIEW.md)
- [Japanese-only transcription, retries, and reference data](JP_TRANSCRIPTION_AND_REFERENCES.md)
- [Kotoba and full-pipeline improvements](KOTOBA_AND_FIXES.md)
- [Earlier full-recording benchmark](BENCHMARK_REPORT.md)

Reports include historical measurements and local artifact identifiers. Those artifacts are not distributed with the source. A successful pipeline run is not a claim of publication-ready subtitle accuracy.

## Roadmap

Our next priorities are better source-transcript selection, evaluation against independently checked references, and reducing the cost of repeated ASR model loading. Translation quality and subtitle-wide consistency will follow. Voice separation, audio-based resynchronization, batch processing, English UI localization, and a packaged Windows executable remain future work.

Contributions, bug reports, and reproducible recording tests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), [STATUS.md](STATUS.md), and the [development notes](DEVELOPMENT_NOTES.md).

## License

KoeSub's original code and documentation are licensed under the **[MIT License](LICENSE)**. External dependencies, runtimes, model weights, and recordings keep their own licenses. KoeSub is not an official product of Subtitle Edit or the model authors.

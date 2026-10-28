# KoeSub status — 2026-10-28

KoeSub is a working Windows/PySide6 prototype. The current focus is Japanese source transcription, with translation optional. Public repository documentation is maintained in English.

## Current behavior

- Whisper Large V3 + VAD is the default Japanese baseline.
- Suspicious intervals can be decoded again with Large V3 and an auxiliary model, normally Kotoba.
- Phrase review runs before translation. Corroborated local edits preserve baseline timestamps; unresolved differences remain visible for listening.
- The editor supports playback, waveforms, persistent projects, manual comparison, annotations, undo/redo, and multiple export formats.
- Optional translation and semantic review use local GGUF models, with an embedded runtime preferred and LM Studio secondary.
- Full LLM pipelines can keep one owned model session loaded across requests. Heavy model work is sequential, and cancellation closes owned child processes.
- Completed stages have integrity checks and can be resumed. Private data, model weights, recordings, and caches are excluded from Git.

## Verification

The current suite has **173 passing tests**, including a clean source snapshot without developer data or models. Hardware experiments use separately prepared assets; they are not part of the unit-test suite.

The latest ten-clip CUDA benchmark compared five models, production review, and evaluation-only reference-guided selection across the existing MCDC core and five newly acquired FLEURS read-speech recordings. Baseline and production both had 31/645 character edits (4.81% CER); constrained oracle selection reached 21/645 (3.26%). Production applied no phrase changes. This identifies missed targeting/selection opportunities, not a measured improvement in the shipping review. See [ASR_FUSION_BENCHMARK.md](ASR_FUSION_BENCHMARK.md).

An earlier targeted Japanese review replay used existing CUDA outputs for a 282.73-second recording and made two edits in one of 98 cues without retiming. It is a targeted example, not a held-out accuracy score; a difficult part of the same sentence remained wrong. See [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md).

Earlier experiments showed that a faster auxiliary ASR can be less accurate than the baseline, invalid alignment must be rejected even after process exit code zero, and repeated reviews by one small LLM do not guarantee correct meaning. Results are in [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md), [EASY_JAPANESE_TEST.md](EASY_JAPANESE_TEST.md), and [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md).

## Open work

Improve transcript selection using independently checked references, reduce ASR reload costs, and evaluate additional recordings and speakers. Translation quality, speaker perspective, terminology, audio-based retiming, voice separation, batch processing, English UI localization, and a packaged Windows executable remain areas for further work. Automatic cache-size limits and an in-app GPU/RAM telemetry panel are not implemented.

The project previously used the working title AI Subtitle Studio. The Python package and existing local receipt names remain compatible with earlier installations.

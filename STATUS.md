# KoeSub status — 2026-10-28

KoeSub is a working Windows/PySide6 prototype. The current focus is Japanese source transcription, with translation optional. Public repository documentation is maintained in English.

## Current behavior

- Whisper Large V3 + VAD is the default Japanese baseline.
- Suspicious intervals can be decoded again with Large V3 and an auxiliary model, normally Kotoba.
- Source review v3 groups retry clips by model and can send only unresolved windows to a third decoder, normally Qwen3-ASR JA Anime/Galgame, with a separate clip limit.
- Optional Japanese scene-context review flags words, names and continuity concerns and recommends existing ASR alternatives. These recommendations require listening and do not automatically rewrite dialogue.
- Phrase review runs before translation. Corroborated local edits preserve baseline timestamps; unresolved differences remain visible for listening.
- The editor supports playback, waveforms, persistent projects, manual comparison, annotations, undo/redo, and multiple export formats.
- Optional translation and semantic review use local GGUF models, with an embedded runtime preferred and LM Studio secondary.
- Full LLM pipelines can keep one owned model session loaded across requests. Heavy model work is sequential, and cancellation closes owned child processes.
- Completed stages have integrity checks and can be resumed. Private data, model weights, recordings, and caches are excluded from Git.

- An offline Source quality workbench separates character differences from user-attested omission/addition/name/meaning events, with audio reference checks and paired assessment coverage. Production tracks remain unchanged.

## Verification

Source review v2 adds a full auxiliary disagreement scan, protects earlier retry priority, reuses complete scan cues where appropriate, and supports saved human phrase choices with undo. Ten additional clips moved from 67/664 to 65/664 reference edits, primarily from spelling; semantic improvement was not demonstrated. The movie regression fix preserves the two earlier edits. Extra coverage costs more processing time. See [ASR_SCAN_REVIEW_V2.md](ASR_SCAN_REVIEW_V2.md).

The current suite has **231 passing tests**, also verified on a clean source-only copy without developer data or models. Hardware experiments use separately prepared assets; they are not part of the unit-test suite. Source review v3 behavior, fresh CUDA timing comparisons, and reference checks are documented in [SOURCE_REVIEW_V3.md](SOURCE_REVIEW_V3.md).

An earlier ten-clip CUDA benchmark compared five models, production review, and evaluation-only reference-guided selection across the existing MCDC core and five newly acquired FLEURS read-speech recordings. Baseline and production both had 31/645 character edits (4.81% CER); constrained oracle selection reached 21/645 (3.26%). Production applied no phrase changes. This identifies missed targeting/selection opportunities, not a measured improvement in the shipping review. See [ASR_FUSION_BENCHMARK.md](ASR_FUSION_BENCHMARK.md).

An earlier targeted Japanese review replay used existing CUDA outputs for a 282.73-second recording and made two edits in one of 98 cues without retiming. It is a targeted example, not a held-out accuracy score; a difficult part of the same sentence remained wrong. See [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md).

Earlier experiments showed that a faster auxiliary ASR can be less accurate than the baseline, invalid alignment must be rejected even after process exit code zero, and repeated reviews by one small LLM do not guarantee correct meaning. Results are in [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md), [EASY_JAPANESE_TEST.md](EASY_JAPANESE_TEST.md), and [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md).

The new quality study reuses five completed FLEURS clips (6/257 text differences, 2.33% CER for both variants). Its references and semantic events are still awaiting human listening; unassessed categories are not zero errors. See [SOURCE_QUALITY_EVALUATION.md](SOURCE_QUALITY_EVALUATION.md).

## Open work

Improve transcript selection using independently checked references and evaluate additional recordings and speakers. Grouped retry inference reduces reload costs; full-recording ASR and auxiliary scans still use separate native runs. Translation quality, speaker perspective, terminology, audio-based retiming, voice separation, multi-file project queues, English UI localization, and a packaged Windows executable remain areas for further work. Automatic cache-size limits and an in-app GPU/RAM telemetry panel are not implemented.

The project previously used the working title AI Subtitle Studio. The Python package and existing local receipt names remain compatible with earlier installations.

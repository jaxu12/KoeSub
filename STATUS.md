# KoeSub status — 2026-11-03

KoeSub is a working Windows/PySide6 prototype. The current focus is Japanese source transcription, with translation optional. Public repository documentation is maintained in English.

## Current behavior

- Japanese GGML jobs enable omission recovery by default, preserving explicit saved off settings. Short scans nominate additional phrases, focused audio decoders corroborate text without requiring aligned auxiliary captions, and a separate aligner supplies gap timing. Global selection avoids overlapping additions while retaining unresolved alternatives and original cues. See [OMISSION_RECOVERY_V2.md](OMISSION_RECOVERY_V2.md).

- New Japanese pipelines run automatic timing review after raw ASR. Supported short boundary defects are merged with explicit reading exposure; other cases use bounded native retries. Raw text, manual edits, hypotheses and repair provenance are retained.

- Whisper Large V3 + VAD is the default Japanese baseline.
- An alternate native Subtitle Edit XXL/MDX preset reuses installed CTranslate2 weights, CUDA float16 and local Kim2. It supports Japanese-only export without CrispASR-specific retries or an LLM, with separate stereo caches and asset resume validation.
- Suspicious intervals can be decoded again with Large V3 and an auxiliary model, normally Kotoba.
- Source review v3 groups retry clips by model and can send only unresolved windows to a third decoder, normally Qwen3-ASR JA Anime/Galgame, with a separate clip limit.
- Optional Japanese scene-context review flags words, names and continuity concerns and recommends existing ASR alternatives. These recommendations require listening and do not automatically rewrite dialogue.
- Phrase review runs before translation. Corroborated local edits preserve baseline timestamps; unresolved differences remain visible for listening.
- The editor supports playback, waveforms, persistent projects, manual comparison, annotations, undo/redo, and multiple export formats.
- Optional translation and semantic review use local GGUF models, with an embedded runtime preferred and LM Studio secondary.
- Full LLM pipelines can keep one owned model session loaded across requests. Heavy model work is sequential, and cancellation closes owned child processes.
- Completed stages have integrity checks and can be resumed. Private data, model weights, recordings, and caches are excluded from Git.

- An offline Source quality workbench separates character differences from user-attested omission/addition/name/meaning events, with audio reference checks and paired assessment coverage. Production tracks remain unchanged.

- Optional adaptive audio probes short/wide contexts and two VAD profiles for unresolved targets. Final-text alignment works in bounded blocks, protects reading exposure and manual cues, and can split long cues at measured word boundaries.

## Verification

Omission recovery v2 now inserts audio-corroborated phrases in measured baseline gaps. Fresh coverage adds five phrases in a 70-second movie interval and two in a separate three-minute interval; the original captions remain unchanged and exports have no invalid times or overlaps. Six additions match nearby unverified reference text exactly; one remains unassessed. No complete-film run or independent accuracy claim is made. Published-transcript/no-speech controls and cached selection replay are documented in [OMISSION_RECOVERY_V2.md](OMISSION_RECOVERY_V2.md).

Source review v2 adds a full auxiliary disagreement scan, protects earlier retry priority, reuses complete scan cues where appropriate, and supports saved human phrase choices with undo. Ten additional clips moved from 67/664 to 65/664 reference edits, primarily from spelling; semantic improvement was not demonstrated. The movie regression fix preserves the two earlier edits. Extra coverage costs more processing time. See [ASR_SCAN_REVIEW_V2.md](ASR_SCAN_REVIEW_V2.md).

The current suite has **369 passing tests**, also verified on a clean source-only copy without developer data or models. Hardware experiments use separately prepared assets; they are not part of the unit-test suite. Source review v3 behavior, fresh CUDA timing comparisons, and reference checks are documented in [SOURCE_REVIEW_V3.md](SOURCE_REVIEW_V3.md).

An earlier ten-clip CUDA benchmark compared five models, production review, and evaluation-only reference-guided selection across the existing MCDC core and five newly acquired FLEURS read-speech recordings. Baseline and production both had 31/645 character edits (4.81% CER); constrained oracle selection reached 21/645 (3.26%). Production applied no phrase changes. This identifies missed targeting/selection opportunities, not a measured improvement in the shipping review. See [ASR_FUSION_BENCHMARK.md](ASR_FUSION_BENCHMARK.md).

An earlier targeted Japanese review replay used existing CUDA outputs for a 282.73-second recording and made two edits in one of 98 cues without retiming. It is a targeted example, not a held-out accuracy score; a difficult part of the same sentence remained wrong. See [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md).

Earlier experiments showed that a faster auxiliary ASR can be less accurate than the baseline, invalid alignment must be rejected even after process exit code zero, and repeated reviews by one small LLM do not guarantee correct meaning. Results are in [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md), [EASY_JAPANESE_TEST.md](EASY_JAPANESE_TEST.md), and [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md).

The new quality study reuses five completed FLEURS clips (6/257 text differences, 2.33% CER for both variants). Its references and semantic events are still awaiting human listening; unassessed categories are not zero errors. See [SOURCE_QUALITY_EVALUATION.md](SOURCE_QUALITY_EVALUATION.md).

A fresh 282.73-second CUDA movie run took 347.953 seconds, accepted timing changes for 20 cues and reduced reading-speed violations from 16 to 15. Adaptive audio made no additional text changes; five reused reference clips remain at 6/257 character differences. See [ADAPTIVE_AUDIO_AND_ALIGNMENT.md](ADAPTIVE_AUDIO_AND_ALIGNMENT.md).

## Open work

A fresh complete eleven-stage Japanese run reaches audited SRT export on the full 122.29-minute film in 1,675.062 seconds. It includes baseline ASR, timing recovery, auxiliary scan, grouped retries/third ASR, phrase/context review, adaptive audio and alignment. The final 647 captions have no invalid durations or overlaps. Kotoba full-scan alignment is rejected, 115 captions are retimed, and one adaptive text change reduces reference distance from 5,006 to 5,005 edits (79.37% final disagreement with the unverified Subtitle Edit sidecar). The result completes with warnings; improved independent accuracy is not demonstrated. Minimum available RAM is 281 MiB. See [FULL_JP_LOOP.md](FULL_JP_LOOP.md).

The full-film timing failure now has an audited recovery: 837 raw captions become 833 with no invalid durations or overlaps, retaining every source character. Two suffix and two prefix merges use existing boundaries; one interval uses explicitly flagged display timing. The saved long ASR and both local retry receipts are reused, with zero new inference processes and 4.531 seconds of new work. Unsupported automatic timing and exhausted audio budgets now continue to export with warnings when legal display space exists; protected barriers and operational failures remain guarded. The original failed experiment is retained. See [AUTOMATIC_TIMING_REVIEW.md](AUTOMATIC_TIMING_REVIEW.md#recovered-full-film-result).

A fresh full 122.29-minute native CUDA/MDX run completed raw ASR in 52 minutes 28.84 seconds, but automatic timing review blocked export. It repaired two of five zero-duration captions, then rejected two content-changing local retries at the next defect; two later defects were not reached. The raw transcript has 57.66% normalized character disagreement with an existing, unverified Subtitle Edit sidecar. Neither transcript is independent gold. Available RAM briefly fell to 4 MiB at preprocessing handoff. Priorities are bounded preprocessing, additional evidence-backed timing recovery and independent listening of major disagreements. The original failed run and source files remain intact. See [FULL_FILM_COMPARISON.md](FULL_FILM_COMPARISON.md).

The 30-minute native XXL/MDX trial completed inference in about fourteen minutes but failed timing validation: one of 183 raw captions has zero duration, blocking final export. CUDA and memory remained operational. A diagnostic project preserves both native and historical hypotheses. The original run remains a failed experiment. A separate replay of its saved hypothesis now passes automatic timing review and final export: 183 captions become 182 with identical source characters and no remaining invalid times. The original ASR is not rerun. See [AUTOMATIC_TIMING_REVIEW.md](AUTOMATIC_TIMING_REVIEW.md). See [LONG_WHISPER_TEST.md](LONG_WHISPER_TEST.md).

The native XXL/MDX profile passed twelve bounded comparison calls with valid times and a separate audited 45-second production ASR/export check. One development reference favored plain XXL over MDX. No full-length or private-excerpt accuracy result is claimed. See [SUBTITLE_EDIT_WHISPER.md](SUBTITLE_EDIT_WHISPER.md).

The latest frozen 17-case CUDA check retained 3.55% CER on ten new read-speech clips and 3.68% on four paired noise variants, while an additional meeting interval regressed from 39 to 40 reference edits. Adaptive work took 557.900 seconds without a text correction. Fifteen speech exports completed, with one whitespace-only round-trip issue; both no-speech controls failed at missing-SRT handling. Priorities are normal no-speech completion, an explicit whitespace contract, verification of accepted phrase edits and lower-cost routing. Production behavior remains unchanged by the benchmark. See [CURRENT_PIPELINE_BENCHMARK.md](CURRENT_PIPELINE_BENCHMARK.md).

Improve transcript selection using independently checked references and evaluate additional recordings and speakers. Grouped retry inference reduces reload costs; full-recording ASR and auxiliary scans still use separate native runs. Translation quality, speaker perspective, terminology, alignment coverage/accuracy, standalone imported-track alignment, voice separation, multi-file project queues, English UI localization, and a packaged Windows executable remain areas for further work. Automatic cache-size limits and an in-app GPU/RAM telemetry panel are not implemented.

The project previously used the working title AI Subtitle Studio. The Python package and existing local receipt names remain compatible with earlier installations.

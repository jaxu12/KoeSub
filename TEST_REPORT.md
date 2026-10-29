# KoeSub test report

## Current source-only verification

As of 2026-10-29, **272 tests pass on a clean source-only copy**, without developer data, models or recordings, using the installed development dependencies (verified separately from GPU inference). The test temporary directory is `.pytest-tmp`, which is ignored by Git. A former `data/test-tmp` setting failed on a fresh checkout with no `data` directory and was corrected.

The suite covers editing/undo, persistence, provenance, format round trips, time/readability checks, strict model-response validation, manual translation protection, source phrase comparison, stage ordering before EN, pause/resume, run locks, timeouts, owned child processes, caches, and Qt behavior. Unit tests do not require model weights or a GPU.

The evaluation suite additionally checks exact complete-phrase oracle paths against exhaustive enumeration, exclusion of reference labels from inference inputs, weighted CER and incomplete coverage, immutability of frozen production results, original baseline timing costs, usable retry candidates, and fatal operational failures after resume. The real ten-clip CUDA benchmark and its unchanged production result are documented in [ASR_FUSION_BENCHMARK.md](ASR_FUSION_BENCHMARK.md).

The source-review v2 suite also covers high-confidence disagreements, retention of baseline-risk budget, real-time scan reuse, auxiliary failure handling, original-track and stale-choice protection, saved human decisions, undo, and restoration of reused native costs. Results and limits are in [ASR_SCAN_REVIEW_V2.md](ASR_SCAN_REVIEW_V2.md).

Source review v3 adds third-decoder corroboration without auxiliary-majority override, unresolved-only routing, manual protection, grouped native output ownership, alignment-warning isolation and fail-closed attribution, fatal device failures, immutable retry receipt replay, quality failure exports, exact context-choice validation, context-only findings without transcript rewriting, scene-gap boundaries, and persistence of disabled third-model selection. See [SOURCE_REVIEW_V3.md](SOURCE_REVIEW_V3.md) for separate hardware and reference results.

The source-quality evaluation suite covers unverified references, missing output denominators, paired versus unmatched listening coverage, clean versus unassessed cases, orthography versus semantic events, exact quote validation, stale evidence, corrected reference history, changed audio, concurrent saves, protected exports, default hypothesis masking and preservation of the active subtitle project. Real-data checks reuse cached ASR and test playback only; they do not certify reference accuracy. See [SOURCE_QUALITY_EVALUATION.md](SOURCE_QUALITY_EVALUATION.md).

Adaptive-audio and alignment coverage includes quiet-boundary planning, distinct-context/model requirements, VAD profile limits, audio/crop hashes and receipt replay, bounded alignment blocks, punctuation/manual protection, zero-duration coalescing without interpolation, exact text preservation, global overlap avoidance, reading exposure, audio-based splitting, LLM release and fatal device errors. Hardware and cached-reference results are separated in [ADAPTIVE_AUDIO_AND_ALIGNMENT.md](ADAPTIVE_AUDIO_AND_ALIGNMENT.md).

Eleven benchmark tests cover deterministic noise/SNR/clipping, label exclusion from production inputs, ASR-buffer versus owned-PID GPU proof, unique full-cue timing matches, whitespace-only round trips, weighted CER and missing coverage, no-speech diagnostics and frozen-collection integrity. The full suite passed in 15.75 seconds and a clean copy in 18.15 seconds. Separately, the frozen 17-case CUDA check exposed a one-edit meeting regression, unchanged short-clip CER, two failed no-speech outcomes and one whitespace-only export mismatch. See [CURRENT_PIPELINE_BENCHMARK.md](CURRENT_PIPELINE_BENCHMARK.md); those findings are not counted as passing quality tests.

## Historical integration checks

An earlier phase had 94 passing tests in 6.70 seconds. Its real 20-second Japanese pipeline ran Whisper Large V3 and Qwen ASR on Vulkan, selected JP, generated two local Qwen3-4B EN profiles, selected EN, reviewed/repaired/verified, and exported. All 12 stages completed, preserving ten tracks and five final cues, with approximately 127 seconds summed stage time. Four cues still required review.

That experiment exposed a transient Windows `PermissionError` reading a checkpoint after computation had completed. Shared bounded JSON-read retries were added for codes 5/32/33. Eight regression cases grew the suite from 86 to 94. Invalid JSON still fails immediately and permanent denial still fails after bounded retries. Later errno-only access-denial handling is described in [EASY_JAPANESE_TEST.md](EASY_JAPANESE_TEST.md).

Additional checks included:

| Utility | Scope |
|---|---|
| `tools.verify_pipeline --audit MANIFEST` | Completed artifact digests, JP/EN text and time round trips, time bounds, and report consistency; no model calls |
| `tools.verify_qol` | FFmpeg waveform, structured local-model proposals, existing EN protection, ASS import, and TXT export |
| `tools.verify_gui_embedded` | GUI → local model → SQLite, followed by real cancellation and child-process cleanup |
| `tools.smoke_ui` | Existing H.264/AAC video playback, audio-track probing, playhead, subtitles, and isolated project save |
| `tools.preview_qol` | Rendered editor/review dialogs and 960×700 layout; images inspected |
| `python -m compileall -q studio tools` | Source compilation |

Local artifacts for that phase are in `D:\models\.cache\verification-pipeline-ui`, `verification-qol`, and `verification-gui-embedded`; successful run ID `ff5df83401a44940b34c7e17cdabf8d6`. They are not included in the repository.

## Interpretation

A successful export verifies pipeline behavior, not subtitle accuracy. Warning categories overlap and are not counts of confirmed errors. Historical short tests did not measure whole-film WER/CER or translation quality against an audited reference. Later full-recording experiments are documented in [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md), [EASY_JAPANESE_TEST.md](EASY_JAPANESE_TEST.md), and [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md).

Run GPU experiments sequentially with prepared local assets. Audit existing artifacts when inference does not need to be repeated.

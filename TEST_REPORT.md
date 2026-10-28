# KoeSub test report

## Current source-only verification

As of 2026-10-28, **191 tests pass on a clean Git snapshot** without local data, models, or recordings, using the installed development dependencies. The test temporary directory is `.pytest-tmp`, which is ignored by Git. A former `data/test-tmp` setting failed on a fresh checkout with no `data` directory and was corrected.

The suite covers editing/undo, persistence, provenance, format round trips, time/readability checks, strict model-response validation, manual translation protection, source phrase comparison, stage ordering before EN, pause/resume, run locks, timeouts, owned child processes, caches, and Qt behavior. Unit tests do not require model weights or a GPU.

The evaluation suite additionally checks exact complete-phrase oracle paths against exhaustive enumeration, exclusion of reference labels from inference inputs, weighted CER and incomplete coverage, immutability of frozen production results, original baseline timing costs, usable retry candidates, and fatal operational failures after resume. The real ten-clip CUDA benchmark and its unchanged production result are documented in [ASR_FUSION_BENCHMARK.md](ASR_FUSION_BENCHMARK.md).

The source-review v2 suite also covers high-confidence disagreements, retention of baseline-risk budget, real-time scan reuse, auxiliary failure handling, original-track and stale-choice protection, saved human decisions, undo, and restoration of reused native costs. Results and limits are in [ASR_SCAN_REVIEW_V2.md](ASR_SCAN_REVIEW_V2.md).

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

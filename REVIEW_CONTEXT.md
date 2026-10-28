# Review, corrections, and whole-transcript context — 2026-10-28

This report describes an earlier translation-focused phase. Japanese-only source review is now the default priority; see [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md).

## Behavior

Review scope and permission to apply corrections are separate settings. New balanced and deep translation jobs can generate an EN correction, compare it with the previous text, and review it again. Check-only mode leaves EN unchanged; quick technical rules do not perform AI repairs. Older resumable manifests retain their original plans.

The standalone AI panel can apply suggestions confirmed by a separate JP-to-EN faithfulness check when no listening decision is required. Manual EN is protected. Before/after records, counts, undo/redo, and persistent proposals remain available. Automatic application does not mark a cue as manually reviewed.

## Whole-transcript context

The optional context step uses all available JP. If only part of a recording was transcribed, its scope is only that part.

1. The model describes the topic, events, roles, facts, and recurring terms. Short texts fit in one compact input. Longer ones use stored chunk summaries and hierarchical aggregation.
2. Context is passed as data, not an instruction overriding the source. Changes invalidate dependent translation cache entries.
3. Chronological JP/EN consistency review carries terms and open questions across batches and flags changes in meaning, perspective, names, or sequence.
4. Context and continuity notes are shown in the UI and retained in artifacts. Proposals using distant context are invalidated if that context changes.

This is analysis of ASR text, not video understanding, speaker recognition, or listening. Summaries can be wrong and do not authorize invented dialogue. One small LLM is not an independent quality guarantee. Later source-only repair verification is described in [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md).

## Historical CUDA checks

- Controlled EN errors were corrected from `My name is Suzuki.` to `My name is Tanaka.` and from `Today is Friday.` to `Today is Monday.`, according to JP. Manual EN was retained; GUI, SQLite, and undo/redo were checked. Approximately 31 seconds.
- A real 20-second balanced pipeline ran both ASRs on CUDA, two EN profiles, context, continuity, review, repair, verification, and export. Five final cues, four changed EN cues, four warning-bearing cues; approximately 138 seconds. This preceded the final summary algorithm.
- Whole-transcript analysis reused 55 Job Interview cues without ASR/translation. A single repeatedly updated summary initially lost earlier facts and was replaced by compact whole-text or chunk-and-aggregate analysis. The improved summary recognized an interview-preparation guide. Ten consistency batches flagged 33 cues; these were model judgments, not 33 confirmed errors. Approximately 54 seconds.
- The suite at this phase had 107 passing tests.

Local artifacts are under `D:\models\.cache\verification-review-changes`; the short pipeline ID is `59dd586797564b9fb3cd5f87d4f34392`. They are not distributed.

```powershell
.\.venv\Scripts\python.exe -m tools.verify_review_changes --whole
.\.venv\Scripts\python.exe -m tools.verify_pipeline --balanced --cuda --data-dir D:\models\.cache\verification-context-review
```

These hardware utilities require separately prepared assets. Historical overlap problems are described in [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md); later timing-compatible selection is described in [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md).

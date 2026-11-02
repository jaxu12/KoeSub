# Automatic ASR timing review — 2026-11-02

New Japanese source-only runs include **Automatic timing review** immediately after raw ASR. A supported timing defect is retained for repair instead of making the entire expensive ASR result unavailable before review. Raw hypotheses and the original native files remain available.

The native XXL preset now runs audio preparation, raw ASR, automatic timing review, Japanese layout and export. The GGML source-only workflow runs this review before auxiliary scans and source phrase review. Existing manifests without the new option retain their original plans.

## Repair policy

### Short suffix at a shared boundary

A zero-duration suffix of at most four characters can merge with the preceding valid caption when its timestamp exactly equals that caption's end. Both captions must be unprotected/untranslated. Speaker markers, oversized output, excessive duration and incompatible neighbouring timing are rejected.

The merged caption keeps every source character and the preceding start time. If necessary, at most **250 ms of explicitly recorded display hold** can satisfy reading exposure. The hold respects neighbouring gaps and the selected interval, creates no new reading-speed violation and cannot worsen an existing excessive reading rate. The original source end is recorded separately. This is display/exposure repair, not a claim that speech continued through the hold.

These inexpensive structural repairs do not consume the budget for additional model calls. They are marked in the resulting cue, its parents and a before/after decision record.

### Local audio fallback

When a boundary repair is unsupported, review tries local audio with six-second and then twelve-second padding. Windows expand to complete context captions, cannot exceed **30 seconds**, and cannot cross manual/reviewed/translated content. The default budget is eight audio targets; each has at most two distinct contexts. MDX retries retain the configured stereo preparation when enabled.

A candidate must have positive in-range non-overlapping native times and exactly match the complete normalized source wording for that window. Original characters and punctuation are reconstructed without interpolating times; a character cannot be divided across Unicode casefold expansion. Only supported measured subtitle boundaries are applied. Content-changing or incomplete candidates do not become automatic timing repairs.

The review stores audio identities, source windows, raw alternatives, native commands/logs and immutable receipts. An interrupted retry cannot inherit an old uncommitted SRT. Changed source audio, review checkpoints, retry receipts or crops invalidate reuse. Device/memory failures remain fatal rather than being mistaken for low-confidence ASR.

### Continue with explicit display recovery

A short zero-duration prefix can also merge with the following unprotected caption at its exact start boundary. This keeps that caption's existing interval, including any pre-existing overlong-duration warning, and cannot worsen its reading-rate limit. Speaker markers, protected work and excessive combined text prevent this structural merge.

When neither structural repair nor an exact-wording audio retry succeeds, timing review now continues with **estimated display timing**. It first allocates reading exposure inside the free interval bounded by neighbouring captions and the selected recording interval. Normal gaps are preferred where space allows. If there is no legal standalone interval, adjacent unprotected captions can be coalesced until a positive non-overlapping display interval exists. Original text and order are retained; tight space or a large merged caption can still produce readability warnings.

This is a display fallback, **not measured speech alignment**. The resulting cue retains its original bounds in before/after provenance, carries an explicit estimated-timing note, and receives a visible review warning. The result reaches export with `needs_review` status instead of failing on an unsupported automatic ASR timing defect. The UI and exported report count unverified display repairs separately. An explicit human `reviewed` decision clears the estimated-timing warning while keeping the history.

Exhausting the expensive audio budget also uses this fallback. Content-changing retry wording is never copied into the transcript. Manual/reviewed/translated cues remain protected; a defect with no legal space between protected barriers remains an explicit error. Device, memory, file-integrity and other operational errors are still propagated. `display_fallback: false` in the timing-review configuration retains strict failure behavior. New GUI jobs enable the fallback; existing failed review checkpoints can continue using their validated source and retry receipts. Completed historical stages are not recomputed.

## Recovered real long-run result

The [original thirty-minute test](LONG_WHISPER_TEST.md) remains a recorded failure. Its native SRT had 183 captions and one zero-duration suffix at **25:28.960**. The recovery experiment reused that frozen output and cached audio; it did not rerun the thirty-minute transcription.

| Check | Recovery result |
|---|---:|
| Input raw captions | 183 |
| Final captions | **182** |
| Source characters retained | **All**, ignoring layout-only line breaks |
| Structural repairs | 1 |
| Local retry/model calls for this case | **0** |
| Original source boundary | 25:28.960 |
| Final merged display end | 25:29.070 |
| Added reading exposure | **110 ms** |
| New-work wall time, including audits/replay | **0.547 s** |
| Invalid final durations / overlaps | **0 / 0** |
| Japanese SRT round trip | Passed |
| Stage digests/report consistency | Passed |
| Completed-stage replay | Passed without another native call |
| Original failed experiment | Unchanged |

The valid preceding caption spans 25:27.320–25:28.960. Its twelve characters plus the two-character suffix fit in one fourteen-character caption after the 110 ms reading hold. The repair preserves its source boundary and records both raw captions as provenance. The final project contains raw, reviewed and final tracks, and the exported JSON report contains `asr_timing_review` decisions.

The final file has 73 warning-bearing captions under existing review rules. These are diagnostics, not 73 confirmed errors, and they do not block the valid export. There is no independently audited complete transcript for this private recording; this experiment establishes formal timing recovery and text preservation, not speech-recognition accuracy.

## Fresh local retry integration check

A separate test injected a zero-duration defect into the cached, previously decoded FLEURS validation-31 sample. This synthetic input fault required the audio branch rather than a suffix merge. One **10.280-second** local XXL retry produced valid timing with unchanged source wording. The actual retry log identifies CUDA execution. Review, layout, export and artifact audits completed in **24.235 seconds** of new work.

This combines cached upstream ASR with fresh local inference. It is not a new full transcription, new held-out quality result or evidence of a CER improvement. Reference labels were not provided to the repair path. Its purpose is to verify that unsupported boundary cases can invoke the native engine and reach export using validated measured times.

## Recovered full-film result

The [122.29-minute experiment](FULL_FILM_COMPARISON.md) completed fresh CUDA ASR but failed at its third zero-duration defect. A separate recovery uses its saved raw ASR, the two already completed structural repairs, and both rejected local retry receipts. It does not rerun the movie or the short retries. The original failed manifest and every retained file under its run directory remain unchanged.

| Check | Full-film recovery |
|---|---:|
| Raw captions | 837 |
| Final captions | **833** |
| Timing repairs | **5** |
| Shared-boundary suffix / prefix merges | 2 / 2 |
| Estimated display intervals | **1** |
| New native inference processes | **0** |
| Reused local audio retry receipts | 2 |
| New work, including export audits/replay | **4.531 s** |
| Invalid final durations / overlaps | **0 / 0** |
| Original source characters retained | All, ignoring layout-only line breaks |
| Exact Japanese SRT round trip / checkpoint audits | Passed |
| Completed pipeline replay | Passed without native inference |
| Review-warning captions | 297 |

The previously unsupported seven-character caption at **50:04.710** receives an estimated display interval **50:04.475–50:05.350**, inside the gap between unchanged neighbours. It is explicitly marked for listening. This does not establish where its speech actually begins or ends. The two later shared-boundary defects merge into their following captions without changing those intervals. Their raw alternatives remain available.

The complete normalized text retains **3,636/6,306 character disagreement (57.66%)** from the unverified Subtitle Edit sidecar. Timing recovery makes no recognition-quality claim and does not improve that score. The 297 warning-bearing captions include overlapping diagnostic categories and are not 297 confirmed errors. Export completes despite warnings. Full-length MDX memory pressure from the original experiment remains separate open work.

Local evidence: `D:/models/.cache/verification-full-film-timing-recovery-20261102`, including final SRT/report, all five repair decisions, copied prior retry evidence, `summary.json` and an isolated result project. Baseline ASR is explicitly marked as cached with its original 3,148.84-second cost retained. The 4.531 seconds measure new recovery work, not another full-film transcription.

## Verification and compatibility

Regression coverage checks boundary/text preservation, display-hold and neighbour limits, manual/translation protection, speaker markers, complete-wording retry acceptance, Unicode mapping, out-of-context retention, source integrity, replay, audio budgets, device failures, offset correctness and final export. Legacy plans keep their original stage list.

The original implementation passed 302 tests. The updated full suite passes **325 tests in 16.78 seconds**; a clean source-only copy passes **325 tests in 18.34 seconds**, without weights, recordings or GPU inference. Fifteen continuation cases add prefix merges, unchanged-neighbour gap allocation, first/last/all-zero/overlapping/out-of-range timelines, one-millisecond availability, protected barriers, exhausted budgets, rejected wording, strict-mode compatibility, validated failed-review resume without duplicate attempts, visible warnings and final export with `needs_review` status.

The original rejected experiment and the recovery run are separate. Recovery does not rewrite historical logs, native SRT or the failed manifest. Models/runtimes/media/settings/caches remain outside Git.

```powershell
.\.venv\Scripts\python.exe -m tools.verify_timing_recovery --source-manifest FAILED_LOCAL_MANIFEST --output NEW_RECOVERY_DIRECTORY
```

Local artifacts:

- `D:/models/.cache/verification-native-timing-recovery-20261102-final`: cached long-ASR recovery, final SRT/report, saved review decisions and an isolated result project.
- `D:/models/.cache/verification-timing-review-live-retry-20261102`: synthetic fault on real audio, fresh bounded native retry and audited output.

The recovery utility requires an unambiguous saved native SRT and the source manifest/audio. It creates a new run and explicitly records reused ASR time instead of reporting cached transcription as fresh inference.

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

If neither repair is supported, the review retains the raw track and attempts and reports the unresolved defect. It does not silently delete a word or manufacture a minimum speaking duration. A failed review can resume from its saved raw ASR stage, without decoding the full recording again. Manual edits remain protected.

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

## Verification and compatibility

Regression coverage checks boundary/text preservation, display-hold and neighbour limits, manual/translation protection, speaker markers, complete-wording retry acceptance, Unicode mapping, out-of-context retention, source integrity, replay, audio budgets, device failures, offset correctness and final export. Legacy plans keep their original stage list.

The full suite passed **302 tests in 15.25 seconds**; a clean source-only copy passed **302 tests in 17.24 seconds**, without weights, recordings or GPU inference. Twenty-one new regression cases cover the timing-review implementation.

The original rejected experiment and the recovery run are separate. Recovery does not rewrite historical logs, native SRT or the failed manifest. Models/runtimes/media/settings/caches remain outside Git.

```powershell
.\.venv\Scripts\python.exe -m tools.verify_timing_recovery --source-manifest FAILED_LOCAL_MANIFEST --output NEW_RECOVERY_DIRECTORY
```

Local artifacts:

- `D:/models/.cache/verification-native-timing-recovery-20261102-final`: cached long-ASR recovery, final SRT/report, saved review decisions and an isolated result project.
- `D:/models/.cache/verification-timing-review-live-retry-20261102`: synthetic fault on real audio, fresh bounded native retry and audited output.

The recovery utility requires an unambiguous saved native SRT and the source manifest/audio. It creates a new run and explicitly records reused ASR time instead of reporting cached transcription as fresh inference.

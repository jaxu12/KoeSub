# Complete Japanese pipeline verification

The complete **11-stage Japanese source-review pipeline** reached audited SRT export on a **122.29-minute local film** in **1,675.062 seconds (27 min 55.062 s)**. This is fresh decoding and review, separate from the earlier cached timing recovery. All stages completed; the final status is `needs_review` because warnings remain. No manual intervention or translation was required to reach export.

Integration success does not establish transcript accuracy. The full auxiliary scan was rejected, and the text changed by only one normalized character. The existing Subtitle Edit sidecar is generated ASR with unverified accuracy.

## Scope and configuration

The test invokes KoeSub's production runner with the existing full Japanese source-review v3 policy: Large V3 GGML baseline, Kotoba v2 auxiliary scan/retries, Qwen3-ASR 1.7B JA Anime as the bounded third decoder, local Qwen3-4B context review, adaptive contexts and Qwen3 forced alignment. Models run on CUDA; no weights were downloaded or copied.

Budgets match the standard full policy: twelve retry windows, six third-model windows and four adaptive targets. Remaining targets are retained as deferred work rather than silently counted as reviewed. Input movie/reference hashes match the earlier native trial. Production Python files were frozen before decoding and verified unchanged after completion. The reference was excluded from inference inputs and scored afterward.

This full preset uses CrispASR/GGML with 16 kHz mono preparation. The earlier Subtitle Edit-compatible native preset uses Faster-Whisper-XXL and MDX stereo preprocessing. Their input processing and decoder policies differ; elapsed times are workflow measurements on this film, not a controlled backend-speed comparison. This is the same development film used in earlier timing work, not a new held-out quality collection. The production runner was invoked by CLI; an isolated GUI project was prepared from its saved results.

## Stage timings

| Stage | Seconds | Outcome |
|---|---:|---|
| Audio preparation | 6.67 | Fresh mono extraction |
| Large V3 baseline | **412.19** | Fresh full-film ASR |
| Automatic timing review | 16.64 | Four invalid captions repaired through two flagged display recoveries |
| Whole-film Kotoba scan | **245.72** | Inference ran; alignment collapse caused quality rejection |
| Bounded ASR retries | 65.27 | Twelve windows; third ASR processed six unresolved windows |
| Japanese phrase review | 0.03 | No text changes accepted |
| Japanese context review | **493.22** | 647 local-model requests/evaluations |
| Adaptive audio | 72.77 | Four targets; one accepted text change |
| Final audio alignment | **361.81** | 173 blocks; 115 caption retimings |
| Japanese layout | 0.03 | Completed |
| SRT/report export | 0.36 | Exact round-trip audit passed |
| Measured wall time, including telemetry shutdown | **1,675.062** | Fresh pipeline |

The retry stage records 54 skipped targets. Third-model work has six deferred windows beyond its six-window budget. Adaptive review records 330 deferred targets. Enabling every stage does not mean exhaustively retrying every finding.

## Transcript and timing results

| Metric | Raw baseline | Final |
|---|---:|---:|
| Captions | 651 | **647** |
| Normalized characters | 6,322 | 6,321 |
| Invalid / zero-duration captions | 4 | **0** |
| Overlaps | 0 | **0** |
| Reading-speed warnings | 49 | 48 |
| Overlong captions | 51 | 50 |
| Exact normalized edits against Subtitle Edit | 5,006 / 6,306 | **5,005 / 6,306** |
| Normalized CER / reference disagreement | 79.38% | **79.37%** |

Timing recovery preserves source text and original bounds in provenance, coalescing captions where needed. Two display intervals remain explicitly unverified. Bounded phrase review applies no text changes. Context review records 332 findings but does not automatically rewrite dialogue. Adaptive review changes one cue, removing one normalized character and reducing reference distance by one edit. This is not independently verified semantic improvement.

Forced alignment runs all 173 blocks without a block-level execution failure. Of 647 captions, **115 receive changed times**, none are split, and 532 retain earlier timing. Rejection reasons are 257 excessive zero-duration token results, 99 unattached zero-duration words, 79 invalid aligned bounds, 55 excessive shifts, 29 neighbour conflicts, nine reading-exposure regressions and four missing usable proposals. Successful native execution does not imply valid alignment for every caption.

There are **602 warning-bearing final captions**. Most warnings describe rejected alignment proposals and retained original times; categories overlap. They are not 602 confirmed recognition errors, and they do not pause the pipeline or block its valid SRT export.

Only 50 / 739 reference captions have unique exact complete-text matches of at least six normalized characters. Median absolute display-time differences are 544.5 ms at starts and 358 ms at ends for this subset. Some text-only matches pair distant occurrences, so these figures cannot establish whole-film acoustic timing accuracy.

The earlier native XXL/MDX transcript has **57.66% disagreement** with the same reference. The full preset therefore has lower agreement with that sidecar despite completing successfully. Neither reference nor hypothesis has an independently audited complete transcript, and shared ASR errors can inflate agreement. It would be incorrect to convert these distances into recognition-accuracy percentages or claim that extra review solved the source-text problem.

## CUDA and memory evidence

- All **59 retained ASR logs** contain actual CUDA backend/buffer evidence, including quality-rejected attempts.
- NVIDIA telemetry observes the baseline PID, the owned context-review PID and **116 / 173 alignment PIDs**. Short processes can fall between the two-second samples; unobserved PIDs are not fabricated as confirmed samples.
- The context server runs with `CUDA0` and GPU offload requested. Its owned session closes after **647 requests**, before subsequent heavy audio work.
- Whole-GPU peak use is **7,552 MiB**, including desktop processes. No fatal CUDA/OOM error or telemetry error is recorded. CrispASR does log a compiled-13.0/runtime-13.5 CUDA minor-version warning; this test does not establish a causal link to alignment collapse.
- Minimum available system RAM is **281 MiB**. The recorded **1,138 MiB process peak covers the baseline engine only**, not the context server or every child. Global memory availability is sampled throughout. Available RAM recovers after context-model release; this is still a material low-memory finding on the 16 GB machine.

## Audits and reproduction

Checkpoint digests, exact Japanese SRT text/time round trip, bounds and report consistency pass. Completed-stage replay preserves digests, stage costs and native-process receipts without new inference. The original movie, reference sidecar and main project pointer remain unchanged. All private dialogue, logs, clips, hypotheses and project databases remain on D: and outside Git.

```powershell
.\.venv\Scripts\python.exe -m tools.compare_local_film --full-jp --media LOCAL_MOVIE --reference EXISTING_JAPANESE_SRT --output NEW_PRIVATE_OUTPUT_DIRECTORY
```

The full-policy helper uses the existing benchmark model locations; adapt those local paths when using another machine. Omitting `--full-jp` retains the native Subtitle Edit-compatible trial. Existing measured directories are not overwritten. Local evidence: `D:/models/.cache/full-jp-loop-20261102`, including `protocol.json`, `run/manifest.json`, `gpu.json`, `live.json`, `run-summary.json`, `comparison.json`, `comparison.md`, final exports and the isolated project.

The required suite passes **329 tests in 19.00 seconds**. A clean source-only copy passes **329 tests in 19.57 seconds**, without recordings, models or GPU inference. Four additional cases cover the complete stage selection, budgets and persisted controls, CUDA-only policy checks, and preservation of the standalone native preset. The production implementation was not changed during this measurement.

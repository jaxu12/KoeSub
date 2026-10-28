# Kotoba and post-benchmark fixes — 2026-10-28

This CUDA-only series improved ASR rejection, timing-compatible selection, source verification, readability, and LLM-session efficiency. The full Easy Japanese 1 run fell from approximately 25:22 to **499.234 seconds (8:19)**. These were different configurations, not an identical controlled before/after experiment: the newer run attempted three ASRs, retained two valid sources, and produced 96 rather than 98 cues.

## Changes

- Invalid ASR timing/alignment is rejected and can be skipped by policy; failed models and durations stay in reports. If every ASR fails, translation does not start. Device, allocation, configuration, and file errors remain fatal.
- The three-ASR preset uses Large V3, Qwen, and Kotoba with VAD. Kotoba requires the existing explicit aligner because unaligned decoding produced zero-duration cues.
- Whole-cue JP selection checks neighboring time compatibility without shifting cue boundaries. If no complete valid combination exists, it retains a coherent source track and records why.
- Full LLM pipelines lazily start one owned offline loopback llama.cpp session after ASR. Model changes release the previous model; completion/failure/worker termination releases owned processes. CUDA0 is explicit.
- Decisions are batched with context budgets, exact-ID checks, and single-target fallback. Resume retains checkpoints.
- EN repairs are generated from JP and separately checked against JP alone. Only `faithful` candidates that win comparison can be applied. Manual EN and uncertain proposals are protected.
- Layout can wrap JP/EN and optionally extend display by up to 250 ms into available gaps. It preserves starts, manual times, neighbors, and media bounds. This is display-time adjustment, not speech alignment.

A later narrow deterministic rule prevents automatic repair of an explicitly punctuated JP question into an EN non-question. It was regression-tested after this full run; saved benchmark output was not manually rewritten or claimed as a rerun.

## Kotoba artifact and performance

One official [Kotoba v2.0 GGML FP16](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0-ggml) file was downloaded: 1,519,521,155 bytes, revision `e3a0cf6a62b95911703cfb97d819292e058f12c3`, SHA256 `eff70a8a236e731abba774ba71e1f6d0fce53302137208c32207e694e0bf4546`. The existing aligner was reused. No duplicate quantization or system-drive model cache was added.

Two AB/BA-order trials on the same 282.73-second recording, CUDA, FP16, beam 5, VAD:

| Model | Trial 1 | Trial 2 | Mean |
|---|---:|---:|---:|
| Large V3 | 47.53 s | 45.20 s | 46.365 s |
| Kotoba + required aligner | 22.44 s | 15.83 s | 19.135 s |

Kotoba was **2.42× faster here**, including loading/alignment. Both successful Kotoba trials had 52 valid cues; Large V3 had 98. This is not a universal speed claim.

On the separate MCDC 112.3-second reference interval, 22 reference cues and 408 normalized characters:

| Model | Duration | CER against community SRT |
|---|---:|---:|
| Large V3 | 26.31 s | 6.13%, 25 edits |
| Kotoba + aligner | 17.00 s | 14.95%, 61 edits |

Kotoba was faster but less accurate against that reference. It remains auxiliary; Large V3 remains the baseline. CER includes spelling differences and possible reference errors, not translation quality or whole-Easy-Japanese accuracy.

## New full run

| Stage | Duration |
|---|---:|
| Cached audio | 0.00 s |
| Large V3 + VAD | 50.38 s |
| Qwen + VAD, rejected | 42.09 s |
| Kotoba + VAD + aligner | 20.67 s |
| JP selection from two valid sources | 18.67 s |
| Unused extra merge slot | <0.01 s |
| Context | 3.44 s |
| Two EN profiles | 41.50 + 42.36 s |
| EN selection | 20.08 s |
| Continuity | 57.39 s |
| Semantic review | 52.53 s |
| Repair generation / verification / choice | 96.91 s |
| Final semantic review | 51.64 s |
| Layout / export | 0.02 / 0.03 s |
| **Total including UI overhead** | **499.234 s** |

One LLM process served **384 valid responses**, with 9.407 seconds to readiness, then closed. A separate three-request session test confirmed the same PID, 2.469/0.109/0.125-second requests, and cleanup.

Two-second whole-GPU samples peaked at 7746 MiB for Qwen, 6680 for Kotoba, 5422 for Large V3, and 4453 during LLM stages, falling to 1178 afterward. These include the desktop and other processes. No live Vulkan testing occurred in this series.

The result had **96 cues, 11 tracks, 30 changed EN cues**, and `needs_review`. Each applied EN repair recorded `source_verification: faithful`; this is a model judgment, not proof. All cues had some warning, largely source disagreement/provenance notes. Layout changed 24 JP wraps and extended 12 displays. Fast EN fell from 20 to 16 and JP from 16 to 15 within this run; overlaps were zero. The older configuration had 11 final fast EN cues, so no cross-configuration overall readability improvement was established.

## Remaining content errors

The same twelve initial creator-caption samples and one targeted sample were used, without giving reference text to models. “PuRiCuA” became “Pretty Cure,” but sentence meaning still had a wrong nuance. The host remained “Kumagai Muna” rather than Mona Kumagai. The fish-availability ASR error propagated into EN. The question about dislikes still had wrong perspective and statement form, motivating the later question-preservation rule. Sendai, broad food topics, and the closing apology retained recognizable meaning.

These changes improved robustness, efficiency, and control over edits. **General content-accuracy improvement was not established.** More ASRs and repeated reviews by one small model do not automatically produce the best transcript.

## Verification and local provenance

The suite at this phase reached 125 passing tests. Qt completion, every stage digest, SQLite persistence, and full JP/EN SRT text/timing were audited. The main user project was preserved.

Local run ID: `509015c7bfe14d2991bc73933b450e69`; root: `D:\models\.cache\benchmark-easy-japanese-1-postfix`. Speed and reference comparisons are under `benchmark-kotoba-cuda` and `benchmark-reference-cuda-kotoba`. Failed unaligned/VAD-disabled trials remain separate. None of these assets is included in Git.

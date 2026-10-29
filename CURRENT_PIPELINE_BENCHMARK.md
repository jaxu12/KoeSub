# Frozen production-pipeline check — 2026-10-29

This check evaluates the existing Japanese transcription pipeline before adding an automatic terminology memory. Production code remains unchanged throughout collection. Translations are disabled.

## Fixed inputs and reference separation

- Ten previously unused application-test recordings: Japanese FLEURS validation rows 30–39, fixed before inference, 120.96 seconds in total.
- Four paired versions of rows 30–33 with deterministic Gaussian noise at a 10 dB whole-file RMS signal/noise ratio, 48.42 seconds. They reuse the same speech and labels and are a separate stress cohort, not four independent recordings. A common gain prevents clipping.
- A 173.541-second interval selected using complete reference-cue boundaries inside minutes 15–18 of the installed MCDC recording. This is an additional range from the same meeting used in earlier tests, not an independent corpus.
- Two generated ten-second controls: exact silence and noise without speech. An empty reference has no defined CER; emitted text and export behavior are checked separately.

The ten FLEURS audio downloads total 7,742,020 bytes. No model weights, full corpus shards or new ML environments were downloaded. Models, new media and all native artifacts stay on D:. The existing subtitle project pointer is checked for changes after production runs.

FLEURS comes from [Google FLEURS](https://huggingface.co/datasets/google/fleurs), revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`, under CC BY 4.0. The MCDC video and community subtitle attribution remain in the installed source receipt described in [JP_TRANSCRIPTION_AND_REFERENCES.md](JP_TRANSCRIPTION_AND_REFERENCES.md). References are published transcripts/community captions, not independently audio-audited gold. These inputs are new to this application check; this says nothing about pretrained model training data or independent speaker identities.

Preparation writes an audio-input allowlist and a separate labels file. Native inference and production review receive only audio paths, hashes, durations, model settings and their own hypotheses. All cases must be collected and frozen before scoring. The scorer rejects missing/duplicate cases, changed inputs, changed labels and mismatched frozen policy. Per-stage missing output remains visible in coverage denominators.

## Production configuration

The full sequence uses Large V3 + VAD, a Kotoba scan, grouped audio retries, unresolved-only Qwen JA Anime/Galgame third decoding, source phrase review, embedded Japanese scene-context review, two-model short/wide adaptive probes, final Qwen forced alignment, layout and Japanese SRT/report export. Existing default budgets are retained: twelve normal retry targets, six third-decoder windows and four adaptive targets. The local text model is Qwen3-4B. ASR, alignment and the embedded model use the configured CUDA runtimes.

For every successful export, the test checks stage artifact digests, SRT round trips, time bounds and report consistency. A second invocation must replay saved results without changing stage digests, original measured stage durations or native-process evidence. This replay is a cache/integrity check, not a second transcription or speed measurement.

Text is scored at baseline, auxiliary scan, source review, context review, adaptive review, alignment and final layout. Reference-distance increases/decreases are reported per case; they are not independently confirmed semantic corrections. Technical checks separately count reading-speed, length, capacity and overlap issues and validate text/timing invariants between stages.

NVIDIA telemetry captures memory, utilization and compute PIDs. ASR proof uses actual CUDA model-buffer logs. Aligner and embedded LLM logs differ, so their owned PIDs are correlated with NVIDIA samples separately; absent short-lived PID samples are inconclusive. Device-wide memory includes other processes. One collector interruption after the first finished case corrected this log classification in the test harness; its completed inference, original timings and outputs were retained. No production policy or reference-based decisions changed.

Unique, exact, complete caption-text matches shared by baseline and final output can also be compared with community subtitle times. These are limited-coverage display-time comparisons, not word-level acoustic timing accuracy.

## Results

**The additional review stages did not improve reference text distance in this check.** All fifteen speech cases produced exports. Fourteen passed exact SRT round trips; the meeting export lost a trailing space during import, with all dialogue characters, cue counts and times retained. Both no-speech controls failed instead of producing an explicit successful no-speech result.

| Cohort | Cases | Audio | Baseline CER | Final CER | Measured processing |
|---|---:|---:|---:|---:|---:|
| New FLEURS read speech | 10 | 120.960 s | 16/451, **3.55%** | 16/451, **3.55%** | 938.781 s |
| Paired synthetic 10 dB noise | 4 | 48.420 s | 6/163, **3.68%** | 6/163, **3.68%** | 386.188 s |
| Additional meeting interval | 1 | 173.541 s | 39/666, **5.86%** | 40/666, **6.01%** | 219.693 s |
| Generated no-speech controls | 2 | 20.000 s | Not defined | Not defined | 17.297 s |

CER is summed character edit distance divided by summed normalized reference length. Noise variants are not pooled into the clean cohort. Their corresponding four clean originals also have 6/163 differences: this particular moderate noise condition did not change aggregate baseline CER. This does not establish robustness to music, reverberation, overlapping speakers or real noisy environments.

The seventeen cases contain 362.921 seconds of audio, including repeated speech in the noise variants. Summed case processing is 1,561.959 seconds (26:01.959), excluding collector investigation pauses, reference scoring and unit tests. The meeting's case interval was recovered from its original manifest creation/finish timestamps after an audit interruption; it excludes telemetry-close time. Its original measured stage durations and GPU samples were retained without new inference. Other case times include telemetry close. These are single-pass measurements on the development desktop, not controlled repeated speed rankings.

### Selection missed useful hypotheses and introduced one regression

Fourteen speech cases retained baseline text. In the meeting, two source-review edits had opposite reference effects:

| Applied phrase | Isolated change in reference edit distance | Interpretation |
|---|---:|---|
| `起草` → `基礎` | +2, worse | A baseline retry and Qwen agreed, despite the original baseline having mean confidence 0.937. |
| `対応` → `対案` | −1, better | A baseline retry and Kotoba agreed. |

The net meeting result is one extra character difference. These effects are measured against community captions; they are not independently audio-audited semantic labels. Scene-context review called the first changed cue coherent and recommended its retry option, so text-context review did not catch this regression. The adaptive stage targets unresolved phrases and did not re-challenge this already-applied edit.

There were seven perfect-baseline speech cases, including paired variants, and none became worse. However, useful alternatives were missed: clean FLEURS rows 31 and 35 each have five baseline differences versus two in the Kotoba scan, while final output retains five. Kotoba is worse on several other cases, including 93 versus 39 differences in the meeting. Globally replacing the baseline with the auxiliary is not supported.

Adaptive audio applied **zero additional phrase edits across all cases**, while consuming **557.900 seconds**. This confirms execution and conservative retention, not demonstrated transcription-quality gain.

### Timing, layout and operational outcomes

- Alignment changed 34 input cues and split two cues in natural production outputs. These are accepted estimates, not 34 independently proven timing corrections.
- Across speech cases, reading-speed violations changed from **9 to 8**, overlong cues from **7 to 4**, capacity violations stayed **0**, and overlaps stayed **0**. The output still contains unresolved readability issues.
- Only **3 of 31** meeting reference cues had unique exact full-text matches in both baseline and final output. On that small matched subset, mean absolute start difference improved from **673.7 to 340.3 ms**, while end difference worsened from **1,493.7 to 1,813.7 ms**. Community display timing is not speech-boundary gold; this is mixed, low-coverage evidence.
- All 231 inspected ASR logs contain actual CUDA model-buffer evidence; this includes copied per-clip logs and is not a count of distinct processes. NVIDIA sampling observed **16/22 aligner PIDs** and **15/15 owned LLM PIDs**. Six short-lived aligner PIDs were not sampled. Telemetry had no errors; device-wide peak memory was **7,524 MiB**.
- All fifteen completed cases replayed without altering stage digests, original stage costs or native-process evidence. Stage text/timing invariants passed. Main project selection was preserved.
- For both generated controls, native VAD reported zero speech and wrote no SRT. The application surfaced a missing-SRT exception. No native dialogue was emitted in these controls, but this is a failed automation outcome, not a successful empty export.
- The meeting's exact round-trip issue is one trailing space after `3月`. All 37 cues retain their times and visible dialogue. It is separate from the reference-distance regression.

| Stage | Sum of original measured durations |
|---|---:|
| Audio preparation | 1.310 s |
| Large V3 baseline | 266.150 s |
| Kotoba scan | 176.300 s |
| Normal retries / third decoder | 321.330 s |
| Source phrase review | 0.100 s |
| Japanese scene-context review | 183.570 s |
| Adaptive audio | 557.900 s |
| Final alignment | 52.090 s |
| Layout / export | 0.950 s |

### Priorities supported by this check

1. Treat confirmed no-speech as a normal completed outcome and define a consistent whitespace contract for exported/imported captions.
2. Revisit automatic acceptance of already-changed phrases, particularly a high-confidence baseline displaced by a shared alternative. Two agreeing weights and a coherent text review were insufficient here. A candidate policy should challenge accepted edits with audio context and preserve the original on weak evidence, then face a separate fixed evaluation.
3. Reduce redundant or low-yield decoding. Adaptive work cost more than twice baseline ASR time without producing a text correction in this collection. Grouping already avoids some reloads, but per-target work still needs better routing and a measured quality/cost comparison.
4. Broaden evaluation with independently checked conversational/anime audio and timing labels. Ten new read-speech clips and one additional interval from a known meeting cannot establish general quality.

An automatic terminology memory is deferred. This experiment provides stronger evidence for improving selection, cost and end-to-end completion first. No production behavior was changed as part of this check.

## Source-only verification

The complete suite passes **272 tests in 15.75 seconds**; a separate clean source-only copy passes **272 tests in 18.15 seconds**, without developer projects, recordings or weights. Eleven new cases cover noise reproducibility/SNR/clipping, exclusion of labels from production inputs, distinct GPU proof sources, unique exact timing matches, whitespace-only export differences, weighted CER with incomplete coverage, no-speech diagnostics, and rejection of incomplete/duplicate/changed frozen collections. Unit tests require no GPU or model downloads.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m tools.fetch_fleurs_reference --root D:\models\datasets\koesub-fleurs-ja-holdout-20261029 --offset 30 --count 10
.\.venv\Scripts\python.exe -m tools.benchmark_current_pipeline prepare --index D:\models\datasets\koesub-fleurs-ja-holdout-20261029\index.json --output NEW_DIRECTORY
.\.venv\Scripts\python.exe -m tools.benchmark_current_pipeline collect --output NEW_DIRECTORY
.\.venv\Scripts\python.exe -m tools.benchmark_current_pipeline score --output NEW_DIRECTORY
```

The installed MCDC recording, its reference captions, local runtimes and model weights are prerequisites. `--meeting-dir` selects another directory containing those same source filenames. The prepared protocol freezes all `studio/*.py` source hashes. Resume preserves completed measurements rather than relabeling cached results as fresh inference. Failed speech cases stop collection for investigation; no-speech failures remain explicit outcomes.

Local artifacts, excluded from Git: `D:/models/.cache/benchmark-current-20261029` contains `protocol.json`, `inputs.json`, `labels.json`, per-case manifests/native logs/telemetry, frozen `collected.json`, `results.json`, `isolated-edit-effects.json` and a generated `report.md`. Frozen collection digest: `dca8d3b344d22b3cadf9c63c8e08ce5710d524cf09d41e204d0b126af513b2e5`.

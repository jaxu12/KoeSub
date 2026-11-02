# Thirty-minute native Whisper test — 2026-11-02

This is a long integration check of the existing **Subtitle Edit Whisper • CUDA FP16 + MDX** preset. Production source hashes and input identity are frozen before inference. No production policy is tuned during the run.

**Later recovery:** automatic timing review now repairs the saved result and produces a valid export without rerunning long ASR. The original failed measurements below remain unchanged. See [AUTOMATIC_TIMING_REVIEW.md](AUTOMATIC_TIMING_REVIEW.md).

## Input and scope

The test uses the first **1,800 seconds** of the preserved audio from the user's earlier long job. The original movie is no longer present at its previous path. The available audio cache is **16 kHz mono PCM16**, covering approximately 109 minutes. The native preset prepares a separate **44.1 kHz stereo PCM16** file of exactly 30 minutes; converting the cached mono source cannot recover its original stereo channels or lost bandwidth.

The input interval includes the first zero-duration subtitle seen in the historical whisper.cpp output, around **26:19**. Historical output is retained separately; only complete cues inside the selected interval are included in the isolated comparison project. It is a historical hypothesis, not an audited transcript reference or a fresh control decode of this exact interval.

All new audio, intermediate files, logs, manifests, telemetry and exports stay under `D:/models/.cache/verification-native-whisper-long-20261102`. Existing Subtitle Edit XXL/CTranslate2/Kim2 assets are reused in place. No model downloads or weight copies are needed. The user's main project selection and earlier subtitle edits are preserved. Private media and transcript excerpts are not quoted or distributed in this repository.

## Procedure

The production workflow runs audio preparation, Faster-Whisper-XXL Large V3 with CUDA float16 and MDX Kim2, Japanese layout, and SRT/report export. It does not invoke the GGML auxiliary/third-decoder/adaptive workflow, translation or a text model.

- Native commands, raw hypotheses and stage receipts are retained.
- NVIDIA telemetry samples device memory/utilization and compute PIDs approximately every two seconds. The owned engine PID is checked separately from device-wide activity.
- The live monitor samples available system RAM and the engine's working set/peak working set every five seconds. Device/system metrics include other applications where indicated.
- Progress shown in the chat contains processing phases and timestamps, not private dialogue.
- Post-run checks cover positive/in-range cue times, zero durations, overlaps, reading speed, long cues, repeated phrases, long gaps, stage digests and SRT/report consistency.
- Repetition and long-gap checks are diagnostics. Natural repeated replies, silence and nonverbal sounds can produce those patterns. They are not counts of confirmed missing or invented dialogue.
- Native JSON can be inspected using the installed decoder's default thresholds: average log probability below −1.0, compression ratio above 2.4, and no-speech probability above 0.6. The decoder's silence condition requires both high no-speech probability and low log probability. Missing metadata remains explicit, and split cues may share decoder metadata. These values do not establish transcription accuracy.
- After completion, replay verifies that saved stage digests, original costs and native-process receipts remain unchanged. This is a completed-stage cache check; the CLI does not checkpoint partial Whisper decoding or MDX progress inside a running stage.

There is no complete independently checked transcript for this audio. Success means the long workflow and its artifacts passed the listed checks, not that every spoken word was recognized correctly.

## Recorded result

**The first unmodified 30-minute run failed production timing validation.** The native executable finished successfully and wrote raw SRT/JSON, but KoeSub rejected one zero-duration cue. Layout and final export did not run. No timestamps were invented and no native text was removed.

| Measurement | Result |
|---|---:|
| Input interval | 30:00.000 |
| Total measured invocation | **14:11.219** |
| Audio preparation | 1.30 s |
| ASR preflight/native stage | 849.70 s |
| Native executable's reported runtime | 14:01.396 |
| MDX displayed progress duration | about 1:44 |
| Raw native captions | **183** |
| Zero-duration captions | **1** |
| Overlapping captions | **0** |
| Final production export | **Blocked by timing validation** |
| Owned engine PID seen by NVIDIA | Yes |
| Device-wide peak GPU memory | 7,347 MiB |
| Engine peak working set | 4,810 MiB |
| Lowest sampled available system RAM | 1,837 MiB of 16,310 MiB |
| GPU/live monitor errors | 0 / 0 |

The invalid caption is cue **165** (one-based), at **25:28.960**, with identical start/end times. Its visible text has two characters, including punctuation. Native word metadata also gives the word zero duration at that boundary, with model word probability approximately **0.178**. The preceding valid caption ends at the same time; the next valid caption starts at 26:09.670. A format conversion alone cannot recover a measured positive interval for this word. Assigning it the entire following gap would create unsupported timing.

This is a quality-validation failure after successful CUDA inference, not a native process crash or memory-allocation failure. The production source and cached source audio remained unchanged. The main subtitle project selection was preserved.

### Technical and confidence diagnostics

| Diagnostic | Native XXL/MDX run | Historical whisper.cpp hypotheses, same 0–30 min range |
|---|---:|---:|
| Captions | 183 | 329 |
| Zero-duration captions | 1 | 1 |
| Overlaps | 0 | 0 |
| Reading speed above default JP limit | 33 | 21 |
| Captions longer than default maximum | 6 | 11 |
| Consecutive repeated-phrase runs | 0 | 3 |
| Distinct exact captions appearing at least ten times | 2 | 6 |
| First caption | 1:04.090 | 2:09.090 |
| Last caption | 28:06.090 | 29:58.850 |

The historical output is reused evidence from the earlier whole-recording decode. Runtime, preprocessing and segmentation differ, and this is not a controlled accuracy comparison. Fewer repeat runs do not prove fewer hallucinations. The native output has no caption after 28:06.090, despite consuming the full 30-minute input; without an audited transcript, this cannot be labeled correct silence or missed dialogue.

Native JSON has complete confidence metadata for **155 decoder segments**, distinct from the 183 formatted SRT captions. At native defaults, 36 segments have low average log probability, one has high compression ratio, and 23 have high no-speech probability. None satisfy both the decoder's low-logprob and high-no-speech conditions together. These are model self-assessment flags, not 36 confirmed errors or 23 confirmed silent regions.

### Artifacts and replay outcome

The raw SRT/JSON, all original timestamps and full native logs remain under `run/asr-0`. An isolated diagnostic project contains the raw native track, the historical hypotheses and a bookmark on the invalid native cue. Its title marks the blocked export; it is not a completed final subtitle project. No private dialogue is included in this public report.

Completed-pipeline replay could not be tested because the ASR stage failed validation. A separate rerun-guard check confirms that requesting the same recorded failed experiment is refused without replacing the original manifest, raw SRT, native log, summary or GPU evidence. Their hashes are retained in `failure-replay-audit.json`. Read-only source/audio/confidence checks are in `post-inference-audit.json`.

This run supports fixing automatic containment of a small invalid region: retry the affected audio and validate its replacement while preserving the successful surrounding hypotheses and the original failed output. It does not justify assigning arbitrary durations, silently deleting words, or presenting this run as production-ready. No production repair policy was implemented or tuned during this test.

The full source-only suite passed **281 tests in 15.11 seconds** and a separate clean source-only copy passed **281 tests in 16.43 seconds**, without recordings, model weights or GPU inference. Three new tests cover non-mutating timing/repetition diagnostics, filtering private timestamped dialogue from live progress, and confidence coverage/silence-rule semantics. These unit results are separate from the failed real-recording test.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m tools.verify_long_whisper --source-manifest EXISTING_LOCAL_MANIFEST --output NEW_DIRECTORY --seconds 1800
```

The source manifest must have an existing `audio/result.json` and its cached WAV. The tool accepts 60–1,800 seconds for bounded verification. A completed run with an existing summary is audited without replacing its original telemetry or presenting cached inference as a fresh run.

Local artifacts include `protocol.json`, `run/manifest.json`, `run/asr-0/engine.log`, `gpu.json`, `live.json`, `summary.json`, `post-inference-audit.json`, `failure-replay-audit.json` and the diagnostic `ui/last_project.json`. This recorded failure has no final `exports/Japanese.srt` or `exports/report.json`; those are created only after production validation succeeds. All these artifacts are excluded from Git.

# Subtitle Edit Whisper profile — 2026-11-02

KoeSub now has a source-only **Subtitle Edit Whisper • CUDA FP16 + MDX** preset. It reuses the existing Faster-Whisper-XXL executable, CTranslate2 Large V3 directory and `Kim_Vocal_2.onnx` from the configured Subtitle Edit installation. Nothing is copied or downloaded.

**Current workflow update:** new source-only runs include [automatic timing review](AUTOMATIC_TIMING_REVIEW.md) between raw ASR and layout. The original four-stage measurements below are historical; the new stage repairs supported invalid native boundaries before final validation.

## Diagnosis

The previous KoeSub setup selected whisper.cpp/CrispASR with a GGML model. Subtitle Edit used Faster-Whisper-XXL with a CTranslate2 model and these options:

```text
--standard_asia --compute_type float16 --ff_vocal_extract mdx_kim2
```

These are runtime/preprocessing options, not a text prompt. `standard_asia` is a subtitle segmentation preset; MDX performs vocal separation before recognition. The [upstream executable documentation](https://github.com/Purfview/whisper-standalone-win) and installed r245.4 help describe the distinct runtime and local vocal model.

In the user's earlier long job, the raw whisper.cpp SRT contained 790 cues, including 15 with zero duration. KoeSub correctly rejected the invalid timings, but this left the baseline unavailable to the remaining workflow. The raw hypotheses and log remain intact. A short crop from an affected time range did not reproduce the zero-duration issue: long-context behavior remains a limitation of this diagnosis. No artificial timestamps or silent deletion were introduced.

The installed XXL executable/model were not configured in KoeSub's saved settings, so merely selecting a Whisper model did not reproduce Subtitle Edit's processing.

## Changes

- The new pipeline preset selects installed XXL Large V3, CUDA, float16 and local MDX Kim2. It runs audio preparation, native transcription, Japanese layout and export without translation or a text model.
- The native profile leaves XXL context/decoding defaults intact. The legacy profile retains earlier overrides, including disabled previous-text conditioning, for existing configurations.
- The transcription tab exposes profile selection, the MDX checkbox and **Use installed Subtitle Edit Whisper + MDX**. A successful setup adds only the existing `_models` directory to discovery and preserves other runtimes/model roots.
- Native MDX input is prepared as PCM16 stereo at 44.1 kHz. It has a separate cache identity and a corresponding disk-space estimate. Existing 16 kHz mono cache names remain compatible.
- Local CTranslate2 weight/config/tokenizer files and the selected vocal asset are included in resumable pipeline identities. Changes invalidate resume. FFmpeg is added to child-process PATH; temporary files stay under the configured cache.
- This native preset does not run the CrispASR-specific auxiliary, third-model or adaptive retry sequence. Those controls are disabled for this baseline, and the established GGML workflow remains available. It does not disguise XXL output as GGML output.

The user's local settings were backed up and configured to reuse the installed files. Existing project selection, manual subtitles, source hypotheses and historical jobs were preserved. These settings and all recordings remain outside Git.

## Native comparison

Twelve fresh native calls compared four fixed excerpts, each decoded with current CrispASR, native XXL, and native XXL with MDX. Comparison inputs were identical 16 kHz mono crops; this isolates the CLI/runtime/filter configuration but does not recreate Subtitle Edit's original full-quality audio path. A separate production test below verifies the new stereo path.

| Excerpt | Audio | CrispASR | XXL without MDX | XXL with MDX |
|---|---:|---:|---:|---:|
| Public street interview | 45.00 s | 20.343 s | 36.765 s | 89.750 s |
| Private dialogue excerpt | 30.00 s | 17.765 s | 56.875 s | 86.688 s |
| Private excerpt around an earlier invalid timestamp | 30.00 s | 16.235 s | 24.657 s | 72.532 s |
| Previously inspected FLEURS validation row 31 | 12.54 s | 20.718 s | 45.156 s | 67.079 s |

All twelve calls exited successfully and produced positive, in-range, non-overlapping SRT times. This does not prove that a full-length job has no timing errors. Logs explicitly identify XXL r245.4 running on CUDA; MDX was requested on CUDA and NVIDIA telemetry was captured. Peak device-wide memory reached 7,671 MiB, including other GPU processes. These are single-pass desktop timings, including launch/initialization overhead, not controlled speed rankings.

The one published-reference clip had **5/56 character differences (8.93%)** for CrispASR, **2/56 (3.57%)** for plain XXL and **5/56 (8.93%)** for XXL with MDX. Labels were read for scoring after native collection. This is a previously inspected development clip, not a new holdout or independently audited audio reference. It shows that MDX is not a universal improvement. There is no complete transcript reference for the interview or private excerpts, so no accuracy ranking is claimed for them. Private audio/transcripts are retained locally and are not quoted in this repository.

## Actual KoeSub pipeline verification

A separate fresh 45-second public-video run used the production preset and **44.1 kHz stereo** preparation. Original measured stages were:

| Stage | Time |
|---|---:|
| Audio preparation | 0.83 s |
| XXL/MDX preflight and ASR | 83.31 s |
| Japanese layout | 0.00 s |
| Export | 0.03 s |
| Sum | **84.17 s** |

The native engine PID was observed on the NVIDIA device. Stage digests, final cue bounds, Japanese SRT round trip and exported report passed. Export was resumed from the completed ASR after a test-console encoding error; native inference was not rerun, and original inference timing and GPU telemetry were retained. This is fresh ASR plus cached-stage export recovery, not a fresh uninterrupted wall-time measurement. There is no full reference for this excerpt.

The required suite passed **278 tests in 28.67 seconds**, and a separate clean source-only copy passed **278 tests in 22.40 seconds** without developer data or weights. New tests cover reuse without copying, native flags/defaults, missing local MDX rejection, CT2/vocal asset identity, cache format separation, source-only execution/resume and native-preset UI restrictions. Source compilation and Git whitespace checks also passed.

## Reproduction and artifacts

```powershell
.\.venv\Scripts\python.exe -m tools.verify_subtitle_edit_whisper --output NEW_DIRECTORY --source-manifest EXISTING_LOCAL_MANIFEST
```

Omit `--source-manifest` to exclude the private cached-audio excerpts. The tool uses prepared local media and the installed Subtitle Edit runtime; it never fetches models. The public-reference input is optional when its existing local index is absent. Hypotheses, commands and measurements remain in the output cache.

Local artifacts: `D:/models/.cache/verification-subtitle-edit-whisper/comparison` and `native-pipeline`, including original native files, telemetry, commands, per-call measurements, post-inference reference scores and an isolated result project. They are excluded from Git.

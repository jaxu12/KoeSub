# Historical full-recording benchmark — 2026-10-28

This report describes the earlier pipeline before whole-transcript context and later persistent LLM sessions. It is historical evidence, not a benchmark of the latest default Japanese-only mode. See [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md) and [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md) for later changes.

## Scope

The entire **188.6-second Job Interview** animation by Simpleshow Japan was processed on an RTX 5060 8 GB, driver 621.01. [Source and attribution](https://commons.wikimedia.org/wiki/File:Job_Interview.webm): CC BY-SA 4.0. The recording is not included in Git.

The full pipeline used Whisper Large V3 FP16 GGML and Qwen3-ASR JA Anime Q8 with VAD, JP selection, Qwen3-4B Instruct Q4_K_M natural/faithful EN profiles, EN selection, deep review, repair, verification, layout, and JP/EN export. Context was 4096, translation batches six cues, estimated splitting disabled. Durations include model loading and process handling.

## Full-recording timings

| Stage | Vulkan | CUDA |
|---|---:|---:|
| Metadata probe, measured separately | 0.36 s | 0.16 s |
| Cached audio | 0.02 s | <0.01 s |
| Whisper Large V3 | 39.59 s | 40.77 s |
| Qwen ASR | 56.08 s | 30.12 s |
| JP selection | 50.78 s | 32.31 s |
| Natural EN | 55.50 s | 48.22 s |
| Faithful EN | 53.34 s | 46.23 s |
| EN selection | 143.95 s | 102.00 s |
| Deep review | 195.97 s | 150.03 s |
| Repair / comparison | 106.88 s | 84.80 s |
| Verification | 196.49 s | 144.59 s |
| Layout | 0.01 s | <0.01 s |
| Export / report | 0.02 s | 0.03 s |
| **Pipeline wall time** | **899.67 s** | **680.09 s** |

Fresh audio extraction separately took 0.529 seconds. Main runs reused cached audio; the operating-system cache was not reset. CUDA was approximately 24.4% faster for these particular sequential Vulkan→CUDA trials, not a repeated average. Whisper itself did not speed up.

## GPU evidence

CrispASR reported supported CUDA backends and actual CUDA buffers / `CUDA0`; the LLM used `--device CUDA0 --n-gpu-layers 99` with a CUDA backend log. This was not inferred only from a GUI setting.

Two-second `nvidia-smi` sampling observed whole-device peaks of 7725/8151 MiB during Qwen ASR, 5843 MiB during Whisper, and 4564 MiB during translation, with up to 96% utilization. These include desktop and unrelated GPU use. No telemetry read errors or model failures occurred. A compiled-CUDA-13.0/runtime-13.5 warning was retained in logs. Normalized Whisper text matched between backends; Qwen outputs differed by about 0.62% of characters.

Only official runtime archives were added; checksums were verified and existing model weights reused. Vulkan artifacts were preserved. Later experiments use CUDA only.

## Outcome and limitations

Both runs completed 12 stages and retained ten tracks. Artifact integrity, nonempty EN, time bounds, SRT round trips, and report consistency were checked.

| Final indicator | Vulkan | CUDA |
|---|---:|---:|
| Cues | 52 | 55 |
| Warning-bearing cues | 45 | 46 |
| EN above 20 chars/s | 6 | 6 |
| JP above 8 chars/s | 13 | 15 |
| Cues involved in overlap | 2 | 4 |
| AI-flagged cues | 8 | 13 |
| EN cues changed during repair | 9 | 7 |

Warnings overlap and are not confirmed error counts. Raw ASR tracks had no overlaps; mixing selected groups introduced them. This exposed the need for timing-compatible selection, implemented later. The result remained `needs_review`; no unsupported retiming was used to hide the problem.

Semantic issues remained, including a suspicious metaphor rendered as “clouds nesting in trees.” No complete independently checked Job Interview transcript was used, so no ASR accuracy percentage is reported.

Decision/review logs alone started the LLM 172 times on Vulkan and 189 on CUDA, accounting for approximately 440 and 263 seconds of model loading. This motivated later batching and persistent owned sessions.

## Independent subtitle comparison

A separate [MCDC Japanese onboarding meeting](https://commons.wikimedia.org/wiki/File:MCDC_Onboarding_%22Ask_me_Anything%22_session_-_Japanese_language.webm) by TCappelletto (WMF), CC BY-SA 4.0, was acquired as 23:10 of 240p video, approximately 20.9 MiB. Existing [JP captions](https://commons.wikimedia.org/wiki/TimedText:MCDC_Onboarding_%22Ask_me_Anything%22_session_-_Japanese_language.webm.ja.srt) and [EN captions](https://commons.wikimedia.org/wiki/TimedText:MCDC_Onboarding_%22Ask_me_Anything%22_session_-_Japanese_language.webm.en.srt) were preserved with revision and attribution metadata. Only SRT separators/numbering were repaired; ten empty EN entries were explicitly omitted. Caption text was not corrected using our models.

The ASR-only comparison covered **01:09.380–03:01.680**, 112.3 seconds, 22 complete reference cues, and 408 normalized characters. It did not process the whole 23-minute meeting or translate/review this second recording.

| CUDA ASR | Stage duration | Character edits | CER |
|---|---:|---:|---:|
| Large V3 | 24.70 s | 25/408 | 6.13% |
| Qwen3-ASR JA Anime | 22.55 s | 38/408 | 9.31% |

Audio preparation took 0.84 seconds; total test time was 48.38 seconds. CER uses exact Levenshtein distance after Unicode NFKC and removal of punctuation, spaces, and music markers. Kanji/kana and numeral spellings are not equated. Community captions may contain errors and omissions; this measures differences against them, not certain audio errors or translation quality.

## Local provenance

Historical run IDs under `D:\models\.cache\pipeline`: Vulkan `3453c5f64d91402ebee141520c25963e`, CUDA `a7e62c5e33794bf183c7573536c7e103`, reference ASR `c88c5cd80d8940d0b4d1e22a615ac464`. Benchmark roots include `benchmark-easy-full`, `benchmark-easy-cuda-full`, and `benchmark-reference-cuda`. Artifacts and recordings are excluded from Git. The historical suite had 99 passing tests; current verification is in [TEST_REPORT.md](TEST_REPORT.md).

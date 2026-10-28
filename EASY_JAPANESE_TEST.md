# Easy Japanese 1 — historical full-recording test

Recorded on 2026-10-28: the complete **282.73-second** street-interview video was processed through ASR, JP context, two EN profiles, EN selection, continuity review, semantic review, repair, verification, layout, and export. The result had **98 cues, 34 changed EN cues, 74 warning-bearing cues, and status `needs_review`**. It was not publication-ready.

## Recording and reference

[Easy Japanese 1 — Typical Japanese](https://www.youtube.com/watch?v=qzzweIQoIOU), Easy Languages, contains interviews in Sendai, street noise, musical transitions, and burned-in JP/romaji/EN captions. YouTube rejected anonymous download with HTTP 429/login requirements. A public [Bilibili mirror of the same episode](https://www.bilibili.com/video/BV1yt411N7mb/?p=1) was used without an account or cookies. Title, duration, and visible content were checked; byte identity with the YouTube file was not claimed.

Local media: 1280×720 H.264/AAC, 55.03 MiB, SHA256 `796f132cc85ac3652157623d4387689b8d60ccb7bb97b426f6880eea0e044f1a`. Source metadata is retained locally under `D:\models\test-media\easy-japanese-1`. Media are not distributed with KoeSub.

Twelve initial visible-caption samples and one targeted 46.5-second sample were read from original frames. The extra sample was selected after a suspicious ASR result was noticed. No complete independent SRT was obtained. Caption fragments and differing speech/caption boundaries prevent a whole-film WER/CER claim. Reference text was not supplied to the models.

## Configuration and timings

The intended two-ASR setup failed: Qwen had alignment errors, and Whisper without VAD produced invalid timing. The completed run used **one Whisper Large V3 + VAD**, not two independent transcriptions. Qwen3-4B Instruct Q4_K_M ran through CUDA llama-completion with context 4096 and translation batches of six. Natural/faithful EN profiles shared the same weights.

| Completed stage | Duration |
|---|---:|
| Cached audio | 0.00 s |
| Large V3 + VAD | 48.45 s |
| Whole-transcript context | 20.73 s |
| Natural / faithful EN | 82.05 / 81.98 s |
| EN selection | 149.73 s |
| Continuity | 100.17 s |
| Review all 98 cues | 297.80 s |
| Repair generation / comparison | 432.95 s |
| Review verification | 307.41 s |
| Layout / export | <0.01 / 0.05 s |
| **Total** | **1521.725 s** |

Total time comes from original creation/completion timestamps and excludes downloads, preceding failed attempts, and later audit/UI replay. The first audio extraction took 0.28 seconds and was reused. Decision/review logs recorded 412 LLM calls and 637.063 seconds of loading, roughly 42% of the full run, excluding separately cached translation calls. Persistent sessions were implemented later.

## CUDA and rejected ASR attempts

Whisper logs and LLM `CUDA0` arguments confirmed CUDA. Whole-GPU telemetry peaked at 5380 MiB during successful ASR and 4865 MiB during LLM work. Samples include desktop/other GPU use. The CUDA build/runtime minor-version warning remained in logs.

| Rejected variant | Observation |
|---|---|
| Qwen + VAD, default windows | About 65.45 s; exit 31, missing word times / aligner collapse |
| Qwen + VAD, 15 s windows / 1 s overlap | 36.64 s, exit zero, but zero-duration cue and alignment warnings |
| Qwen without VAD, 10 s windows | 33.77 s, exit 31, three chunks missing word times |
| Whisper without VAD | About 58.44 s; 138 cues, including 12 zero-duration cues and repeated text |

Qwen reached 99% GPU utilization and 7753 MiB total GPU use. The reported failure was alignment, not OOM. Strict validation remained enabled and invalid cues were not assigned invented times.

## Content findings

| Sample | Finding against visible creator captions |
|---|---|
| 3.5 s, host name | Mona Kumagai became “Kuma Muna” in EN; summary and both profiles shared the wrong name and review missed it |
| 7 s, Sendai | Place and broad meaning retained |
| 44 / 46.5 s, fresh fish | Availability was misrecognized as `国の開発度`, the country's development level; EN repeated it and review did not repair it |
| 63 s, healthy food | Broad meaning retained, EN wording shortened |
| 88 s, black hair | Broad meaning retained; review removed an intensifier |
| 117 s, meals and consideration | Idea retained, but final EN was too long |
| 145 s, snow | Recognizable fragment; adjacent cues needed for a full judgment |
| 172 s, anime | “Anime, right?” changed the nuance of “I guess anime” |
| 199 s, Pretty Cure | Correct JP `プリキュア` became “paying attention to PuRiCuA,” missing the styling reference |
| 220 s, dislikes about Japan | A question to interviewees became a first-person question about a place; review left a flag |
| 243 / 265 s | Broad meaning of the sampled “yabai” explanation and closing apology retained |

The summary recognized food, consideration, language, and anime, but misspelled the name and incorrectly suggested no clear negative opinions. No A/B experiment isolated summary influence, so errors cannot be attributed solely to context.

## Review and readability

Thirty-four changed EN cues are not 34 proven semantic repairs; some are shortening or paraphrase. Two profiles differed in 50/98 cues.

| Indicator | Selected EN before review | Final |
|---|---:|---:|
| EN over 20 chars/s | 13 | 11 |
| JP over 8 chars/s | 16 | 16 |
| Cues with overlaps | 0 | 0 |
| Warning-bearing cues | 61 | 74 |

More warnings include newly added review notes and do not alone indicate worse text. Final JP and timing matched the valid Whisper+VAD source. Estimated splits and manual correction were not applied. Timing checks detected problems but did not automatically resolve all short displays/readability issues.

## Application fixes and provenance

A transient errno-only `EACCES` reading `en-1/partial.json` escaped Windows-winerror-only retry handling. Bounded retry now covers that variant while preserving errors for bad JSON or permanent denial. Reopening also exposed a callback on a deleted waveform `QProcess`; Qt-object validity checks were added.

After fixes, 74 relevant core/pipeline/UI tests passed, artifacts were audited, both SRT files matched complete final text/timing, and all 12 checkpoints replayed into SQLite. Nine tracks and 98 final cues were retained. The 25-minute inference was **not rerun** after the I/O fix; verified artifacts were replayed.

Completed run ID: `c97c4289b82440f9a717f22735d5741d`; local root: `D:\models\.cache\benchmark-easy-japanese-1-final`. Assets are not in Git. See [KOTOBA_AND_FIXES.md](KOTOBA_AND_FIXES.md) for later changes and remaining limits.

# Adaptive audio retries and final source alignment

KoeSub can now revisit unresolved Japanese phrases with two audio contexts and align the selected final text to speech before export. These are optional source-only pipeline stages. They reuse installed models; no training or new model downloads are involved.

The order is baseline ASR, auxiliary scan/retries, phrase review, optional Japanese context review, adaptive audio, final alignment, layout and export. Any owned embedded LLM session is closed before the new audio stages. Existing manifests without the new options retain their original plans.

## Adaptive audio

The default budget is four target cues. Genuine unresolved ASR disagreements take priority over additional suspicious/name flags from text-context review. Manually edited or reviewed cues and contexts containing them are excluded.

Each target has a short context with one-second padding and a wide context with six-second padding. Bounds expand to whole source cues and are capped at 45 seconds. Quiet-region hints may adjust edges by up to 800 ms without trimming the target. These hints come from PCM energy, not an assertion that a region contains no speech.

Two existing model weights, normally Large V3 and Kotoba, decode both contexts:

| Profile | VAD speech padding | Minimum silence |
|---|---:|---:|
| Short | 120 ms | 100 ms |
| Wide | 300 ms | 250 ms |

Jobs are grouped per model/profile, giving four native ASR invocations for a non-empty adaptive batch. Four targets therefore produce at most 16 additional clips. This adds processing time; it is not a speed optimization. The ordinary retry grouping checkbox controls the preceding retry stage; adaptive profiles are always grouped.

Automatic phrase changes require all four usable attempts to agree, two distinct model paths, both contexts for each model and confidence of at least 0.8 from both baseline retries. Existing single-cue, temporal, anchor, length, Latin/number and manual-edit guards remain. Repeated runs of one model do not become extra independent votes. Disputed or weak evidence retains the current text. No reference text enters inference.

Original hypotheses, exact model/VAD settings, crops, audio hashes and immutable attempt receipts are retained. Source/crop changes invalidate resume; incomplete unreceipted audio is preserved before regeneration.

## Final alignment and exposure

Final alignment uses the installed Qwen3 forced aligner through CrispASR's align-only mode. It aligns the chosen text without transcribing again. Speech groups are at most 25 seconds, plus up to 400 ms of audio padding per side. Long single cues, punctuation-only cues and protected cues retain their source timing.

A full-recording experiment exposed unreliable long-input alignment and a dropped punctuation-only cue. Bounded groups avoid the aligner's long-audio chunking limit, preserve cue mapping and isolate failed blocks.

Each proposal must cover the complete normalized input text, have finite in-range ordered word times and stay within 1.5 seconds of the source cue bounds. Excessive zero-duration words are rejected. An isolated zero-duration token can be coalesced with an adjacent measured interval; it never receives an interpolated positive duration. Raw text is preserved.

A two-state-per-cue selection keeps a globally non-overlapping timing path, retaining original times where candidates conflict. Manually edited/reviewed cues keep their text, timestamps, annotations and layout.

Display exposure is separate from measured speech duration. A subtitle may linger for at most 600 ms after the measured word end, toward its existing end time, to meet minimum exposure and reading-speed constraints. The measured words remain unchanged, and speech end / display hold are recorded separately. A proposal that creates a new reading-speed violation or worsens an existing excessive rate is rejected.

Long cues are split only when actual word boundaries provide a complete feasible partition. The partition prefers punctuation, pauses and conservative Japanese phrase boundaries, avoids splitting Latin words and continuous kanji/katakana compounds, and obeys reading limits. With defaults, each part needs at least 834 ms, at most seven seconds and at most 40 characters. When no safe partition exists, the cue remains intact. Splitting cannot make arbitrarily fast speech readable without changing content.

Native memory/device failures stop the pipeline. A quality failure or malformed alignment block retains the input cues and is reported. Before/after times, rejected proposals and original native output remain available.

## Interface and compatibility

The Japanese pipeline has independent controls for adaptive audio, target budget, final alignment and aligned splitting. Final alignment is disabled when no local aligner is configured.

**Adaptive ASR comparison** shows both contexts from both models, their full hypotheses and matching playback ranges. Phrase decisions remain available separately. **Timing changes** shows changed cues first, original/output times, split children, rejection reasons and any display hold.

Original, review, adaptive, aligned and final tracks stay in the project. Explicit ASR phrase selection still requires a compatible pre-alignment track. For retimed/split output, edit the final cue directly or select its pre-alignment review track for phrase choices. This version adds stages to the Japanese pipeline; standalone realignment of arbitrary imported tracks is not implemented.

## Recorded CUDA verification — 2026-10-28

The 282.73-second Easy Japanese street interview completed with fresh baseline, scan, retries, context review and both new stages. Audio preprocessing reused its existing cache. Total wall time was **347.953 seconds**.

| Stage | Measured time |
|---|---:|
| Large V3 baseline | 54.580 s |
| Kotoba scan | 26.230 s |
| Existing retries / third decoder | 77.500 s |
| Initial phrase review | 0.020 s |
| Japanese context review | 104.300 s |
| Adaptive audio, four targets | 54.910 s |
| Final alignment, 12 blocks | 30.020 s |
| Layout / export | 0.180 s |

Adaptive audio applied **zero additional text changes**. Alignment changed **20 of 98 cues**, with a maximum accepted shift of 1,360 ms. The recording already had no overlong/over-capacity cues, so no cue splitting was needed. Reading-speed violations changed from **16 to 15**. The output still has 91 warning-bearing cues; warnings are diagnostic, not 91 proven errors.

An earlier development version shortened exposure too aggressively, increasing reading-speed violations from 16 to 19. The final exposure safeguards reject those proposals. The earlier result is not the final benchmark result.

CUDA ASR logs and NVIDIA compute-process samples confirmed GPU use, including aligner child PIDs. The owned LLM closed before the first adaptive ASR child started. Artifact digests, bounds, non-overlap, text preservation, SRT round trips and report consistency passed. There is no independently audited word-timing reference here, so moved timestamps are not automatically proven more accurate.

Local full-run artifacts: D:/models/.cache/verification-audio-refinement-easy-fresh.

### Existing five reference clips

Five previously used FLEURS Japanese clips were checked using **cached upstream stages and new CUDA adaptive/alignment inference**. This is not a fresh full-pipeline timing comparison or a new blind cohort.

| Clip | New work | Adaptive targets | Text edits | Retimed cues |
|---|---:|---:|---:|---:|
| Validation 10 | 41.719 s | 1 | 0 | 1 |
| Validation 11 | 3.109 s | 0 | 0 | 0 |
| Validation 12 | 38.843 s | 1 | 0 | 0 |
| Validation 13 | 2.687 s | 0 | 0 | 2 |
| Validation 14 | 42.016 s | 2 | 0 | 5 |

Both baseline and final output still have **6/257 character differences (2.33% CER)**. No semantic transcription gain was demonstrated. Published labels were used only after inference and are not independently audio-audited in this project. Artifacts: D:/models/.cache/verification-audio-refinement-references.

A separate fresh alignment check deliberately merged the two cached ASR cues of the 17.46-second validation-12 recording into one 59-character cue. It split into two measured ranges, 3.710–6.590 s and 6.750–13.470 s, preserving every character and leaving the source manifest unchanged. Alignment took 2.797 seconds. This is a constructed layout regression on real audio/ASR text, not a fresh transcription or a gold-timing test. Artifacts: D:/models/.cache/verification-audio-refinement-merged-layout.

## Reproduction and tests

~~~powershell
.\.venv\Scripts\python.exe -m tools.verify_audio_refinement --source-manifest SOURCE_MANIFEST --output NEW_DIRECTORY
.\.venv\Scripts\python.exe -m tools.verify_audio_refinement --source-manifest SOURCE_MANIFEST --reuse-upstream --output NEW_DIRECTORY
.\.venv\Scripts\python.exe -m tools.verify_audio_refinement --references --output NEW_DIRECTORY
.\.venv\Scripts\python.exe -m tools.verify_audio_refinement --source-manifest CLIP_MANIFEST --merged-layout --output NEW_DIRECTORY
~~~

Prepared runtimes/models/media are required; none are distributed in Git. The reference mode uses the existing local FLEURS benchmark paths. Unit tests use synthetic local fixtures and require neither weights nor GPU inference.

The required full suite passed with **261 tests in 14.37 seconds**. A separate clean source-only copy passed the same **261 tests in 15.76 seconds**, without application data, model weights or recordings. Source compilation and Git whitespace checks also passed. Saved timing and adaptive-comparison dialogs were rendered and visually inspected without rerunning inference.

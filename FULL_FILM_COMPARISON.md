# Full-film Subtitle Edit comparison — 2026-11-02

The subsequent [fresh complete Japanese pipeline test](FULL_JP_LOOP.md) exercises all eleven stages and reaches audited export in 27 min 55 s. It uses the separate GGML/CrispASR full preset, records degraded auxiliary work and only a one-character text change; it is not a rerun of this native MDX preset.

**Follow-up:** the [updated timing review](AUTOMATIC_TIMING_REVIEW.md#recovered-full-film-result) recovers this saved result to an audited **833-caption final SRT, with no invalid times or overlaps**, in **4.531 seconds of new work**. It reuses the full-film ASR and short retry receipts; one display interval is explicitly estimated. The original failed experiment documented below remains unchanged.

**Full-film ASR completed on CUDA, but automatic timing review failed and blocked final export.** The retained raw transcript was compared with the existing Subtitle Edit sidecar. This is a recorded failure of the complete native-preset pipeline, not a successful final-subtitle export.

## Scope and reference

A complete **122.29-minute local film** was selected from four recordings with existing Japanese sidecars. Selection used duration and subtitle timing integrity, before comparing transcript wording. The reference contains **739 captions and 6,306 normalized characters**, with no zero-duration captions or overlaps.

The user reports that this sidecar was generated in Subtitle Edit. Its original model, complete command and manual-edit history are unknown. It is an **unverified ASR reference, not an independently checked transcript**. Agreement cannot establish which system is right, including when both share an error. This experiment does not evaluate translation.

The private film, reference, dialogue examples, native logs and project database remain outside Git. The original movie and sidecar are read-only inputs. A separate result directory and editor project preserve the main project.

## Fresh production run

The measured pipeline uses existing local Faster-Whisper-XXL r245.4, CTranslate2 Large V3, `--standard_asia`, CUDA `float16`, VAD and `mdx_kim2` vocal extraction. No model weights are downloaded or copied. Original stereo audio is prepared at 44.1 kHz; native temporary files and results use the D: cache.

The full interval runs once, without dividing the movie into independent ASR jobs:

`audio → raw ASR → automatic timing review → Japanese layout → export`

Translation, LLM review, auxiliary/third ASR, adaptive retries and forced alignment are disabled for this native preset. Automatic timing review remains enabled. This is the complete native-preset path, rather than every optional KoeSub feature.

Before inference, the protocol freezes input hashes, production Python files and configuration. The comparison reference is excluded from inference inputs and scored only after production finishes. An owned-process resource guard monitors sustained critical RAM and output-volume exhaustion.

Hardware: Windows, NVIDIA RTX 5060 with 8 GB VRAM, 16 GB system RAM. GPU telemetry includes other desktop processes; the native engine PID is checked separately against NVIDIA's process inventory.

## Measured results

| Stage | Measured time | Outcome |
|---|---:|---|
| Stereo audio preparation | 7.64 s | Completed |
| Full-film native ASR, including MDX | **3,148.84 s / 52 min 28.84 s** | Completed |
| MDX portion, included above | About 6 min 30 s | Completed; native progress measurement |
| Automatic timing review | 103.73 s | Failed after two structural repairs and two local retries |
| Japanese layout / final export | Not run | Blocked by unresolved timing |
| Wall time through failure and telemetry shutdown | **3,260.672 s / 54 min 20.672 s** | Fresh measured work |

| Check | Subtitle Edit sidecar | KoeSub raw ASR |
|---|---:|---:|
| Captions | 739 | **837** |
| Normalized characters | 6,306 | **6,620** |
| Zero-duration captions | 0 | **5** |
| Overlaps | 0 | 0 |
| Reading-speed warnings under KoeSub rules | 307 | 189 |
| Overlong captions under KoeSub rules | 3 | 14 |

The complete normalized transcripts differ by **3,636 character edits / 6,306 reference characters = 57.66% CER**. This substantial disagreement survives punctuation/spacing normalization. It does **not** mean that 57.66% of the recognized speech is wrong, or that either system has a corresponding accuracy score. Both transcripts require independent listening before one can be preferred. No semantic improvement is demonstrated.

Differences vary across the film. Diagnostic ten-minute bins show 15.63% distance at 0–10 minutes, 75.76% at 40–50, 74.04% at 70–80, 105.74% at 90–100 and 30.68% at 110–120. Whole captions are assigned by midpoint; boundary/segmentation differences can inflate these local scores. CER can exceed 100% when insertions exceed the short reference denominator. These are listening priorities, not verified regional error rates. All thirteen bins and twenty distributed listening locations are saved privately.

### Timing-review failure

The five raw zero-duration captions occur at **18:22.800, 20:25.960, 50:04.710, 1:14:49.930 and 1:27:36.320**. Review merges the first two with their preceding captions at an existing shared boundary, without display hold. Every original source character remains in the partial reviewed track, which has 835 captions.

The third defect is a seven-character zero-duration caption separated from its neighbours. It does not satisfy the conservative short-suffix boundary rule. Fresh CUDA/MDX retries of **12.0 and 24.43 seconds of audio** take **49.297 and 50.406 seconds** respectively. Both return usable positive times but different wording; neither contains the complete original target phrase. They therefore cannot become text-preserving timing repairs. Review stops with `AsrQualityError`. The last two defects are not reached, so this experiment does not establish whether those two could be repaired automatically.

Three invalid captions remain in the incomplete review. There is no final SRT, export round-trip audit or successful whole-pipeline replay. The original failed manifest/native output remain intact. Completed audio and raw-ASR checkpoints were independently re-read and replayed without invoking work or changing their receipts; this is **partial checkpoint reuse**, not a completed-pipeline integration pass or another transcription.

### Matched timing and resource use

Only **102 / 739 reference captions** have unique exact complete-text matches of at least six normalized characters in the 837-caption raw hypothesis. Median absolute differences are **705 ms at starts and 105 ms at ends**. Two text matches differ by over five seconds, including one roughly eighteen-minute mismatch. Such text-only matches can pair different utterances; their arithmetic mean is unsuitable as a whole-film acoustic drift estimate. Unmatched captions are not scored as correctly timed.

NVIDIA telemetry observes the owned native PID **26244**. No GPU telemetry errors, CUDA execution errors or OOM termination are recorded. Whole-GPU peak use is **7,567 MiB**, including the desktop; peak native-engine RAM is **7,405 MiB**. Available system RAM briefly falls to **4 MiB** around the MDX/ASR handoff before recovering. The sustained-pressure guard does not trigger. This is a material resource-pressure finding, rather than evidence that full-length preprocessing is comfortably bounded on a 16 GB machine.

Hashes confirm that the original film, reference sidecar and frozen production Python files are unchanged. The main project pointer is unchanged. No model download or full-film ASR rerun was required for comparison.

### Consequences

The long test exposes two concrete priorities: bounded audio preprocessing to control peak RAM, and an additional evidence-backed timing repair path for defects unsupported by exact-text ASR retries. Text selection also needs independently audited listening examples: the existing Subtitle Edit sidecar alone cannot identify the better decoder. Production behavior was deliberately left unchanged while measuring this failure.

## Comparison method

Whole-transcript CER is **exact normalized character Levenshtein distance**, using arbitrary-width Myers bit vectors rather than a capped quadratic traceback matrix. Normalization removes punctuation, spacing and selected non-speech labels. This is reference disagreement, not independently measured recognition accuracy. Different cue segmentation alone does not increase the whole-transcript distance.

Timing comparison includes only unique, identical complete captions of at least six normalized characters. Coverage and unmatched denominators are explicit. Start/end differences describe Subtitle Edit display timing, not acoustic accuracy. Unique text alone is not proof that a match corresponds to the same utterance.

Listening suggestions use a separate heuristic alignment. A limited sample spans the beginning, middle and end of the observed differences. These excerpts stay private and are not treated as verified errors or exact edit-operation counts.

Technical diagnostics cover positive durations, bounds, overlaps and reading speed. Completed checkpoint digests/reuse and unchanged inputs are verified. Export text/time round trips and whole-pipeline replay are performed only after successful export; neither was reached in this run. Readability/repetition warnings are diagnostics rather than confirmed recognition errors.

## Reproduction and local artifacts

```powershell
.\.venv\Scripts\python.exe -m tools.compare_local_film --media LOCAL_MOVIE --reference EXISTING_JAPANESE_SRT --output NEW_PRIVATE_OUTPUT_DIRECTORY
```

The utility requires existing local runtime/model assets and a film longer than thirty minutes. It refuses to overwrite a previous measured run. Models, recordings and reference subtitles are not distributed.

Local evidence: `D:/models/.cache/comparison-local-film-20261102`. This directory contains `protocol.json`, the failed native pipeline, `live.json`, `gpu.json`, `run-summary.json`, `comparison.json`, the private Markdown comparison, a clearly labelled raw native SRT with five invalid times, and an isolated diagnostic project. That project contains reference, raw ASR and incomplete-review tracks. It is not a final export. A completed-stage replay is an integrity check, not another measured transcription.

## Source-only verification

The required suite passes **310 tests in 18.21 seconds**. A clean source-only copy passes **310 tests in 19.74 seconds**, without developer recordings, data or model weights. Eight added cases cover exact distance against exhaustive dynamic programming, long transcripts, normalization, unique-caption timing coverage, distributed heuristic listening locations, temporal-bin exclusions/empty denominators, incomplete-check reporting and comparison after a failed review without rewriting evidence.

The initial sandboxed suite had one localhost permission failure in the existing synthetic HTTP worker fixture; rerunning with local loopback access passed. This was separate from the real GPU pipeline failure. Unit-test success does not turn the failed film export into an integration pass.

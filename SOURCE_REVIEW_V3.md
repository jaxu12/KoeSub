# Source review v3 — third ASR, Japanese context and grouped inference

Date: 2026-10-28. The source transcription workflow now combines three bounded stages before export. Translation remains optional and was not used in these checks.

## Audio evidence and third-model routing

Large V3 remains the baseline. A Kotoba scan detects disagreements and low-confidence intervals retain their existing retry priority. Local retries are collected by model, preserving each window's original native output, confidence, model path, input range and decision provenance.

Only windows still disputed after the first two decoders, or missing a usable hypothesis, are eligible for the third model. The default third choice is the existing Qwen3-ASR 1.7B JA Anime/Galgame conversion. There is a separate limit, initially six windows. Deferred windows remain available for listening. No weights are downloaded by the pipeline.

Version 3 can accept a bounded phrase when a third decoder corroborates a high-confidence baseline retry despite a dissenting auxiliary. Two auxiliaries agreeing against the baseline retry cannot replace it. Existing temporal, anchor, phrase-length, name/number, confidence and manual-edit protections remain. Supporting and dissenting model paths are recorded. Model agreement can still be wrong.

Versions 1 and 2 retain their original plans and selection policy. Existing manifests do not silently enable the new stages.

## Japanese scene-context review

An optional Japanese-only stage runs after ASR processes exit. It uses the embedded local LLM, normally Qwen3-4B, with LM Studio available as a secondary backend. The owned embedded session loads lazily and closes on exit or cancellation.

Each cue is checked against up to two nearby cues on either side, excluding context more than 15 seconds away. Unique cue IDs and an explicit target marker avoid presenting the target as duplicated dialogue. The reviewer flags suspicious words, names, homophones and continuity concerns. For disputed phrases it can recommend only an exact supplied ASR option ID, keeping the text or listening. It cannot return new transcript text. Recommendations appear in the phrase comparison dialog; source-only flags also appear when all decoders share an error.

Context advice adds notes and recommendations, never automatic LLM rewrites. Accepted audio-evidence edits remain a separate, auditable decision. The local context window is not a complete understanding of the film, and a plausible suggestion is not proof of what the speaker said. Manual and reviewed cues are skipped. Completed decisions can be resumed with source, prompt-policy and schema validation.

## Grouped CUDA inference

The installed CrispASR 0.8.45 runtime, revision `e58bb48b`, supports multiple sequential input/output pairs in one native invocation. KoeSub uses that path, preserving its SRT and full Whisper token-confidence output. One pending batch runs per model; models do not occupy GPU memory concurrently. This requires no user-managed ASR server.

The [pinned dispatcher](https://github.com/CrispStrobe/CrispASR/blob/e58bb48b/examples/cli/crispasr_run.cpp) initializes the backend before its sequential input loop. The [Whisper implementation](https://github.com/CrispStrobe/CrispASR/blob/e58bb48b/src/crispasr.cpp) defaults to resetting text context and initializes decoder RNG state for each transcription call. GPU results are still not guaranteed byte-identical.

Each batch records measured wall time including model load. Per-clip `seconds` values are explicitly labeled amortized shares of the batch, not independently measured clip latency. Transport receipts point to the shared command/log. Ordered audio-duration markers permit per-clip alignment-warning attribution; incomplete or mismatching markers preserve the full log and fail closed. Memory/device failures stop the pipeline. A quality failure stays in the exported report and cannot silently become a valid hypothesis. Unreceipted native output left by cancellation is archived before another decode, preserving the hypothesis without allowing a failed attempt to reuse stale subtitles.

### Fresh timing comparison

Three existing FLEURS development recordings were decoded once as a group and once in separate processes for each model, using the same installed weights, explicit CUDA and decoding settings. No native results were replayed for this measurement.

| Model | Three separate processes | One grouped process |
|---|---:|---:|
| Large V3 | 35.297 s | 20.641 s |
| Kotoba | 14.781 s | 12.813 s |
| Qwen JA Anime/Galgame | 17.078 s | 16.219 s |

All nine cases had identical text after the documented NFKC/punctuation/whitespace normalization, and equal reference edit counts. Raw punctuation, segmentation, times or confidence were not identical in every Whisper case. This is one ordered comparison on short development clips, not a randomized repeated benchmark or a claim of uniform speedup on whole films. CUDA inference was confirmed from every engine log.

Local artifacts: `D:\models\.cache\verification-source-v3-batch`. Reproduce with `python -m tools.verify_source_review_v3 --mode batch --output NEW_DIRECTORY`; post-inference scoring uses `--mode batch-eval` on that directory. Prepared assets are required and are not distributed in Git.

## Full recording and separate reference check

The verification utility runs the complete 282.73-second Easy Japanese street interview with a fresh baseline and scan, grouped retries, bounded third-model decoding, source phrase review, embedded context review, layout and export. It checks completed artifact digests, SRT round trips, bounds, baseline timing preservation and actual CUDA logs. This film has only sampled burned-in subtitle comparisons here, so it does not provide a complete CER score.

The first development run exposed batch-wide rejection from one clip's alignment warning and a missing quality-failure report field. Both were fixed and have regression coverage. Its failed/incomplete run is not a successful full-pipeline result.

The corrected fresh full-film run completed in **390.547 seconds**, including the first context prompt:

| Stage | Measured time |
|---|---:|
| Large V3 baseline | 50.830 s |
| Whole Kotoba scan | 25.920 s |
| Crops and grouped audio retries | 74.060 s |
| Phrase comparison | 0.020 s |
| First context prompt | 239.490 s |

There were 12 retry windows and six third-model windows out of 11 eligible unresolved windows. Three native retry processes handled 12 Large, 11 Kotoba and six Qwen clips; one additional Kotoba hypothesis was reused from the scan. A Kotoba and a Qwen alignment failure in the same window were rejected individually. Two phrase edits affected one of 98 cues, matching the earlier known corrections; no further transcription gain was demonstrated. Baseline times, artifact digests, exported SRT and report consistency passed verification.

The first context prompt marked 96 cues, mostly as uncertain, and sometimes mistook the repeated target in its request for repeated dialogue. The final prompt identifies a single timed target, treats ordinary dialogue as coherent unless a concrete textual concern exists, and requests one short reason. A **new CUDA context-only run over the verified saved ASR/review results** took **86.422 seconds**. It returned 54 `ok` and 44 `suspicious` statuses; 56 cues had a concern or non-keep recommendation, and the final subtitle report had 73 warning cues. These are diagnostics, not 44 proven errors or 73 incorrect subtitles. False positives remain possible. No LLM rewriting or extra automatic subtitle changes occurred. This replay is not a fresh full-pipeline timing measurement.

The embedded reviewer used one owned model process for 98 requests and released it afterward. Movie telemetry confirmed GPU activity during the context stage. A separate short structured-response check matched the owned LLM PID in NVIDIA's compute-process list; its default runtime logs omit allocation/backend messages. ASR CUDA evidence is present in engine logs. All real inference checks used CUDA, with no Vulkan or CPU inference tests.

Local movie artifacts: `D:\models\.cache\verification-source-v3-easy-r2`; final context replay and isolated review project: `D:\models\.cache\verification-source-v3-context-r3`. The replay utility accepts `--mode context-replay --source-manifest MANIFEST --output NEW_DIRECTORY` and verifies copied upstream stage digests.

Five additional FLEURS Japanese validation recordings, fixed rows 10–14, were downloaded separately: 64.86 seconds, 4,151,330 source audio bytes. Only audio paths, hashes and time ranges enter production inference; published reference labels are scored afterward. These are read speech, not a movie, and the transcripts were not independently audio-audited here. Dataset license: CC BY 4.0. No claim is made about model-training contamination or independent speakers.

Both baseline and reviewed output had **6/257 character edits (2.33% CER)**. No phrase changes were applied, so the test demonstrates integration and unchanged quality on this small set, not a measured accuracy improvement. Qwen was used on three of five clips; all ASR hypotheses passed quality checks and all 17 native ASR logs confirmed CUDA. The five fresh runs took 55.329, 38.375, 66.000, 40.625 and 73.578 seconds respectively. These runs used the first context prompt; context never edits transcript text, and the final prompt was measured separately in the movie replay. Artifacts: `D:\models\.cache\verification-source-v3-references`.

The final suite has **208 passing tests**, also verified in a clean source-only copy without local recordings, models or settings (13.82 seconds). The suite includes cancelled-output preservation, warning attribution, quality-failure export, third-model selection, prompt-policy checkpoint binding and manual-edit protection. Hardware checks are separate from unit tests.

Hardware results and reference totals are recorded separately from unit tests. Run `python -m tools.verify_source_review_v3 --mode movie --output NEW_DIRECTORY` or `--mode references` with the prepared local assets. Neither mode downloads models.

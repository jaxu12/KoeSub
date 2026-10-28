# ASR selection and fusion benchmark — 2026-10-28

**The current production review did not improve the baseline on these ten clips.** Reference-guided selection found useful alternatives, so there is measurable selection opportunity, but that oracle is not a production result.

## Data and separation

| Source | Clips | Audio | Normalized reference characters |
|---|---:|---:|---:|
| Existing MCDC meeting comparison core | 5 | 112.30 s | 408 |
| Newly acquired Japanese FLEURS recordings | 5 | 63.96 s | 237 |
| Total | 10 | 176.26 s | 645 |

The MCDC core was evaluated previously and is not a new holdout. Its community SRT was not independently audited against audio. The separate [Google FLEURS](https://huggingface.co/datasets/google/fleurs) corpus provides **read speech, not another movie or meeting**. The first five Japanese validation rows (0–4) were fixed before ASR. They were acquired at revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`; checksums and attribution are retained locally. Only 4,093,730 bytes were downloaded, rather than a full corpus shard. No model weights or extra ML environment were downloaded.

This is a small corpus-level external check. We do not claim independent speaker identities, absence from a pretrained model's training data, or a human-audited gold standard. Both references can differ from spoken audio or acceptable spelling.

Inference receives an explicit allowlist of audio inputs and ordinary model settings. Reference text and labels are excluded from ASR configuration and production review. Production results are frozen before reference-based scoring. The oracle lives in an evaluation-only module, outside the app's review path.

## Results

CER is summed character edit distance divided by summed reference length, after the same NFKC/casefold and punctuation/spacing normalization used in earlier tests. It is not an average of per-clip percentages, a translation score, or guaranteed audio error.

| Variant | MCDC CER | FLEURS CER | Combined CER | Combined edits | Accepted subtitle outputs |
|---|---:|---:|---:|---:|---:|
| Large V3 baseline | 6.62% | 1.69% | **4.81%** | 31/645 | 10/10 |
| Kotoba | 10.78% | 3.80% | 8.22% | 53/645 | 10/10 |
| Qwen JA Anime/Galgame | 15.93% | 4.64% | 11.78% | 76/645 | 10/10 |
| Anime GGML conversion | Incomplete text coverage | 8.44% | Not comparable | Not ranked | 8/10 |
| Reazon GGUF conversion, text only | 27.94% | 6.75% | 20.16% | 130/645 | 5/10 |
| **Production baseline + retries + review** | **6.62%** | **1.69%** | **4.81%** | **31/645** | **10/10** |
| Oracle: Large V3 + Kotoba + their retries | 4.66% | 1.69% | 3.57% | 23/645 | Evaluation only |
| Oracle: all accepted models + retries | 4.66% | 0.84% | **3.26%** | **21/645** | Evaluation only |
| Oracle: best complete hypothesis per clip | 5.39% | 0.84% | 3.72% | 24/645 | Evaluation only |

Acceptance here requires native output validation, positive in-range timestamps, and **no overlapping cues**. This is stricter than checking positive cue lengths alone. Reazon's earlier one-of-five positive-timing MCDC case fails the additional overlap check. Its readable text is still scored, but rejected subtitle hypotheses are excluded from fusion and oracle pools. Anime has readable text in nine of ten clips, including one invalid UTF-8 failure in the MCDC set; its partial-text score is not ranked against complete coverage. Its previously documented conversion issue remains relevant.

## What the oracle measures

The reference-free construction stage aligns hypotheses to the baseline, expands differences into script-run phrases, and creates a monotonic lattice of complete source fragments. An exact edit-distance dynamic program then uses the reference to choose whole phrase edges. It cannot freely vote for individual characters or invent reference text absent from the candidate paths. Complete hypotheses are also available, so the oracle cannot score worse than the best accepted whole hypothesis.

Usable production retries are included by overlaying each retry window on the unchanged outside baseline. This avoids understating the available pool when the application had an extra audio decode.

The oracle finds the optimum **inside this constrained lattice and whole-hypothesis pool**. It is not an unrestricted upper bound on speech recognition quality, does not solve synchronization, and cannot be used for unknown recordings without the reference. Choosing complete hypotheses alone reaches 24 edits; phrase-level selection reaches 21. Production uses no reference and remains at 31.

## Production behavior and examples

Only two retry windows were selected, both in MCDC. All ten production outputs retained their baseline text and timestamps: **zero helpful, harmful, or neutral applied phrase changes**. Four clips had a baseline/reference mismatch but no retry window. Thus the current confidence-driven targeting misses some discrepancies, and strict corroboration does not recover every useful retry.

- In FLEURS row 0, Large V3 wrote `企画後` while Qwen matched the published `帰国後`. No production retry was selected. The production auxiliary is Kotoba, so this example also shows the opportunity outside the current two-model policy. Qwen was nevertheless worse on aggregate; it should not replace Large V3 globally.
- In MCDC clip 3, a baseline retry reduced the reference distance from five edits to two, but production did not apply it. The auxiliary's mean confidence was approximately 0.236 and the hypotheses did not satisfy the production agreement requirements.
- In MCDC clips 1 and 4, phrase selection can retain useful Kotoba fragments while preserving stronger baseline text elsewhere. Some gains concern name spelling and other orthographic differences, not independently confirmed semantic repairs.

The benchmark supports investigating **ASR disagreement as an additional review/targeting signal**, including disagreements when baseline confidence is high. It does not justify lowering confidence thresholds or applying majority voting blindly. Production rules were not tuned during this run. New policy changes should be checked against additional unseen recordings and unnecessary-edit controls; these ten clips are now inspected development evidence.

## Timing and CUDA

| Variant | Sum of original ASR/review stage durations |
|---|---:|
| Large V3 | 165.30 s |
| Kotoba | 87.16 s |
| Qwen | 129.26 s |
| Anime conversion, including rejected attempts | 70.40 s |
| Reazon conversion, including rejected attempts | 44.22 s |
| Production, including seeded baseline ASR cost | 221.51 s |

Production adds **56.21 seconds** of retries/review/layout/export to the baseline stage sum. Baseline stages copied into retry manifests have zero current execution time; their original ASR cost is explicitly restored for this comparison.

The collection session took **392.029 seconds (6:32)** including its initial scoring. Twenty model cases reused verified historical artifacts; thirty model cases and four retry decodes were new. This wall time is not a fresh run of all fifty model cases. Per-case cache flags and original durations are preserved. Historical and new timings are not a repeated controlled speed ranking, and short clips include substantial model-loading overhead. Later scoring replay took no GPU inference and is not presented as collection time.

Actual CUDA inference evidence was found in all **50 model logs**, plus all four production retries. New-session telemetry contains 210 samples across 40 session files, no sampling errors, a whole-device peak of **7376 MiB**, and sampled utilization up to **100%**. Device-wide figures include the desktop and other GPU processes. VAD can use CPU independently of the main ASR model. No live Vulkan tests were run.

## Reproduction and artifacts

The tools require configured local runtimes and model files; they never download weights automatically. Prepare the existing MCDC bank if needed, then acquire the small separate corpus sample and run:

```powershell
.\.venv\Scripts\python.exe -m tools.fetch_reference_media
.\.venv\Scripts\python.exe -m tools.prepare_jp_references
.\.venv\Scripts\python.exe -m tools.fetch_fleurs_reference
.\.venv\Scripts\python.exe -m tools.benchmark_asr_fusion
.\.venv\Scripts\python.exe -m tools.benchmark_asr_fusion --evaluate-only
```

Defaults describe the development setup on `D:\models`. `--bank`, `--external`, and `--output` select reference and result locations. The model paths are declared explicitly in the benchmark's `MODELS` list and must match your installation. Quality failures retain readable text separately; allocation, device, and other operational failures stop collection rather than being silently counted as low-quality ASR, including after resume.

Local artifacts, excluded from Git:

- `D:\models\.cache\benchmark-asr-fusion-v1/protocol.json`: fixed selection, model paths, audio hashes, reference digest, and production-review source hash.
- `inputs.json`: reference-free inference inputs.
- `collected.json`: frozen production/model results and collection digest `540fd925d5254906bb996d88c3b113a0335f98434d2be1a2646692f47e1c67de`.
- `results.json` and `report.md`: per-case scores, oracle provenance, coverage, and summaries.
- `collection-timings.json`, `gpu-summary.json`, and per-run logs/telemetry.
- `D:\models\datasets\koesub-fleurs-ja-v1/index.json`: source revision, selection, references, and audio checksums.

The test suite now has **173 passing tests**, including exact oracle checks against exhaustive complete-phrase paths, reference/input separation, weighted CER and missing coverage, preservation of frozen outputs, retry-pool eligibility, baseline-inclusive timing, and operational-failure handling. Original projects and completed earlier experiments were preserved.

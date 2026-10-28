# Auxiliary disagreement scan and editable source review — 2026-10-28

KoeSub now offers a full auxiliary ASR scan before choosing Japanese retry windows. It detects disagreement even when Whisper reports high confidence. The source-review dialog also supports explicit human phrase selection, saved with provenance and undo.

## Behavior

1. Large V3 + VAD remains the baseline. The selected auxiliary, normally Kotoba, decodes the same recording once.
2. Nearby time intervals are compared independently of subtitle segmentation. Differences are review signals, not proof that either model is wrong.
3. Existing low-confidence/repetition targets retain priority within the retry budget. Additional disagreements use remaining capacity, so a large number of scan differences cannot starve earlier risk windows.
4. Baseline-risk windows retain fresh local-context decoding by both models. Additional disagreement windows can reuse complete auxiliary scan cues when real timestamps cover the target; otherwise the auxiliary is decoded locally. No artificial timestamps are introduced.
5. Version 2 can apply a bounded correction despite high baseline confidence when a genuine scan disagreement was recorded and a confident baseline retry plus another model corroborate the phrase. Context, temporal, manual-protection, and source-fragment constraints remain. Disagreement alone cannot replace text.
6. Disable the new scan checkbox for the earlier confidence-targeted workflow. The retry-window limit bounds extra work. A full scan and more retries can increase runtime substantially.

New Japanese-only jobs use `source_review_version: 2` and configurable `retry_asr.scan_first`. Older manifests retain their existing stage plans and version-1 decisions. No translator or reference text is used. Auxiliary quality failures can be reported while retaining the baseline; device/allocation/configuration failures still stop the job.

## Human phrase selection

In the source-review dialog, select a row and an ASR alternative or the original baseline, then use **Use selected ASR phrase**. Current text, timestamps, and ancestry are validated before changing the active review/result track. This action cannot modify original ASR tracks. Structural/cross-cue changes require direct editing.

Choices are stored in the project's job metadata with source model/directory, original character range, and before/after text. They remain unreviewed and can be undone together with their decision records. Multiple choices in one cue are reconstructed without stale offsets. Already reviewed, independently manually edited, retimed, or stale cues are rejected. Existing translations are retained but invalidated rather than silently rewritten.

Completed pipeline artifacts remain immutable. Export the edited active track again to update subtitle files after a human choice.

## Additional-clip evaluation

The production policy was frozen before decoding ten additional clips: MCDC clips 6–10 and FLEURS Japanese validation rows 5–9. These are new clips within previously inspected corpora, not source- or speaker-independent data. The five FLEURS recordings added 4,781,090 download bytes on the data drive. No weights were downloaded.

A subsequent full-movie test exposed retry-budget starvation. Scheduling was corrected to preserve baseline-risk priority, then revalidated in a separate revision directory using only configuration- and window-matched native outputs. This replay is not another blind experiment. Original experiments remain preserved; no word-specific repair or reference-derived prompt was introduced.

| Set | Baseline CER | Earlier production CER | Scan/review v2 CER | Reference edits, baseline → v2 |
|---|---:|---:|---:|---:|
| Previously inspected development clips, 10 | 4.81% | 4.81% | 4.81% | 31 → 31 / 645 characters |
| Additional clips, 10 | 10.09% | 10.09% | 9.79% | 67 → 65 / 664 characters |

Development: 11 disputed cues, eight retry windows, five reused auxiliary fragments, no applied edits. Additional clips: 18 disputed cues, 11 windows, eight reused fragments, two applied edits. Against the references, one edit helped, one was neutral, and no clip's CER worsened. Baseline timestamps were preserved.

**The measured gain is primarily orthographic, not a demonstrated semantic repair.** The helpful edit was `のほうに` → `の方に`, matching reference spelling. The neutral edit changed `共国` to `教国`; both are wrong against published `峡谷`. Corroborating models can share a homophone error. References are not independently audio-audited, and no claim about training contamination or independent speakers is made.

## Full street-interview recording

The complete 282.73-second Easy Japanese recording retained 98 cues and selected 12 retry windows from 82 disputed cues. One auxiliary attempt was reused; baseline-risk windows received local auxiliary decoding.

The initial scheduling experiment lost the earlier fish correction because disagreement targets consumed the budget first. Corrected priority restored both earlier edits in the 44.12–47.51-second cue: `を得ても` → `いつでも`, and the spelling change producing `一番いいところですね`. The remaining fish-availability error was not repaired. There is no complete independent SRT, so no whole-film CER is reported.

Stage digests, SRT round trips, report consistency, and time bounds passed audit. All baseline timestamps remained unchanged. The final result has 60 warning-bearing cues, including disagreement/provenance notes; this is not 60 confirmed errors. The rendered Qt comparison dialog with human-choice controls was inspected.

## Cost and CUDA

| Set | Baseline stage cost | Earlier production cost | Scan/review v2 cost |
|---|---:|---:|---:|
| Development clips | 165.30 s | 221.51 s | 396.65 s |
| Additional clips | 145.45 s | 145.78 s | 465.41 s |
| Full street-interview recording | 52.56 s | About 305 s | About 334 s |

These are original or reconstructed stage costs, **not current cache-replay wall times**. Reused baseline/scan costs are counted once; reused native window attempts retain their original durations, with measured non-decoding overhead accounted for. Short clips pay repeated loading costs. This is not a repeated controlled speed benchmark, and the scan mode can be substantially slower.

The initial clip collection took 606.578 seconds with cached development and new inference. The scheduling-revision replay took 16.234 seconds; the final movie revision took 97.977 seconds of new work. Neither replay time represents fresh end-to-end transcription.

CUDA was confirmed from native logs for new/reused attempts. Revision telemetry had no read errors; sampled whole-device peaks were 4215 MiB for the clips and 5148 MiB for the movie. These include desktop/other processes. No live Vulkan tests were run.

## Verification and reproduction

**191 automated tests pass**, covering disagreement detection, segmentation tolerance, baseline-risk priority, scan reuse/fallback, version-1 compatibility, quality/device failures, timestamp/manual protection, stale choices, SQLite decision persistence, undo, and cache-aware timing. Fresh-checkout tests require no local models or recordings.

Development-machine commands, with separately configured models/runtimes and reference banks:

```powershell
.\.venv\Scripts\python.exe -m tools.fetch_fleurs_reference --root D:\models\datasets\koesub-fleurs-ja-holdout-v1 --offset 5 --count 5
.\.venv\Scripts\python.exe -m tools.verify_asr_scan --output D:\models\.cache\verification-asr-scan-v2-r2 --reuse-run D:\models\.cache\verification-asr-scan-v2
.\.venv\Scripts\python.exe -m tools.verify_asr_scan_movie --output D:\models\.cache\verification-asr-scan-v2-easy-r2 --reuse-manifest D:\models\.cache\verification-asr-scan-v2-easy\runs\easy-full-scan-v2\manifest.json
```

The `--reuse-*` options require the corresponding earlier local experiments and validate source digests, windows, and decoding configuration. Omit them for fresh work in a new output directory. Frozen protocols reject changed policy/input definitions.

Local artifacts, excluded from Git:

- `D:\models\.cache\verification-asr-scan-v2-r2`: protocol, frozen collection, scores, report, and logs.
- `D:\models\.cache\verification-asr-scan-v2-easy-r2`: movie comparison, sampled creator captions, SRT, and isolated editable project under `ui/`.
- `D:\models\datasets\koesub-fleurs-ja-holdout-v1`: revision, references, checksums, and recordings.

The main user project was preserved. These changes improve disagreement coverage and editable decisions; broad automatic semantic correction remains unsolved.

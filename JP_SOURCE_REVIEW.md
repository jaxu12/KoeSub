# Japanese source review — 2026-10-28

New jobs run **Japanese source review before translation**. The default Japanese-only pipeline is: Large V3 + VAD → targeted audio retries → phrase comparison and fusion → layout → subtitles. It requires no translator or LLM.

Earlier logic required agreement across an entire audio window. A useful local correction was rejected when models disagreed elsewhere in that window. The new review aligns local text, checks surrounding matches and time overlap, and changes only text within baseline cues. Baseline timestamps and segmentation remain unchanged.

## Automatic correction requirements

- The same phrase must occur in a baseline-model retry and a different model. Every available usable hypothesis must agree; a third conflicting hypothesis blocks replacement. Two runs of the same model file do not count as distinct models.
- The baseline cue must have a low-confidence signal. The matching baseline retry cue must have confidence of at least 0.8. This is an average of cue token probabilities, **not a calibrated probability that a phrase is correct**.
- Both sides need matching context, and source cues must overlap in time. The replacement must be a verbatim contiguous fragment of one decoded cue.
- Added text, deletion of entire utterances, cross-cue changes, Latin-script names/numbers, and large edits require listening. Manual and reviewed cues are protected.
- Comparison units expand across hiragana, katakana, or kanji runs. This is a conservative heuristic, not morphological analysis. It prevents selecting shared characters such as `配列` from conflicting words `配列道` and `配列堂`.

Applied changes remain unreviewed. Reports preserve before/after text, character ranges, source cue IDs, model paths, confidence, and raw-output directories. Shared model errors can still satisfy these conditions.

Full translation jobs also run a JP review stage after whole-cue selection and before context/EN generation. It marks differences against raw hypotheses. Without a baseline retry and its confidence evidence, that stage does not apply automatic phrase replacements. Existing `merge-*` whole-cue selection is separate.

## Real-recording replay

The test reused completed CUDA outputs from the full 282.73-second Easy Japanese 1 recording: 98 baseline cues and nine audio windows, each retried by Large V3 and Kotoba. No ASR was rerun and no models were downloaded. Original artifacts were preserved.

| Result | Value |
|---|---:|
| Comparison units with differences | 28 |
| Applied phrase edits | 2 |
| Changed cues | 1 |
| Unresolved units | 26 |
| New review stage | 0.01 s |
| Review, layout, export, and cache handling | 0.1161 s |
| Timestamp changes | 0 |

At 44.12–47.51 seconds:

- `を得ても` → `いつでも`: both retries agree, and `いつでも` is visible in the creator's caption at 44 seconds.
- `一番良` → `一番い`: together with the retained suffix, the result is `一番いいところですね`. This mostly matches the creator's spelling rather than repairing another meaning error.
- `の開発度` remains unchanged: `配列道` and `配列堂` disagree and are both wrong. The original caption says `手に入るっつうとこは…`. Review **did not repair the entire sentence**.

This is a targeted example, not a held-out quality score. There is no complete independent SRT for this recording in the test set, so no whole-recording CER is reported. Warning-bearing cues increased from 35 to 47 because review exposed more differences and recorded notes; warnings are not a count of confirmed recognition errors.

## Verification and local artifacts

The suite reached **156 passing tests**: local fusion despite differences elsewhere, disputed kanji, a third dissenting model, manual protection, invalid times, no LLM in Japanese-only mode, ordering before EN, resume and artifact integrity, and Qt comparison/playback. Artifact audit confirmed digests and SRT/report consistency. The rendered Qt dialog was visually checked.

Local artifact root: `D:\models\.cache\benchmark-jp-source-review` (not distributed).

- `comparison.json`: timings and applied decisions.
- Run `54383235f39a4ac4a5933e58f77660da`: manifest, review, export, and provenance.
- Project `projects/33acb427b2be416a9b1e570a97ba829a/project.sqlite`.
- `creator-frame-comparison.json`: sampled visible creator captions versus output.

The JP phrase comparison dialog shows baseline text, final text, alternatives, and decisions. Tooltips contain context and source directories; double-clicking plays the interval. Older manifests retain their original plan. `tools.review_cached_asr` creates a new run from verified cached outputs without inference.

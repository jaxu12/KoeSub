# Audio omission recovery, version 2

New Japanese GGML jobs enable **Recover missed lines • short overlapping audio chunks** by default. An explicit saved off setting is preserved. The full-film --full-jp verifier also enables the stage. Existing manifests keep their stored version and stage plan; the separate native Subtitle Edit XXL/MDX preset remains a distinct workflow.

The previous [short-chunk implementation](SHORT_CHUNK_COVERAGE.md) decoded audio but added no lines in its real probes. It required the auxiliary decoder to produce valid aligned captions before its text could corroborate anything, and rejected additions merged with neighboring captions. Version 2 separates text recognition, phrase extraction, acoustic alignment and selection.

## Automatic processing

1. Scan the complete selected interval with overlapping short Large V3 decodes without VAD. The default is 30 seconds with three seconds of context on each side; quiet boundaries can move the cut slightly.
2. Find whole gap cues and added prefixes/suffixes anchored to existing caption text. Keep crop-edge evidence for a focused retry. Nominal decoder offsets locate search windows; they are not exported as speech timing.
3. Decode each candidate's short context again with the baseline. Ask a distinct auxiliary model to corroborate the text, using the configured third model when the auxiliary fails or disagrees. These text-only calls omit SRT output and forced-alignment requests. Native JSON, token probabilities and unverified offsets remain available.
4. Require an exact, unique normalized phrase in the focused baseline and its corroborator, original baseline token confidence of at least 0.8, and a plausible phrase start. A substring beginning inside a continuous word is rejected. Confidence is a diagnostic threshold, not a calibrated correctness probability.
5. Align the corroborated phrase separately, retaining the focused decoder's surrounding text as acoustic context. Insert only measured positive bounds in a free baseline gap. Existing cue text, times, IDs, translations, comments and manual/reviewed work remain intact.
6. Where internal zero-duration particles cannot receive a supported word timestamp, a whole caption can use measured first/last anchors after the remaining strict alignment checks pass. Internal zero times remain unchanged and are marked incomplete; this mode supplies no invented word boundaries or splitting points.
7. Select a globally non-overlapping set of corroborated insertions, maximizing supported character coverage, then complete word timing, confidence and compact exposure. Contradictory wording at almost identical audio intervals remains unresolved. Other timing conflicts retain their evidence and the selection reason. A conflicting candidate no longer suppresses every neighboring addition.

The final SRT and report include the accepted phrases. **Missing-line candidates** retains alternatives and supports double-click listening. Added text keeps its source punctuation. A brief display hold can extend a new caption beyond the measured speech end within a free gap; the hold and raw word bounds are recorded separately.

No translation or LLM inference is required by this stage. Models run sequentially in batches. Temporary short WAVs are removed after their evidence is saved, while native logs, immutable receipts, source hypotheses and decisions remain. Existing models are read in place without downloading or copying weights.

## Verification and interpretation

Unit and Qt tests exercise merged-prefix/suffix extraction, invalid-offset text decoding, exact context corroboration, word-start guards, partial internal word timing, global interval selection, lexical disputes, source preservation, native output ownership, device failure handling, final exports and replay. Clean-copy tests use synthetic/local fixtures without models or recordings.

The hardware checks use existing CUDA models and audio. Movie comparisons use Subtitle Edit output as an unverified ASR reference. The controls use published FLEURS transcripts; those recordings have not been independently listened to for this experiment. Complete-omission controls deliberately start with an empty baseline. They measure recovery under that setup, rather than natural omission frequency.

The required suite passes **369 tests in 23.01 seconds**. A clean source-only copy without developer data, models or recordings passes the same **369 tests in 24.95 seconds**.

### Fresh movie coverage

Both final probes use unmodified cached baseline captions and fresh coverage inference with the final interval-selection policy. No cues are artificially removed. The first interval was used during development; the second was selected separately for validation.

| Audio | Coverage wall time | Input/output cues | Added phrases | Reference character edits before/after | Exact nearby reference matches among additions |
| --- | ---: | ---: | ---: | ---: | ---: |
| 70 seconds | 54.984 s | 12 / 17 | 5 | 83 → 39 / 156 characters | 5 / 5 |
| 180 seconds | 137.484 s | 16 / 18 | 2 | 285 → 274 / 393 characters | 1 / 2 |

The first run adds 44 normalized characters; the second adds 13. The remaining second-run insertion is corroborated by audio decoders but is not an exact nearby reference match, so its correctness remains unassessed. Reference distance is not an independently measured semantic error count. No independent listening-quality claim is made.

The runs retain two and nineteen unresolved hypotheses respectively. These counts are hypotheses, not verified missing utterances. Timings are single-run observations on an active workstation, not a controlled model-speed comparison.

### Published-transcript and no-speech controls

Three fixed FLEURS validation clips, selected before collection, deliberately start with an empty transcript. Existing local silence and noise controls check spurious insertions.

| Case | Fresh coverage time | Added captions | Emitted normalized characters | Character edits / reference characters |
| --- | ---: | ---: | ---: | ---: |
| FLEURS 33 | 29.110 s | 2 | 36 | 0 / 36 |
| FLEURS 34 | 45.453 s | 1 | 29 | 3 / 32 |
| FLEURS 35 | 47.125 s | 1 | 31 | 34 / 65 |
| Silence | 35.781 s | 0 | 0 | 0 / 0 |
| Noise only | 35.672 s | 0 | 0 | 0 / 0 |

Speech-reference distance totals 37 / 133 characters, versus 133 / 133 for the deliberately empty input. The third speech clip remains substantially incomplete. Neither no-speech case receives an insertion, despite high-confidence hallucinated scan nominations. These are coverage-stage controls, not a claim that the complete baseline pipeline now handles every no-speech file.

The controls have fresh native decoding/alignment evidence from immediately before the final pure insertion-selection fix. Reapplying the final selector to those frozen hypotheses leaves all five text/time outputs unchanged, with zero new native inference processes. That selection replay is reported separately from fresh inference.

Native ASR logs provide CUDA buffer/backend evidence. Standalone alignment has a different log format, so its owned process IDs are correlated separately with NVIDIA telemetry; short processes can fall between two-second samples. Whole-GPU memory includes the desktop.

The final movie probes retain 23 and 48 ASR log entries, all with CUDA evidence; per-clip logs can repeat a grouped process's evidence. NVIDIA observes all four and eight owned ASR processes respectively, plus four of five standalone alignment processes in each run. Whole-GPU peaks are 5,585 and 5,626 MiB; telemetry reports no errors.

All checked movie outputs preserve existing cues exactly, contain unique cue IDs and no invalid times or overlaps, and pass an exact text/time SRT round trip. Source runs, recordings and the main project pointer remain unchanged. Completed evidence replays without new native inference.

## Remaining limits

Exact corroboration leaves some kana/kanji name variants and other spelling disagreements unresolved. The stage recovers whole phrases in free gaps; it does not rewrite existing caption content or move protected times to make room. Recognition errors shared by several models can still survive.

The initial development probe recovered four real gap phrases whose wording also appeared in nearby reference captions. Another candidate remained unresolved because the ASR models spelled a name differently. A separate movie probe exposed an incomplete-word nomination and mutually blocking timing proposals; those findings led to the word-start and global-selection checks above.

Fresh inference, cached evidence reselection and independently assessed accuracy are distinct. The reselect_verified function in tools/verify_chunk_coverage.py evaluates a new insertion selection over immutable native evidence, with zero new ASR processes and a separate output directory. It must not be reported as fresh GPU transcription or an inference speed improvement.

No complete-film trial of this version or guarantee of eliminating every omission is claimed.

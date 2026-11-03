# Short-chunk coverage search

This document records the initial version and its historical probes. Current jobs use [omission recovery version 2](OMISSION_RECOVERY_V2.md), enabled by default for new Japanese GGML runs, with separate text corroboration, focused alignment and global insertion selection. Explicit saved off settings and existing version-1 manifests are preserved.

The Japanese workflow can search for whole lines missing from baseline gaps. Existing retry selection mostly starts from existing cues; a completely missing utterance may have no low-confidence cue to select. This optional stage scans the entire selected audio range instead of relying on the existing cue list.

## Historical version-1 controls and behavior

Enable **Search for missed lines • short overlapping audio chunks (experimental)** in the Japanese pipeline. Select 15–120 seconds per chunk; the initial value is 30 seconds. Settings are saved per project. It is initially disabled, and old manifests retain their original plans. The separate native Subtitle Edit XXL/MDX preset does not support this stage yet.

The additional `asr-coverage` stage runs after baseline timing repair and before the existing auxiliary scan and phrase review:

1. Partition the entire selected interval. Prefer a quiet core boundary within two seconds of each target cut; include three seconds of context on both sides. Quiet energy boundaries are hints, not verified speech detection.
2. Decode every short window with GGML Large V3 **without VAD**. This changes audio context and checks regions VAD might discard. It can also hallucinate speech over silence or music.
3. Nominate complete decoded cues in baseline gaps, including the head and tail of the interval. Leave 200 ms around existing cues and reject nominations touching an interior crop edge. Core boundaries never trim subtitle text or timestamps.
4. Decode only windows containing nominations with the selected auxiliary model. If its output fails quality checks, use the configured third model, if available. Device/memory failures still propagate.
5. Add an isolated line only when distinct model weights agree on normalized text, complete cue times overlap sufficiently and differ by at most 750 ms at each end, and baseline token-confidence mean is at least 0.8. Confidence is not a calibrated correctness probability. Preserve the baseline decoder's verbatim text and bounds.
6. Deduplicate overlap nominations by both text and time. Preserve separate genuine repetitions. Conflicting overlapping hypotheses remain unresolved. Existing cues, manual work and timestamps survive exactly.

Added lines are marked for listening. **Missing-line candidates** shows proposals, nearby peer text and decisions, with double-click playback. Reports retain hypotheses, rejected outputs, model paths, parent IDs, source directories and insertion records. Candidates and rejected windows keep the run in `needs_review`; rejected outputs may represent silence, so their count is not an error count.

At most eight temporary short WAVs are prepared per batch. They are removed after evidence is saved; native logs and immutable receipts remain. Models run sequentially, with one load per pending batch. No downloads or full-film duplicate WAVs are required. Changed audio, models, settings or receipt contents invalidate replay.

## Verification on 2026-11-03

Twenty-two synthetic/local coverage cases test interval coverage, offsets, quiet cuts, crop edges, head/tail gaps, preservation of human work, corroboration, confidence, duplicates versus repeated speech, conflicts, auxiliary-quality fallback, fatal CUDA errors, tamper detection, replay, validation and final pipeline/export integration. Existing Qt tests cover controls and saved settings. The complete suite passes 351 tests in 17.36 seconds, and a clean source-only copy passes in 19.44 seconds. Hardware inference is separate from unit tests.

Two fresh CUDA probes used the same 70-second interval of an existing local recording and an immutable cached baseline. One whole baseline ASR cue was removed in an isolated copy as a controlled gap probe. That removed cue is an ASR hypothesis, **not independently verified truth**. No reference subtitles entered inference.

| Setting | Windows | Fresh coverage wall time | Nominations | Added lines | Rejected clip outputs | Masked ASR wording restored |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 30-second cores, 3-second context | 3 | 24.140 s | 5 | 0 | 1 | No |
| 15-second cores, 3-second context, third-model fallback available | 5 | 46.516 s | 2 | 0 | 2 | No |

The second probe used the new fallback; the first predates it. These are development probes, not a controlled chunk-size quality benchmark. An initial verification-driver error occurred after native decoding and before parsing; its separate directory was preserved and is excluded above. Corrected probes use new directories and fresh coverage decoding.

All retained ASR logs in the completed probes contain actual CUDA buffer/backend evidence. NVIDIA telemetry observed both native process IDs in the 30-second probe and all three in the 15-second probe. Whole-GPU peaks, including desktop use, were 5,522 and 7,049 MiB respectively, not model-only memory. Telemetry reported no errors. Both probes replay identically without new native processes and preserve the source run, audio and main project pointer.

Shorter decodes sometimes contain the masked ASR wording, but crop-edge or neighboring-caption overlap guards prevent insertion. Auxiliary and fallback alignment rejection also prevents corroboration. **This verifies execution, provenance and safe rejection, not a demonstrated reduction in omissions.** No full-film run of this option or independent quality gain is claimed.

## Limits and next measurement

This stage recovers only complete isolated cues in gaps. It does not split a candidate crossing an existing caption, infer words inside a caption, trim neighboring timings, repair poor alignment by guessing, or let an LLM invent dialogue. Models can share hallucinations or omit the same quiet speech. Smaller chunks can lose context; more nominations are not necessarily more real speech.

The next quality step is checking genuinely omitted utterances against audio, then evaluating token/word-aligned insertion across caption boundaries. Automatically inserting overlapping text before that evidence exists risks duplicates and incorrect times. The option remains off by default.

To reproduce a probe using an existing completed run:

```powershell
.\.venv\Scripts\python.exe -m tools.verify_chunk_coverage `
  --source-manifest D:\models\.cache\existing-run\run\manifest.json `
  --output D:\models\.cache\new-coverage-probe `
  --start-ms 215000 --end-ms 285000 --chunk-seconds 30
```

The source must have cached 16 kHz mono audio, a valid baseline and a CUDA configuration. Optional `--hide-cue-index` masks one ASR cue for an integration probe. Existing output directories are rejected to protect prior evidence. Audio, transcripts, masked text and diagnostics stay outside Git.

# KoeSub development notes

This document summarizes prototype behavior and historical implementation decisions. Start with [README.md](README.md) for setup, [STATUS.md](STATUS.md) for current priorities, and the individual benchmark reports for measurements. Earlier test counts in historical reports describe those stages, not the current suite.

## Editing and persistence

The native PySide6 editor supports video/audio import, audio-track selection, subtitle playback, JP/EN editing, merging, splitting, and undo/redo. Edits are committed before navigation or jobs; invalid draft times block navigation rather than discarding input. Projects use SQLite with stable cue IDs, parent provenance, original imports, annotations, and job records. Session undo/redo is separate from persisted save history.

Waveforms are decoded by FFmpeg in a separate process and stored as compact 50 Hz peaks, avoiding a second full WAV. Dragging selects an ASR/pipeline interval. Search covers JP, EN, timing, and notes. Filters include warnings, unreviewed cues, bookmarks, and missing translations.

Import supports UTF-8 SRT/ASS/SSA, with explicit CP932 fallback after encoding failure. Export supports SRT, ASS, SSA, and timestamped TXT. ASS/SSA input styling is not preserved. Partial EN cannot silently disappear during merges. Technical timing proposals and optional estimated splits are marked for listening; they are not audio alignment.

## ASR and model storage

Adapters validate flags and supported backends against the selected executable. Whisper GGML and Qwen ASR use CrispASR; Faster Whisper XXL is optional. The tested XXL release expects a model name plus an existing parent directory rather than a full model path. Output validity is checked independently of exit status.

GPU selection is explicit. Device, allocation, configuration, and file failures stop the task. A configurable policy can reject unusable ASR alignment while continuing with other hypotheses; all failures and durations remain in the report. All rejected hypotheses are excluded from later selection. Models are read from configured paths, without duplication. The GUI does not download weights.

Japanese-only jobs run Large V3 with VAD and optional audio retries. The current local phrase review is documented in [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md). Older full-window consensus remains in historical artifacts and old resumable plans.

## Full translation pipeline

Full pipelines support configurable ASR and EN variants. Whole-cue ASR selection preserves existing timestamps and uses a compatibility pass to avoid overlaps created by combining alternatives. If no complete combination is valid, one coherent source track is retained. A separate source review stage precedes context and EN generation in new jobs.

The optional embedded Qwen3 Instruct translation backend uses llama.cpp. LM Studio remains secondary. Different prompts for one model are not independent models. Translation cache identity includes relevant context and configuration. Manual EN is protected.

Candidate EN repairs are generated from JP and checked separately against the source. Only confirmed candidates can be applied automatically; ambiguous suggestions remain for review. Whole-film context is derived from available JP, with separate chunk summaries and hierarchical aggregation where needed. It is a hypothesis, not an independent transcript or permission to invent dialogue.

## Runtime ownership and recovery

The app runs one heavy task at a time. Owned Windows child jobs close model processes on cancellation, failure, or worker termination. Full pipelines can lazily start an owned offline loopback LLM server and keep its model across requests. Missing server support falls back to CLI inference. Japanese-only mode does not start the LLM.

Checkpoint JSON uses atomic writes and bounded retries for transient Windows read/replace conflicts. Invalid JSON and permanent access denial remain errors. Source hashes, model/runtime identities, and completed artifact digests protect resume. Manual edits to processing inputs require a new run unless the pipeline explicitly paused for review.

Cleanup offers recognized rebuildable audio/waveform caches, not models, projects, logs, or checkpoints. Missing audio cache can be recreated without rerunning completed inference. Free-space reserves are enforced; a total cache-size cap is not yet implemented.

## Shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+F / F3 / Shift+F3 | Search / next / previous result |
| F8 / Shift+F8 | Next / previous problem |
| Ctrl+Enter | Apply editor fields |
| Ctrl+Shift+Enter | Mark selected cues reviewed |
| Ctrl+M / Ctrl+Shift+M | Bookmark / note |
| Ctrl+L | Play selected cue |
| Ctrl+Shift+T | Preview timing shift |
| Ctrl+Shift+F | Preview common repairs |
| Ctrl+O / Ctrl+I / Ctrl+Shift+S | Open project / import media / save as |

## Remaining limitations

No speaker diarization, voice separation, audio-based automatic resynchronization, complete advanced ASR profiles, dedicated TranslateGemma adapter, multi-recording job queue, full historical-revision browser, in-app GPU telemetry, total cache limit, or packaged EXE. The UI still has Polish labels; repository documentation is English. Text-model review does not listen to audio. Current quality must be checked on the intended material.

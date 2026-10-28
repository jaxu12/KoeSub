# Original specification review

This English summary records the prototype's implemented scope and remaining gaps. The original working title was AI Subtitle Studio. Subsequent decisions prioritize Japanese source transcription, an embedded local GGUF backend for optional translation, LM Studio as secondary, and explicit model/cache locations.

## Implemented

- Native PySide6 media editor, audio-track selection, video playback, and 50 Hz waveforms.
- Search, warning/unreviewed/bookmark filters, keyboard navigation, notes, and persistent review annotations.
- Draft validation before cue navigation and tasks; invalid timing does not discard edits.
- Previewable whitespace, limited timing, cue merge/split, and timing-shift operations with undo and provenance.
- Partial-translation protection during merges and conservative handling of speaker markers; no claim of diarization.
- Standalone AI proposals, source-faithfulness checks, optional confirmed application, before/after records, and undo.
- Optional full-pipeline review pauses with auditable manual checkpoints and resumed downstream work.
- SRT/ASS/SSA import and SRT/ASS/SSA/TXT export; source ASS/SSA styles are not retained.
- Drag-and-drop media/subtitles/projects, recent projects, timeouts, and process cancellation.
- Controlled rebuildable-cache cleanup without offering models, projects, logs, or checkpoints for deletion.
- Japanese-only baseline/retries and a separate local source-phrase review before translation in new jobs.

## Scope and gaps

| Area | Current scope and limits |
|---|---|
| Import / playback | Available; ASR language remains Japanese |
| Waveform | Available; does not replace a spectrogram or forced alignment |
| ASR runtimes | Explicit CLI adapters and backend validation; quality depends on model conversion/alignment |
| Advanced ASR profiles | Partial presets/VAD options; not every advanced decoding parameter is exposed |
| Voice separation / denoising | Not implemented |
| Source comparison | Time-based 1:N/N:1 grouping, manual/AI whole-cue choice, and local corroborated phrase review; large offsets still need attention |
| Retiming | Technical proposals only; no general audio-based resynchronization |
| Translation | Local Qwen3 Instruct and optional LM Studio; no dedicated TranslateGemma/native Qwen3.5 adapter |
| Semantic review | Available, but a text-model judgment rather than audio ground truth |
| Pipeline | Resumable stages for one recording; no multi-recording queue |
| History | SQLite, original sources, IDs, parent provenance, checkpoints; no complete historical revision browser |
| Resources | Sequential heavy tasks, explicit backends, child ownership, free-space reserves; no total cache cap or in-app GPU/RAM telemetry |
| Distribution | Python environment and Windows launchers; no packaged EXE |
| Language | English public documentation; English UI localization remains planned |

An earlier review phase had 86 passing tests and separate FFmpeg/model checks. The current suite is described in [TEST_REPORT.md](TEST_REPORT.md). Suggested next work includes broader independently audited references, better source selection, cheaper ASR retries, audio-aware alignment, and later translation quality improvements.

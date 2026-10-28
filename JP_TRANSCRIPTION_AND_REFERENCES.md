# Japanese transcription, retries, and references — 2026-10-28

New projects default to Japanese-only transcription. Translation, English review, LM Studio, and embedded LLM inference are skipped. Exports contain JP and a report. Existing full-pipeline configurations remain available.

**Current update:** new runs include local JP phrase review before translation. The strict whole-window decision described in the historical test below is superseded for new jobs. Replaying its cached results produced two edits in one cue without retiming; see [JP_SOURCE_REVIEW.md](JP_SOURCE_REVIEW.md).

## Targeted audio retries

1. Large V3 + VAD supplies the baseline; auxiliary models cannot replace it by unsupported text voting.
2. Low token confidence, repetition, and punctuation-only cues identify suspicious intervals. Current confidence thresholds are a mean below 0.78 or at least 20% of tokens below 0.4. These are risk signals, not proof of error.
3. Windows include three seconds of context before/after by default, expand to whole neighboring cues, and do not overlap. The default maximum window is 30 seconds, with up to 12 windows per run.
4. Each window is decoded again by Large V3 and an auxiliary model, normally Kotoba. Experimental Qwen JA Anime/Galgame, Anime-Whisper, and ReazonSpeech profiles are available. Models run sequentially with explicit device selection.
5. Raw hypotheses, durations, rejections, and logs are retained. Changed source text, window boundaries, attempts, or completed decisions invalidate resume.
6. Manual/reviewed text is protected. JP layout wraps lines without retiming baseline cues.

The old policy required two complete retry windows to agree with preserved boundary context. The current phrase policy compares smaller corroborated units while preserving unresolved baseline text.

## Historical full-recording retry test

Easy Japanese 1: 282.73 seconds, CUDA.

| Stage | Duration |
|---|---:|
| Cached audio | 0.00 s |
| Large V3 + VAD | 52.56 s |
| Nine windows, two retries each | 252.50 s |
| JP layout / export | 0.02 / 0.03 s |
| Total wall time | 305.984 s |

The original result had 98 cues, three tracks, and 35 warning-bearing cues. **Zero whole-window replacements** passed the old conditions. This verified detection and retries, not an accuracy improvement. Repeated ASR loading accounts for part of retry cost; ASR models are not yet kept loaded across windows.

Local run ID: `841464cecf4343fa9f1217ed29d341fc`; benchmark root: `D:\models\.cache\benchmark-jp-retry`. Artifacts are not included in Git. GUI, SQLite, stage digests, and exported JP SRT were audited.

## Reference bank

Thirty disjoint clips were prepared from the existing MCDC recording and Japanese SRT: **599.802 seconds of FLAC, approximately 18.59 MiB**. Audio is shared by ASR and review examples.

- 19 clips are marked `development`, 11 `control`.
- The fixed first-five-clip comparison core contains 22 reference cues and 408 normalized characters.
- All clips come from **one recording**. They are time-disjoint, not source- or speaker-independent.
- Community captions were not manually audio-verified. Labels retain `human_audio_verified: false` and `training_ready: false`.

ASR receives audio only. Reference text is used after decoding. CER uses Unicode normalization and removes punctuation/spacing, without equating kanji and kana. It measures differences from community captions, not certain audio error or translation accuracy. Repeated tuning on control results consumes the independence of that split; broader evaluation needs more held-out recordings.

## Review and training preparation

The bank contains 30 audio/JP ASR pairs, 30 unchanged review cases, 30 explicitly synthetic repetition cases, and five real Large V3 outputs. Real ASR/SRT differences require label audit rather than automatic assignment as model errors.

There are **65 input-only review records** and **65 separate labels**. Labels must not be passed to the evaluated model. Clean examples also measure unnecessary edits. A text LLM does not hear the audio.

**No model weights have been fine-tuned.** Before training, the labels need review and the dataset needs broader coverage. Inference GGML/GGUF files are not a ready-made training environment.

Local bank root: `D:\models\datasets\subtitle-studio-references-v1`, including `index.json`, `asr_examples.jsonl`, `review_inputs.jsonl`, `review_labels.jsonl`, and `review_real_asr_examples.jsonl`. These files are excluded from the repository.

## Five-clip CUDA model comparison

No reference text was supplied to ASR as a prompt.

| Model in the tested runtime | Core CER | Valid timing |
|---|---:|---:|
| Large V3 | 6.62% | 5/5 |
| Kotoba + aligner | 10.78% | 5/5 |
| ReazonSpeech NeMo v2 FP16 GGUF | 27.94%, text only | 1/5 |
| Anime-Whisper FP16 GGML | No comparable complete score | 3/5; one invalid UTF-8 result |

Text scoring is separate from timing validity. Reazon produced readable text in all five trials but zero-duration cues in four. An additional shorter-window/aligner test did not resolve the problem. Anime's corrupt text prevents a complete comparable CER. These are small-sample results for particular conversions and runtimes, not a universal ranking of the original Python models.

- [Reazon conversion](https://huggingface.co/cstr/reazonspeech-nemo-v2-GGUF): one 1,240,435,584-byte FP16 GGUF; no NeMo/PyTorch environment was installed. Experimental.
- [Anime GGML conversion](https://huggingface.co/Aratako/anime-whisper-ggml): its author documents text corruption, also observed here. It does not replace Kotoba. The [original model](https://huggingface.co/litagin/anime-whisper) is a separate artifact; no initial prompt was used.
- [Qwen3-ASR JA Anime/Galgame conversion](https://huggingface.co/cstr/qwen3-asr-1.7b-ja-anime-GGUF): the existing 2,506,725,376-byte Q8 file was reused. Verified SHA256: `f173ceddb15b59177575a101491862bd362cd85f2e7a6bac811fbc53411596a1`.
- [Kana-Whisper](https://huggingface.co/sbintuitions/kana-whisper): outputs katakana pronunciation rather than ordinary mixed-script subtitles. Investigated but not downloaded.

Historical tests at this stage numbered 138. The later phrase-review suite reached 156. Model weights, recordings, and caches stayed on the configured data drive, and the main user project was preserved.

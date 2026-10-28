# Local runtime and model setup

KoeSub uses local model files and external runtimes. The paths below describe the development machine as of **2026-10-28**, not a required installation layout. Choose your own storage drive and configure the paths in the app.

## Tested CUDA runtimes

- CrispASR v0.8.45: `D:\models\.runtime\crispasr-v0.8.45-cuda13\crispasr-windows-x86_64-cuda13\crispasr.exe`.
- llama.cpp b11935: `D:\models\.runtime\llama-b11935-cuda13\llama-completion.exe`, with `llama-server.exe` alongside it.
- FFmpeg from an existing local installation.

The tested machine has an RTX 5060 with 8 GB VRAM. Actual ASR and LLM logs confirmed CUDA inference. Runtime receipts record source releases and checksums. Earlier Vulkan installations remain available, but subsequent hardware experiments use CUDA only. The app must use a backend supported by its selected runtime; it does not silently recover a GPU failure by switching to CPU.

## Model files

All weights on the development machine live under `D:\models`; there is no duplicate Hugging Face model cache on the system drive.

| Purpose | Relative path under the model root | Approximate size |
|---|---|---:|
| Baseline Whisper Large V3 FP16 | `whisper/ggml-large-v3.bin` | 2.88 GiB |
| Auxiliary Kotoba v2.0 FP16 | `whisper/ggml-kotoba-whisper-v2.0.bin` | 1.42 GiB |
| Experimental Qwen3-ASR JA Anime/Galgame Q8 | `asr/qwen3-asr-1.7b-ja-anime-q8_0.gguf` | 2.33 GiB |
| Qwen forced aligner | `asr/qwen3-forced-aligner-0.6b-q8_0.gguf` | 0.92 GiB |
| Silero VAD | `asr/ggml-silero-v6.2.0.bin` | 0.84 MiB |
| Optional translation / review LLM | `lmstudio-community/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | 2.33 GiB |

Kotoba and the experimental Anime-Whisper profile require the explicitly configured local aligner. The tested Qwen ASR conversion has had alignment failures on some recordings. ReazonSpeech and the Anime-Whisper GGML conversion remain experimental; see [the model comparison](JP_TRANSCRIPTION_AND_REFERENCES.md).

## Configuration

1. Point the app at FFmpeg and the selected ASR executable, weights, VAD, and aligner.
2. Choose CUDA only when supported by that executable. CPU use is an explicit choice; VAD can use CPU independently of the main model.
3. Set the cache directory to a drive with sufficient free space, such as `D:\models\.cache`. Existing recordings stay in place.
4. Start with 20–60 seconds of audio and inspect both text and timing.
5. For optional translation, select the embedded GGUF backend and the llama.cpp executable. LM Studio is a separate secondary option.

When a compatible sibling `llama-server.exe` exists, full translation pipelines start an owned loopback-only session lazily after ASR, keep the model loaded across requests, and close it at the end. Otherwise, the CLI fallback remains available. Japanese-only pipelines never start this LLM session. Models loaded manually in an external server must be released there before ASR if VRAM is limited.

Settings are local in `data/settings.json` and are excluded from Git. Existing download receipts and dataset directories may still use the historical `subtitle-studio-*` names; these are retained for compatibility and do not trigger duplicate downloads.

## Download sources

The GUI does not download models. Separate, explicit `tools/fetch_*.py` utilities check storage and source metadata. Inspect their paths before running them on a new machine.

- [Whisper GGML](https://huggingface.co/ggerganov/whisper.cpp)
- [Kotoba v2.0 GGML](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0-ggml)
- [Qwen3-ASR JA Anime/Galgame conversion](https://huggingface.co/cstr/qwen3-asr-1.7b-ja-anime-GGUF)
- [Qwen forced aligner conversion](https://huggingface.co/cstr/qwen3-forced-aligner-0.6b-GGUF)
- [Silero VAD](https://huggingface.co/ggml-org/whisper-vad)
- [Qwen3-4B Instruct GGUF](https://huggingface.co/lmstudio-community/Qwen3-4B-Instruct-2507-GGUF)
- [CrispASR v0.8.45](https://github.com/CrispStrobe/CrispASR/releases/tag/v0.8.45)
- [llama.cpp b11935](https://github.com/ggml-org/llama.cpp/releases/tag/b11935)

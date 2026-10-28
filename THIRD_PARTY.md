# Third-party dependencies and materials

The [MIT License](LICENSE) applies to KoeSub's original code and documentation. It does not automatically cover dependencies, external programs, model weights, or test recordings.

## Python dependencies

Versions are listed in `requirements.txt` and `requirements-dev.txt`. Metadata from the installed development environment reports:

| Package | License reported by package metadata |
|---|---|
| PySide6 Essentials and Addons / Qt for Python | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| pysubs2 | MIT |
| httpx | BSD-3-Clause |
| pytest, for testing | MIT |

Full terms and component notices are supplied by the corresponding distributions. Qt components have their own license files; this table does not replace them. This repository does not contain those libraries or a bundled application distribution.

## Runtimes and models

KoeSub can use [CrispASR](https://github.com/CrispStrobe/CrispASR), [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [llama.cpp](https://github.com/ggml-org/llama.cpp), [FFmpeg](https://ffmpeg.org/), an existing Subtitle Edit installation, and optional LM Studio. These programs are installed separately and retain their own terms and attribution. FFmpeg licensing also depends on the build used.

Whisper, Kotoba, Qwen, Anime-Whisper, ReazonSpeech, and their conversions have separate model cards and licenses. Download utilities and setup documentation identify their sources. Check the exact version's terms before use or redistribution. KoeSub's MIT license does not change a model's license.

## Test materials

The synthetic `samples/japanese_a.srt` and `samples/japanese_b.srt` examples belong to this project. Test videos, audio, reference subtitles, and external datasets are not included. Their sources are documented in the experiment reports and `samples/` notes. Using material in an experiment does not place it under the MIT license.

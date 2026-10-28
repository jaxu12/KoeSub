# External test media

Media files are excluded from Git. Source attribution here does not imply an endorsement of KoeSub.

## Job Interview

- Author: [Simpleshow Japan](https://commons.wikimedia.org/wiki/User:Simpleshow_Japan), 2017-04-20.
- [Source](https://commons.wikimedia.org/wiki/File:Job_Interview.webm), [original file](https://upload.wikimedia.org/wikipedia/commons/e/ec/Job_Interview.webm).
- License recorded by the source: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- Japanese educational animation about preparing for an interview; 188.6 seconds, 854×480, VP8/Opus.
- Original size: 16,807,115 bytes; SHA-1 `628f841a1c2a61bf25948da346981dfc393b3040`.
- Local path after explicit acquisition: `samples/media/Job_Interview.webm`.

`python -m tools.fetch_test_media` explicitly fetches this file, checks its checksum and storage reserve, and caps acquisition at 25 MiB. It does not download models. Source video is retained unchanged; extracted audio and machine captions are separate artifacts.

Start with a short interval, listen, and check omissions, invented text during silence, timing, and cutoff speech. Narration does not replace tests of fast dialogue, overlapping voices, or music. Full experiments are in [BENCHMARK_REPORT.md](../BENCHMARK_REPORT.md).

## Sisters of the Gion: difficult live-action audio

[Sisters of the Gion / 祇園の姉妹 (1936)](https://commons.wikimedia.org/wiki/File:Sisters_of_the_Gion_(1936)_by_Kenji_Mizoguchi.webm), directed by Kenji Mizoguchi. The recorded Commons source identifies PD-Japan-film / PD-1996 public-domain status.

Only the first 12 MiB of a 240p copy was acquired; the approximately 1.62 GB full original was not downloaded. A **02:00–04:00** excerpt was retained. Video was converted to H.264; baseline Opus audio was copied from the distributed Wikimedia version. This is not audio from an original film master.

- `media/Sisters_of_Gion_02m00_04m00.mkv`: baseline, approximately 1.93 MiB.
- `media/Sisters_of_Gion_02m00_04m00_noisy.mkv`: deliberately degraded copy, approximately 1.89 MiB; 250–3400 Hz band, speech gain 0.7, seeded pink noise, AAC 64 kb/s.
- `media/gion-source.json`: exact source URLs and processing parameters.

The noisy version must not be described as original film audio. Compare identical ASR settings on both clips after listening to them; age alone does not establish a recording's difficulty. No matching reference SRT has been confirmed.

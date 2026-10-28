# Recordings with existing subtitles

These notes identify external reference candidates, not bundled media. See each source for attribution and reuse terms. Community captions and OCR are not automatically error-free ground truth.

## Street interviews with burned-in captions

[Easy Japanese 1 — Typical Japanese](https://www.youtube.com/watch?v=qzzweIQoIOU), Easy Languages, approximately 4:43, contains interviews with several people in Sendai and JP/romaji/EN captions. It was first identified from a small preview and later acquired at usable resolution for the experiment in [EASY_JAPANESE_TEST.md](../EASY_JAPANESE_TEST.md). No complete independent SRT was obtained. The experiment used twelve initial caption frames and one targeted additional frame, without whole-film CER.

## Meeting video with JP/EN SRT

[MCDC Onboarding “Ask me Anything” — Japanese language](https://commons.wikimedia.org/wiki/File:MCDC_Onboarding_%22Ask_me_Anything%22_session_-_Japanese_language.webm), 23:10, is a real meeting recording. Local test assets are under `D:\models\test-media\mcdc-japanese`: `MCDC-Japanese-23m-240p.webm`, `reference.ja.srt`, `reference.en.srt`, and source revision/attribution metadata in `source.json`.

The published captions permit text/time comparison, but they were not independently audio-audited. See [BENCHMARK_REPORT.md](../BENCHMARK_REPORT.md) and [JP_TRANSCRIPTION_AND_REFERENCES.md](../JP_TRANSCRIPTION_AND_REFERENCES.md) for limited-interval and five-clip comparisons.

The earlier Sisters of the Gion clip has no confirmed matching SRT and showed no captions in the inspected frame. It is a difficult-audio sample, not a ready reference dataset.

# Repository instructions

The product name is **KoeSub**. Keep the existing `studio` Python package and historical local receipt/cache names compatible with existing projects.

Write all public repository prose in **English**: README content, documentation, issue descriptions, and pull request descriptions. Do not add Polish-language documentation. Preserve Japanese transcript examples in their original language.

Do not commit model weights, native runtimes, recordings, private projects, user settings, or generated caches. Preserve manual subtitle edits, timestamps, source hypotheses, and decision provenance when changing ASR/review behavior.

Run `.\.venv\Scripts\python.exe -m pytest -q` for relevant behavior changes. Unit tests use synthetic/local fixtures and do not require model downloads or GPU inference. Distinguish cached-result replay, integration success, and independently measured transcription quality in reports.

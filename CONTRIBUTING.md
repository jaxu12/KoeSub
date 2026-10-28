# Contributing to KoeSub

We are building a local tool for Japanese transcription and subtitle review. The current priority is source-transcript accuracy, useful comparisons between ASR hypotheses, and preservation of timing and manual edits.

**Repository language:** Write READMEs, documentation, issue descriptions, and pull request descriptions in English. Preserve Japanese examples in their original language. Do not introduce Polish-language documentation.

## Working on the code

1. Set up the environment from [README.md](README.md) and install `requirements-dev.txt`.
2. Create a branch, for example `git switch -c improve-asr-review`.
3. Describe the concrete problem and intended behavior. Validate behavior changes with appropriate checks.
4. Run `.\.venv\Scripts\python.exe -m pytest -q` and report the result with your change.

The app and pipeline are in `studio/`, tests in `tests/`, and diagnostic and hardware-verification utilities in `tools/`. Small synthetic examples live in `samples/`. The Python package remains named `studio` for compatibility; the product is KoeSub.

Preserve raw ASR results and decision provenance. Do not overwrite manually edited text or treat model agreement as audio ground truth. Separate pipeline integration checks from quality evaluation against an independent reference. For hardware experiments, record the model, runtime, backend, recording length, elapsed time, and use of caches.

## Reporting a bug

Include your Python version, OS, GPU, model and runtime, reproduction steps, and expected and actual behavior. Share a short log excerpt with private paths and data removed. A short audio excerpt and a reference transcript help with ASR issues when you have permission to share them.

Do not commit model weights, recordings, caches, user settings, or private project databases. Check `git status` and `git diff --cached` before committing. Respect the licenses of external materials.

Contributions to original project code and documentation use the project's MIT license. Preserve attribution and licensing notices when adding third-party code.

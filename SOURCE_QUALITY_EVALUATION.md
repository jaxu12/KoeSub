# Source-quality evaluation and reference listening

KoeSub's **Source quality** tab measures transcription quality separately from the production pipeline. It compares the frozen baseline and after-review transcript for the same prepared audio clip. The evaluator performs no inference, downloads no models, and never sends reference text to an ASR or review model.

## Two kinds of evidence

Automatic diagnostics report character substitutions, deletions, insertions and weighted CER. The existing normalization remains unchanged: Unicode NFKC and case folding, with punctuation, symbols, spacing and selected non-speech labels removed. Kanji and kana are not treated as equivalent. A character deletion is not automatically an omitted utterance, and different spelling is not automatically changed meaning.

Content errors require explicit listening assessments. The workbench supports these primary categories:

| Category | What to record |
|---|---|
| Omission | Spoken content missing from the hypothesis |
| Addition | Hypothesis content that was not spoken |
| Name | Incorrect person, place, title or other named entity |
| Meaning | Another change to a fact, negation, intent or relationship |
| Orthography | Spelling or script differences with preserved meaning |
| Timing | A cue presented at an incorrect time |

Each event has one primary category, a minor/major/critical severity, exact reference/hypothesis quotes and an explanation. These are reviewer events, not automatically inferred word errors. Spelling-only events do not contribute to the semantic-event count.

## Listening workflow

1. Open **Source quality** and create a study from a reference index and completed results, or open an existing study.
2. Select a clip and enter your reviewer name or ID. Use **Listen to clip** to play its audio independently of the active subtitle project.
3. Check the reference against the recording. ASR text is masked during an unverified reference audit by default, to reduce copying the hypothesis into the reference. The mask can be disabled for provisional comparison; this is not a fully blinded research protocol.
4. Correct the reference if necessary, explain the check or correction, explicitly attest listening, and save the reference audit.
5. Select **Baseline ASR** or **After review**, select relevant quotes and add error events. Added/deleted events are saved as a draft. Explicitly complete listening review for that variant and save the assessment.
6. A completed assessment with no events records a checked, clean clip. An unassessed clip never counts as error-free.
7. Export a JSON report and its Markdown table. Category comparisons use only clips completed for **both** variants with an audio-audited reference.

Every imported reference starts unverified, even if the dataset has a human_audio_verified flag. Verification in this study is an explicit user attestation, not an automatic certification. A single reviewer can miss mistakes or introduce bias; the tool does not claim independent reviewers, speaker independence or annotation consensus.

## Coverage and preservation

Reports distinguish available model outputs, audio-audited references, completed variant assessments and paired comparisons. Null / **Not assessed** means there are no qualifying listening assessments. Missing outputs do not silently disappear from the expected-case denominator; complete CER stays unavailable until all expected outputs are present, while partial CER is labeled as such.

Paired effects compare primary semantic-event counts on the same clips. They do not rank the severity of all possible meaning changes. Unpaired observations remain in the report with their separate coverage and do not enter paired category counts.

Published reference text, raw hypothesis text, cue times, source artifact digests and audio hashes are retained. Reference corrections affect only the study; prior assessments are preserved in history and invalidated for the new text. Changes to frozen evidence or stale assessment keys are rejected. Audio identity is checked before playback and listening attestation. Study saves use a file lock and reject stale writes from another editor.

An unsaved reference text/audit draft blocks clip changes, opening another study and closing the application until it is saved or discarded. Quality reports cannot overwrite the study, input index/results, source audio or completed run folders. No evaluation action modifies production tracks, manual subtitle edits, timestamps or native ASR receipts.

## CLI and prepared inputs

The index describes **complete prepared audio clips**, at most ten minutes each. Audio playback and run times are clip-relative, starting at zero; original source_range_ms is retained as provenance.

Required sample fields:

~~~json
{
  "samples": [{
    "id": "clip-01",
    "audio": "D:/evaluation/clip-01.flac",
    "audio_sha256": "SHA256_OF_THE_AUDIO",
    "source_range_ms": [10000, 25000],
    "reference_jp": "日本語の参照字幕です。"
  }]
}
~~~

The results file maps IDs to existing pipeline manifests:

~~~json
{"records": [{"id": "clip-01", "manifest": "D:/evaluation/run/manifest.json"}]}
~~~

The v3 reference benchmark's reference-summary.json already has this mapping. Missing mappings remain missing-output cases. Completed stage JSON and its digest are verified; installing the old model weights or runtime is not required to evaluate frozen results.

~~~powershell
.\.venv\Scripts\python.exe -m tools.evaluate_source_quality create --index D:\models\datasets\koesub-fleurs-ja-v3\index.json --results D:\models\.cache\verification-source-v3-references\reference-summary.json --out D:\models\.cache\source-quality-v1\fleurs-study.json
.\.venv\Scripts\python.exe -m tools.evaluate_source_quality report D:\models\.cache\source-quality-v1\fleurs-study.json --out D:\models\.cache\source-quality-v1\fleurs-report.json
~~~

Paths describe the development machine; prepared media, studies, annotations and reports are private local artifacts excluded from Git.

## Recorded verification — 2026-10-28

An offline study was prepared from the five existing FLEURS Japanese validation clips, rows 10–14, and their completed v3 baseline/review artifacts. Both variants have **6/257 character differences (2.33% CER)**. All five outputs are available. There are **zero audio-audited references and zero completed semantic assessments in this newly prepared study**, so omission, addition, name and meaning totals remain **Not assessed**. The evaluator does not turn existing text labels or an automated playback check into a gold reference.

This is a cached-result evaluation, not fresh model inference or a new quality gain. UI playback advanced past 250 ms on a real 17.46-second FLAC clip; its study bytes remained unchanged. This verifies playback integration only. The workflow still requires actual listening and category annotation before content-quality conclusions can be drawn.

Synthetic tests cover false verification claims, missing-output coverage, clean versus unassessed clips, spelling versus meaning, matched assessment cohorts, stale evidence, reference correction history, audio identity, concurrent saves, protected exports, independent project state, default masking and unsaved draft protection. Existing CER benchmark imports remain compatible.

The complete suite has **231 passing tests**, also verified on a clean source-only copy without developer recordings, settings or models (13.89 seconds in the recorded clean run). These tests validate the measurement workflow; they do not establish a new transcription-quality score.

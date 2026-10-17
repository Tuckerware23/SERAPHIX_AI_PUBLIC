# Seraphix public source review

This is a proposed sanitized source release for architecture and code review.
It contains no manuscript, canon database, conversation history, index, credentials,
model weights, portraits, generated audio, or private evaluation data. Fictional
passages in tests are synthetic. This package has not been published.

## Architecture

- seraphix_app.py: CustomTkinter GUI, worker queues, chat history, model calls,
  optional portraits, and interruptible speech subprocesses.
- seraphix_manuscript_library.py: DOCX/TXT/PDF import into a private paragraph index.
  seraphix_evidence_anchor.py ranks evidence using BM25.
- seraphix_scene_answer.py: answer/before/after extraction, citation validation,
  model verification, bounded repairs, and verified partial results.
- seraphix_narrative_engine.py: earlier narrative retrieval and answer cleaning.
- seraphix_canon_intelligence.py, seraphix_book_qa.py, seraphix_book_reader.py,
  seraphix_book_guard_v284.py: legacy chunk retrieval, indexing, and guards.
  The GUI still imports legacy helpers; its active /book route uses the paragraph
  retriever and scene answer module.
- seraphix_tools_v28.py and seraphix_tools_v281.py: workspace reading, bounded
  filename searches, and optional web research.
- seraphix_kokoro_voice.py: optional speech subprocess.
- seraphix_config.py: optional trusted rules and environment configuration.
- test_seraphix_retrieval.py, test_seraphix_scene_answer.py, and
  test_release_sanitization.py: offline synthetic tests.
- test_kokoro_voices.py: manual synthetic audio demo; importing it is inert.
- Config/Modelfile: optional generic Ollama model template; not loaded by the GUI.

## Setup (not executed during preparation)

Use Python 3.10 or newer with Tk installed. The original GUI and fallback speech
path target Windows. Non-Windows GUI/audio operation has not been verified.

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe seraphix_app.py

Install Ollama separately and make the selected model available before chat use.
The default is qwen3:14b; SERAPHIX_MODEL selects another. The injected Ollama client
also honors its own endpoint configuration: verify the endpoint before sending
private text. Model downloads are outside the offline test procedure.

For Kokoro speech, create .venv_kokoro separately and install requirements-voice.txt
there. Kokoro can download model data on first use. Windows fallback uses pyttsx3
and pywin32. System audio libraries and runtime dependencies may require separate
platform setup. Direct dependencies are declared but not locked to verified
versions. Transitive reproducibility and third-party license review remain tasks.

Portraits are optional: the GUI has a built-in text fallback. Proprietary assets
and model weights are unnecessary for architecture review.

## Configuration

Config/config.example.json is empty of story rules and is not loaded automatically.
For private rules, copy it to an ignored file such as Config/config.local.json and
set SERAPHIX_CONFIG to that file. Relative paths resolve against this directory.

| Environment variable | Default | Purpose |
|---|---|---|
| SERAPHIX_MODEL | qwen3:14b | GUI model name |
| SERAPHIX_CONFIG | unset | Optional trusted rule JSON |
| SERAPHIX_WORKSPACE_ROOT | Assistant_Workspace | Discovery and /readw root |
| SERAPHIX_CANON_FILE | Memory/Canon/reference.md | Optional private reference |

The /files and /read commands retain a separate project-relative
Assistant_Workspace boundary. /searchdrive and /readw are legacy command names;
they now use the configured workspace instead of an entire personal drive.
Natural-language discovery accepts "find files named sample in workspace".
The /research command sends its query to an external search endpoint.

Optional trusted rule keys:

- entities: names for legacy retrieval prioritization; empty by default.
- retrieval_rules: objects with question_terms (all terms occur in the question)
  and source_pattern (regular expression).
- identity_rules: the same keys plus answer; enables the legacy configured-answer
  helper, not the active paragraph-answer route.
- unsupported_patterns: regular expressions rejected by the legacy guard.

Rules are trusted local configuration, not model output. Configured answers and
regex hits are not proof of entailment. Validate private rules independently.
No story-specific rules or deterministic answers are bundled.

## Evidence contract

The current retriever returns one record containing anchor, chapter, before,
anchor_text, and after. Source paragraphs use (P123); answers cite [P123].
The v3.1.6 answer module accepts lists/tuples of mapping records and validates
anchors/content before model calls. It rejects conflicting paragraph text.
Multiple records require the same explicit source_id identifying one paragraph
number namespace. Identical repeated text is accepted; ambiguity fails closed.

## Offline synthetic tests

No third-party GUI/model/audio packages are required for these tests:

    python -B -m unittest -v test_seraphix_retrieval test_seraphix_scene_answer test_release_sanitization

Do not execute test_kokoro_voices.py as an offline test: main() generates audio
and may download model data. Preparation also blocked network connections and
subprocess/model calls during the synthetic suite. GUI, actual speech, actual
model calls, and real manuscript behavior were not tested.

## Runtime privacy and limitations

Importing the GUI configures diagnostic logging and creates its conversation
directory. Running it saves conversations and generated answers. Manuscript import
writes derived text and source-path metadata under Memory/Book_Index; keep these
private. General chat attaches the optional reference and recent messages to model
requests. Book requests send retrieved passages, and failure fallbacks may return
literal excerpts. Exception tracebacks can contain paths or sensitive details.

Workspace reading is a convenience feature, not a security sandbox. Filename
filters and best-effort credential redaction do not make arbitrary documents safe.
Do not point it at private project or credential directories. Model verification
is heuristic and does not prove entailment. Finite call counts do not establish
client timeouts or token-size bounds. These limitations are retained for review.

## Sanitized variant and release policy

Only this separate copy was changed. Story-specific logic became empty config
hooks, personal absolute paths were removed, discovery was narrowed, branding
was generalized, legacy chunk filenames became generic, and the manual voice
demo became safe to import. The live application was untouched. This variant
intentionally differs in those sanitized areas.

.gitignore denies all root entries except exact reviewed files. This directory
contains no .git history. Never copy a private .git directory or force-add files.
RELEASE_REVIEW.md records checks and the proposed release procedure.

## License

LICENSE is pending owner decision. No license is invented or granted by this
preparation. Dependency/model/voice license obligations require separate review.

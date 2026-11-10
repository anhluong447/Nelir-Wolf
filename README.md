# Nelir WOLF RPG Translator

Nelir WOLF RPG Translator is an automated translation and localization platform designed specifically for games created with the WOLF RPG Editor engine. It provides an end-to-end localization workflow featuring multi-engine AI translation (Google Gemini, OpenRouter, Kaggle / Local LLMs), intelligent API key and model fallback rotation, an isolated multi-project architecture, engine logic safety locking, automated translation QA, and non-destructive binary game patching via WolfTL.

---

## Key Features

### 1. Multi-Project Architecture
* **Isolated Project Workspaces**: Manage translations for multiple WOLF RPG games within a single unified web interface. Each project maintains its own independent SQLite database (`translation.db`), raw script dump files, and target game installation paths.
* **Centralized Configuration**: Global settings—including API keys, provider endpoints, prioritized fallback models, system prompts, and interface themes—are managed centrally in `global_settings.db`, shared across projects without redundant re-entry.

### 2. Portable Project Packaging (.nel Format)
* **Single-File Archiving**: Export the entire translation state, string status flags, and project metadata into a compact, compressed `.nel` container (typically 1 to 2 MB).
* **Seamless Export & Import**: Create standalone backup archives with one click or import `.nel` packages onto other systems to continue translation or apply patches immediately.

### 3. Resilient AI Pipeline with Automatic Quota & Key Rotation
* **Google Gemini Multi-Key Rotation**: Configure a pool of Google AI Studio API keys. When a key exhausts its daily quota or encounters HTTP 429 (`RESOURCE_EXHAUSTED`), the translation engine automatically shifts to the next available key in the pool.
* **Tiered Model Fallbacks**: Establish primary and secondary model preferences (Priority 1 through Priority 5). If the primary model encounters rate limits or transient errors, requests transparently fail over to secondary models. Every new batch tries the primary model first again, so it is picked up as soon as its quota replenishes.
* **Flexible Provider Support**: Fully compatible with OpenAI-compatible endpoints, including OpenRouter, Kaggle compute instances, and local LLM runners (such as Ollama or vLLM).

### 4. Engine Logic Protection & Automatic Key Locking
* **Selective Extraction**: Differentiates player-facing text (`Message`, `Choice`, `DBName`, `DBField`, `SetString`, `Picture`, `GameTitle`) from engine runtime scripts.
* **Automated Key Locking**: Scans all Common Events and Map commands to detect strings used as variable references, database lookups, or comparison conditions. Any string referenced programmatically is permanently locked to its original Japanese value to prevent runtime errors (e.g., `the data name does not exist` or broken branching).
* **Runtime Database Safeguards**: Internal engine work memory (`CDataBase.dat`) is strictly excluded from extraction and modification.

### 5. Automated Quality Assurance (QA) Engine
* **Status Classification**: Each row is tracked with explicit status semantics: Empty (`0`), Machine Translated (`1`), Human Reviewed (`2`), or QA Flagged (`3`).
* **Automated Anomaly Detection**: Flags translations that retain unintended Japanese characters, mismatch original line counts, omit engine control codes (`\c[]`, `\s[]`, `\E`, `<C>`, `@1`), contain unclosed brackets, or exceed display window widths.
* **Error Resilience**: Failed API requests raise structured exceptions rather than saving raw Japanese text as completed translations.

### 6. Translation Memory & Glossary Management
* **Deduplication**: Identical source strings within a batch are requested only once and populated across all occurrences, conserving API tokens and ensuring terminological consistency.
* **Context-Aware Glossary Injection**: Project-specific glossaries are dynamically injected into translation prompts when matching source keywords are detected.
* **Translation Synchronization**: Batch tools enable aligning diverging translations across identical source lines throughout the project.

### 7. Non-Destructive Game Patching & Rollback
* **Pristine Reference Dumps**: Each project retains an unmodified Japanese dump (`dump_original/`). During patch compilation, working files are synthesized dynamically from the original reference combined with translated rows, followed by execution of `WolfTL --patch --inplace`.
* **Integrity Validation**: Verifies path-to-source integrity before writing. Patching is blocked if translations introduce new unresolved database queries or orphan labels compared to the source game.
* **Automatic Rollback Backups**: Backs up `Data/BasicData` and `Data/MapData` prior to the initial patch operation. Full restoration to pristine Japanese data is available at any time without compromising translation database records.

### 8. Translator Workbench Interface
* **Three-Pane Layout**: A file tree with per-file progress, a segment list with status stripes and control codes rendered as inline chips, and an inspector panel for editing the selected segment.
* **Inspector Editor**: Shows the source text, the machine suggestion (one-click "use this"), and an editor with live QA while typing (line count, line length, Japanese residue, missing control codes with one-click re-insertion). Also shows the surrounding context (±2 segments in the same file) and matching glossary terms that can be inserted with one click.
* **Background Batch Jobs**: Batch translation runs in a minimisable job dock, so reviewing and editing can continue while the AI works. Visible rows update as each batch completes.
* **Appearance**: Dark and light themes, comfortable or compact density, and normal or large text size (Settings > Appearance).

| Key | Action |
|---|---|
| `Up` / `Down` (or `J` / `K`) | Previous / next segment |
| `Alt+Down` / `Alt+Up` | Next / previous segment that still needs work |
| `Enter` / `Esc` | Focus the editor / return to the list |
| `Ctrl+Enter` | Save, mark reviewed and move to the next segment |
| `Ctrl+S` | Save |
| `Ctrl+Shift+A` / `Ctrl+Shift+U` | AI-translate this segment / use the machine suggestion |
| `Ctrl+F` / `Ctrl+B` / `?` | Search / toggle the file tree / shortcut sheet |

---

> **Target language:** the prompts, output cleanup and line-splitting heuristics are currently written for **Japanese → Vietnamese**, and the interface is in Vietnamese. Other target languages would need changes in `config.py` and `openrouter.py`.

> **Local only:** the server answers only to `127.0.0.1` / `localhost` Host headers (`config.ALLOWED_HOSTS`) because the API exposes your API keys and runs WolfTL. Do not expose it to a network.

## System Requirements

* **Operating System**: Windows 10 / 11 (64-bit)
* **Python**: Version 3.10 or higher
* **Underlying Tool**: WolfTL (packaged in `bin/`). It is a third-party tool by its own author; check its upstream license before redistributing this repository, and replace `bin/WolfTL.exe` with a build you trust if you prefer.
* **Game data**: the game's `Data` folder must be unpacked (games shipping `Data.wolf` need to be extracted first).

---

## Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/anhluong447/Nelir-Wolf.git
   cd Nelir-Wolf
   ```

2. **Install required dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Launch the application**:
   Execute `run.bat` or run:
   ```bash
   python server.py
   ```

4. **Access the Web Interface**:
   Open a modern web browser and navigate to:
   ```
   http://127.0.0.1:8765
   ```

---

## Automated Testing & Validation

The project includes an automated regression test suite operating on synthetic game dumps without requiring network access or external game binaries:

```bash
# Install test dependencies (adds httpx for the API tests)
pip install -r requirements-dev.txt

# Run unit and integration tests
python -m unittest discover -s tests -v

# Run static script verification on a specific project
python validator.py --project <project_id>
```

The `NELIR_DATA_DIR` environment variable can be set to point tests or portable deployments to an alternative data directory containing `projects/` and `global_settings.db`.

---

## Directory Structure

```
Nelir-Wolf/
|-- bin/
|   `-- WolfTL.exe                  # Wolf RPG data extraction and patching binary
|-- projects/                       # Translation project workspaces
|   `-- <Project_ID>/
|       |-- project.json            # Project metadata and game directory paths
|       |-- translation.db          # Project SQLite database (translations, glossary, metadata)
|       |-- dump_original/          # Unmodified pristine Japanese dump
|       |-- dump/                   # Active working dump synchronized during patching
|       `-- game_backup/            # Pristine game backup taken prior to initial patch
|-- static/                         # Web UI: index.html, css/ (design tokens, views), js/ (ES modules)
|-- tests/                          # Automated unit test suite
|-- config.py                       # Global configurations, defaults, and row type definitions
|-- db.py                           # SQLite connection pooling and schema definitions
|-- extractor.py                    # Dump parsing, database synchronization, and logic locking
|-- qa.py                           # Translation quality assurance and control code verification
|-- pipeline.py                     # Translation workflow (TM -> AI Translation -> QA -> Database)
|-- validator.py                    # Static analysis engine (labels, database lookups, logic keys)
|-- bridge.py                       # Project lifecycle controller (patching and restoration)
|-- project_manager.py              # Multi-project lifecycle and .nel archive manager
|-- openrouter.py                   # OpenAI-compatible API client with key and model rotation
`-- server.py                       # FastAPI application server and REST API endpoints
```

---

## License & Disclaimers

This software is developed for game localization, preservation, and research purposes. All trademarks, game assets, and engine binaries belong to their respective copyright holders. Users are responsible for ensuring compliance with the terms and licenses of the games they translate.

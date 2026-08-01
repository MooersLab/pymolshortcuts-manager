# PyMOL Shortcuts Manager Plugin — Setup Guide


## Requirements

| Dependency | Version       | Notes                                              |
|:-----------|:--------------|:---------------------------------------------------|
| Python     | 3.8 or later  | Ships with PyMOL 3.x                               |
| PyMOL      | 3.x           | Open-source or incentive; provides `pymol.Qt`      |

The shortcuts file `pymolshortcuts.py` (latest version) should be
downloaded from [MooersLab/pymolshortcuts](https://github.com/MooersLab/pymolshortcuts)
or loaded from a local copy.

### Optional: AI Assistant Providers

The AI Assistant tab supports five LLM back-ends. Each requires its own
credentials:

| Provider         | What You Need                                                      |
|:-----------------|:-------------------------------------------------------------------|
| Anthropic Claude | API key from [console.anthropic.com](https://console.anthropic.com/) |
| OpenAI           | API key from [platform.openai.com](https://platform.openai.com/)   |
| Google Gemini    | API key from [aistudio.google.com](https://aistudio.google.com/)   |
| Ollama (local)   | [Ollama](https://ollama.com/) running on `localhost:11434`         |
| Custom API       | Any OpenAI-compatible endpoint (e.g., LM Studio, vLLM, Together AI) |


## Installation

### Method 1: PyMOL Plugin Manager (recommended)

1. Open PyMOL.
2. Navigate to **Plugin → Plugin Manager → Install New Plugin**.
3. Choose **Install from local file** and select `pymolshortcuts_manager.py`.
4. Restart PyMOL. The plugin appears under **Plugin → PyMOL Shortcuts Manager**.

### Method 2: Manual Installation

Copy the plugin file into the PyMOL startup directory:

```bash
# macOS
cp pymolshortcuts_manager.py ~/Library/PyMOL/startup/

# Linux
cp pymolshortcuts_manager.py ~/.pymol/startup/

# Windows (PowerShell)
Copy-Item pymolshortcuts_manager.py "$env:APPDATA\PyMOL\startup\"
```

### Method 3: Auto-run via `.pymolrc`

Add the following line to `~/.pymolrc` (create the file if it does not exist):

```python
run ~/path/to/pymolshortcuts_manager.py
```

### Persisting the Shortcuts File Between Sessions

The plugin **automatically persists** the shortcuts file path every time
you install shortcuts through the Installation tab.  On subsequent plugin
opens the Shortcuts tab is pre-populated immediately — no reinstallation
required.

When the plugin dialog opens it resolves the shortcuts file through a
three-level fallback chain:

1. **Module-level auto-load path** — set by `__init_plugin__` when
   *auto-load* is enabled in the Settings tab.
2. **QSettings saved path** — written automatically whenever you install
   shortcuts via the Installation tab.
3. **Well-known filesystem locations** — `~/pymolshortcuts.py`,
   `~/Library/PyMOL/startup/pymolshortcuts.py` (macOS),
   `~/.pymol/startup/pymolshortcuts.py` (Linux), and
   `%APPDATA%\PyMOL\startup\pymolshortcuts.py` (Windows).

You can also configure the default path and enable auto-load explicitly
in the **Settings** tab.


## Quick Start

1. Launch PyMOL.
2. Open the plugin: **Plugin → PyMOL Shortcuts Manager**.
3. Go to the **Installation** tab and either browse to a local copy of
   `pymolshortcuts.py` or download it from GitHub.
4. Click **Install Shortcuts**.
5. Switch to the **Shortcuts** tab, type a keyword in the search box,
   and double-click a shortcut to execute it.


## Plugin Tabs

The plugin dialog contains ten tabs organized by workflow:

| Tab          | Purpose                                                                                              |
|:-------------|:-----------------------------------------------------------------------------------------------------|
| Installation | Download or browse for `pymolshortcuts.py`; detect OS; install `psico` via conda                     |
| Shortcuts    | Searchable, sortable table of all shortcuts; click to execute; view docstrings; copy PML or Python   |
| Add Shortcut | Author a new shortcut with structured docstring fields; preview generated code; submit a GitHub PR    |
| AI Assistant | Ask natural-language questions about shortcuts; uses RAG retrieval with five LLM back-ends           |
| History      | Timestamped log of every shortcut executed; re-execute with one click; export to CSV                  |
| Favorites    | Star frequently used shortcuts for quick access; organize by category                                 |
| Tutorial     | Seven guided walkthroughs that teach shortcut usage by running commands in the PyMOL viewport         |
| Citation     | Copy or save BibTeX and EndNote entries for the Mooers 2020 *Protein Science* paper                   |
| Settings     | Configure file paths, auto-load behavior, AI provider preferences, and display options                |
| Links        | Curated hyperlinks to documentation, the GitHub repository, and related resources                     |


## AI Assistant Configuration

The AI Assistant tab implements a lightweight RAG (Retrieval-Augmented
Generation) pipeline so that answers are grounded in the actual content of
`pymolshortcuts.py`.

### RAG Pipeline

1. **Load** — The shortcuts file is read into memory.
2. **Chunk** — The text is split into overlapping 500-token chunks
   (100-token overlap) to preserve context across boundaries.
3. **Embed** — Each chunk receives a simple term-frequency embedding
   vector. No external embedding model is required.
4. **Search** — At query time the user's question is embedded and
   compared to every chunk via cosine similarity; the top-*k* chunks are
   retrieved.
5. **Generate** — The retrieved chunks are prepended to the prompt sent
   to the selected LLM, which generates a context-aware answer.

Timing statistics for each step (file loading, chunking, embedding) are
printed to the status area during indexing.

The AI tab discovers the shortcuts file through the same three-level
fallback chain used by the Shortcuts tab, so it works immediately after a
fresh install without requiring a separate indexing step.

### Provider Configuration

| Provider   | Configuration                                                                                     |
|:-----------|:--------------------------------------------------------------------------------------------------|
| Claude     | Paste your Anthropic API key; select a model (e.g., `claude-sonnet-4-20250514`)                   |
| OpenAI     | Paste your OpenAI API key; select a model (e.g., `gpt-4o`)                                       |
| Ollama     | Set the host URL (default `http://localhost:11434`); click *List Models* to discover models        |
| Gemini     | Paste your Google AI Studio API key; select a model (e.g., `gemini-2.0-flash`)                    |
| Custom     | Enter any OpenAI-compatible endpoint URL, model name, API key, and optional auth header/prefix     |


## Cross-Platform Notes

The plugin supports macOS, Linux, and Windows. The Installation tab
detects the operating system automatically and provides the appropriate
`psico` installation command for conda.


## Setting up the Agentic AI tab

1. Install a coding harness. Claude Code provides the `claude` executable;
   Pi provides `pi`. Any other agent with a headless command-line mode works
   through the generic adapter.
2. Open the plugin, go to the **Agentic AI** tab, and open the **Harness**
   pane.
3. Click **Auto-detect**. When the executable is somewhere unusual, click
   **Browse...** instead.
4. Set the working directory to your `pymolshortcuts` checkout, so the agent
   can read the existing library.
5. Click **Test Harness**. The transcript should show a version string.
6. Click **Save Harness Settings**.
7. Open the **Skills** pane and click **Install Selected Skill** after ticking
   `pymol-shortcuts-author` and `pymol-shortcuts-test`.

Generated code lands in `~/.pymolshortcuts/agent/` and never touches your
shortcuts file until you click one of the integration buttons.


## Registering the MCP server

To let an external harness drive the shortcut library instead:

```bash
claude mcp add pymolshortcuts -- python /path/to/pymolshortcuts_mcp.py
```

Add `PYMOLSHORTCUTS_PATH=/path/to/pymolshortcuts.py` to the server's
environment when the shortcuts file is not in a standard location. Leave
`PYMOLSHORTCUTS_MCP_ALLOW_LIVE` unset unless you want the server to be able to
execute generated code in a running PyMOL session.

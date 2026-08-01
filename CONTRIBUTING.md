# Contributing to the PyMOL Shortcuts Manager Plugin

Contributions are welcome! To get started:

1. Fork the repository and create a feature branch.
2. Make your changes in the feature branch.
3. Ensure all tests pass:
   ```bash
   make test
   ```
4. Add new tests for any new functionality.
5. Open a pull request describing what you changed and why.


## Coding Conventions

- Follow [PEP 8](https://peps.python.org/pep-0008/) style guidelines.
- Use `pymol.Qt` imports exclusively (never import `PyQt5` or `PyQt6`
  directly) to maintain compatibility with both Qt bindings.
- Keep all GUI code in tab-specific classes that inherit from
  `QtWidgets.QWidget`.
- Document every new shortcut with a structured docstring containing
  `DESCRIPTION`, `USAGE`, `ARGUMENTS`, `EXAMPLE`, `MORE DETAILS`,
  `VERTICAL PML SCRIPT`, `HORIZONTAL PML SCRIPT`, and `PYTHON CODE`
  sections.
- Keep the harness-specific command-line strings inside the `run_argv`
  method of a `HarnessAdapter` subclass. A renamed vendor flag should be a
  one-method change.
- Never call `eval`, `exec`, `os.system`, `subprocess`, or `shutil.rmtree`
  inside a shortcut. The validator rejects them, because a shortcut runs
  inside the user's live PyMOL session.


## Model-generated contributions

A pull request that carries a shortcut written wholly or partly by a
language model is welcome, and it must disclose that fact.

State in the pull request description which harness and which model wrote
the code, and which skills the run used. The Agentic AI tab records all of
this in `~/.pymolshortcuts/agent/runs.json`, so the information is a copy
and paste away.

The shortcut must pass all three validation tiers before the pull request
is opened: the static check against the docstring contract, the generated
pytest module, and a run inside a live PyMOL session against a reference
structure. Paste the validation output into the pull request.

Review the code yourself before you submit it. A generated shortcut that
you have not read is not a contribution, it is a forwarding address.


## Testing

The test suite runs entirely without PyMOL or a display server by mocking
`pymol`, `pymol.cmd`, and `pymol.Qt` at the module level.

### Prerequisites

```bash
pip install pytest pytest-cov
```

### Running the Tests

Place `test_pymolshortcuts_manager.py` and `pymolshortcuts_manager.py` in
the same directory, then use the provided Makefile:

```bash
# Run the full test suite
make test

# Verbose output (one line per test)
make verbose

# Minimal output (dot per test)
make quiet

# Generate an HTML coverage report
make coverage

# Run a single test
make single T=TestRAGEngine::test_cosine_similarity_identical

# Re-run only previously failed tests
make failed

# Lint the plugin source
make lint

# Clean up caches and bytecode
make clean

# Show available targets
make help
```

Or run directly with pytest:

```bash
python -m pytest test_pymolshortcuts_manager.py -v
```

### Test Suite Overview

The suite contains **248 tests** across **31 test classes**, organized by
component:

| Test Class                       | Tests | Coverage                                                    |
|:---------------------------------|------:|:------------------------------------------------------------|
| `TestShortcutData`                |     3 | Data class defaults, all fields, keybinding identity
| `TestShortcutsParser`             |     9 | Parsing, empty and missing files, docstring extraction
| `TestRAGEngine`                   |    17 | Chunking, embeddings, cosine similarity, search, file loading
| `TestRAGTimingStatistics`         |     2 | Timing output verification during indexing
| `TestAPICallConstruction`         |    13 | Request payloads and error handling for all five providers
| `TestAPITestConnections`          |     4 | Gemini and Custom test-connection methods
| `TestTutorialTab`                 |     9 | Tutorial data integrity, display, execution, clipboard
| `TestCitationTab`                 |    18 | BibTeX and EndNote accuracy, clipboard copy, file save
| `TestHistoryTab`                  |     5 | Persistence, add and increment, clear, CSV export
| `TestFavoritesTab`                |     5 | Add, duplicate detection, remove, persistence
| `TestSettingsTab`                 |     3 | QSettings save, load, and clear
| `TestShortcutsTableModel`         |    10 | Row and column counts, data retrieval, description truncation
| `TestPluginDialogAssembly`        |     8 | Eleven tab names, tab order, class and method existence
| `TestAddShortcutCodeGeneration`   |     5 | Form validation, code generation with docstrings
| `TestInstallationTabDownload`     |     2 | GitHub download success and network-error handling
| `TestAutoPopulateShortcuts`       |     3 | Module-level, QSettings, and filesystem fallback discovery
| `TestOnShortcutsInstalled`        |     4 | QSettings persistence, tab refresh, module-level update
| `TestApplyAppearance`             |    11 | Font size, built-in themes, qdarktheme, save and reset paths
| `TestDarkthemeInstallation`       |     5 | Detection and pip installation of pyqtdarktheme
| `TestEdgeCases`                   |     5 | Empty names, long lines, large vectors, UTF-8 content
| `TestVersionAndMetadata`          |     3 | Version string, module docstring, author attribution
| `TestHarnessAdapters`             |    14 | Argument vectors for Claude Code, Pi, and the generic CLI
| `TestHarnessProcess`              |     8 | Line streaming, exit codes, timeout, stdin payload, stop
| `TestHarnessRunner`               |     9 | Signal emission on success, failure, timeout, and exception
| `TestSkillRegistry`               |    11 | Frontmatter parsing, directory scanning, precedence, install
| `TestAgenticPromptTemplates`      |     8 | Template rendering and the retrieval context
| `TestCandidateValidator`          |    18 | The static, pytest, and live validation tiers
| `TestAgenticSettings`             |     7 | Round trip of every agentic/ key through QSettings
| `TestAgentRunStore`               |     6 | Run log add, load, trim, clear, and export
| `TestAgenticIntegration`          |    11 | Run directories, backup and append, form prefill, input checks
| `TestMCPServer`                   |    12 | JSON-RPC surface, tool registry, and the two guarded tools


### Mock Architecture

The test file creates a complete mock hierarchy that replaces the PyMOL
and Qt runtime:

- **`sys.modules` injection** — `pymol`, `pymol.cmd`, and `pymol.Qt` are
  replaced with `MagicMock` objects before the plugin module is imported.
- **`MockQSettings`** — An in-memory dictionary-backed replacement for
  `QtCore.QSettings` that supports `value()`, `setValue()`, `sync()`,
  and `clear()`.
- **`MockWidget` / `MockDialog`** — Minimal stand-ins for `QWidget` and
  `QDialog` that satisfy the constructor chain without a running Qt event
  loop.
- **Dynamic module loading** — The plugin is loaded via
  `importlib.util.spec_from_file_location` so that the mocked `pymol.Qt`
  module is already in `sys.modules` when the top-level imports execute.


## Project Layout

```
pymolshortcuts/
├── pymolshortcuts_manager.py          # Main plugin source
├── test_pymolshortcuts_manager.py     # Test suite (248 tests, 31 classes)
├── pymolshortcuts_mcp.py             # Companion MCP server (stdio)
├── skills/                           # Bundled skills for the Agentic AI tab
├── Makefile                          # Build and test automation
├── README.md                         # GitHub README
├── CONTRIBUTING.md                   # This file
├── SETUP_GUIDE.md                    # Detailed setup instructions
├── requirements.txt                  # Python dependencies
├── REUSE.toml                        # Machine-readable license declarations
├── docs/
│   ├── index.rst                     # Read the Docs entry point
│   ├── conf.py                       # Sphinx configuration
│   └── images/                       # Screenshots for documentation
├── LICENSE                           # MIT license
└── pymolshortcuts.py                 # The shortcuts file (downloaded separately)
```


## Licenses

The software is licensed under the [MIT License](LICENSE). By submitting
code you agree to license your contribution under those terms.

The screenshots in `docs/images/` are licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), which is a
different license from the one covering the code. By submitting an image
to that directory you agree to license it under CC BY 4.0, and you confirm
that you either created it or hold the rights to release it that way. Do
not add a screenshot that contains a figure, a logo, or an interface
element you do not have the right to relicense.

Both declarations are also recorded in machine-readable form in
[`REUSE.toml`](REUSE.toml).

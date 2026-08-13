.. PyMOL Shortcuts Manager Plugin documentation master file

=============================================
PyMOL Shortcuts Manager Plugin Documentation
=============================================

.. note::

   This documentation covers version 0.4.1.

.. contents:: Table of Contents
   :depth: 3
   :local:

Overview
========

The **PyMOL Shortcuts Manager Plugin** is a PyQt-based plugin for managing,
searching, and executing `PyMOL shortcuts
<https://github.com/MooersLab/pymolshortcuts>`_ directly inside the PyMOL
molecular-graphics application.  The plugin integrates an AI assistant powered
by a lightweight Retrieval-Augmented Generation (RAG) engine that answers
questions about the shortcuts in natural language.

Key capabilities:

- Searchable, sortable shortcut table with click-to-execute functionality
- Tags on every shortcut, with a tag filter and an in-place tag editor
- AI Assistant with RAG retrieval supporting five LLM providers
- Seven guided tutorials that run commands directly in the PyMOL viewport
- History and Favorites tabs with cross-session persistence
- BibTeX and EndNote citation entries for the Mooers 2020 *Protein Science*
  paper
- Bundled shortcuts that load automatically on first launch, so a novice does
  not need the Installation tab; the plugin caches the library to
  ``~/.pymolshortcuts/pymolshortcuts.py`` and a ``use_bundled_default`` setting
  turns this off
- Automatic shortcuts discovery on plugin startup via a fallback chain
  (module-level path, QSettings, the bundled copy, well-known filesystem
  locations)
- Command-line launchers ``scg`` and ``psm`` that reopen the GUI from the
  PyMOL prompt
- Cross-platform support for macOS, Linux, and Windows


Requirements
============

============  ============  ===================================================
Dependency    Version       Notes
============  ============  ===================================================
Python        3.8+          Ships with PyMOL 3.x
PyMOL         3.x           Open-source or incentive; provides ``pymol.Qt``
============  ============  ===================================================

Optional AI-provider dependencies:

================  ===================================================
Provider          What you need
================  ===================================================
Anthropic Claude  API key from `console.anthropic.com`_
OpenAI            API key from `platform.openai.com`_
Google Gemini     API key from `aistudio.google.com`_
Ollama (local)    `Ollama <https://ollama.com/>`_ on localhost:11434
Custom API        Any OpenAI-compatible endpoint
================  ===================================================

.. _console.anthropic.com: https://console.anthropic.com/
.. _platform.openai.com: https://platform.openai.com/
.. _aistudio.google.com: https://aistudio.google.com/


Installation
============

Via the PyMOL Plugin Manager (recommended)
------------------------------------------

1. Open PyMOL.
2. Navigate to **Plugin → Plugin Manager → Install New Plugin**.
3. Choose **Install from local file** and select
   ``pymolshortcuts_manager.py``.
4. Restart PyMOL.  The plugin appears under
   **Plugin → PyMOL Shortcuts Manager**.

Manual installation
-------------------

Copy the plugin file into the PyMOL startup directory:

.. code-block:: bash

   # macOS
   cp pymolshortcuts_manager.py ~/Library/PyMOL/startup/

   # Linux
   cp pymolshortcuts_manager.py ~/.pymol/startup/

   # Windows (PowerShell)
   Copy-Item pymolshortcuts_manager.py "$env:APPDATA\PyMOL\startup\"

Auto-run via ``.pymolrc``
-------------------------

Add the following line to ``~/.pymolrc`` (create the file if it does not
exist):

.. code-block:: python

   run ~/path/to/pymolshortcuts_manager.py

Persisting the shortcuts file
-----------------------------

The plugin **automatically persists** the shortcuts file path every time
you install shortcuts through the Installation tab.  On subsequent plugin
opens the Shortcuts tab is pre-populated immediately — no reinstallation
required.

When the plugin dialog opens it resolves the shortcuts file through a
three-level fallback chain:

1. **Module-level auto-load path** — set by ``__init_plugin__`` when
   *auto-load* is enabled in the Settings tab.
2. **QSettings saved path** — written automatically whenever you install
   shortcuts via the Installation tab.
3. **Well-known filesystem locations** — ``~/pymolshortcuts.py``,
   ``~/Library/PyMOL/startup/pymolshortcuts.py`` (macOS),
   ``~/.pymol/startup/pymolshortcuts.py`` (Linux), and
   ``%APPDATA%\PyMOL\startup\pymolshortcuts.py`` (Windows).

You can also configure the default path and enable auto-load explicitly in
the **Settings** tab.


Quick Start
===========

1. In PyMOL, go to **Plugin → Plugin Manager → Install New Plugin**, choose
   **Install from local file**, and select ``pymolshortcuts_manager.py``.
   (You can also paste the raw URL to that file under **Install from
   PyMOLWiki or any URL**.)
2. Restart PyMOL.  The plugin appears under **Plugin → PyMOL Shortcuts
   Manager**.  On first launch it loads the bundled shortcuts automatically,
   so there is nothing to install on the Installation tab.
3. Open the plugin: **Plugin → PyMOL Shortcuts Manager**.
4. On the **Shortcuts** tab, type a keyword in the search box to find a
   shortcut, then click its row to select it.
5. Click **Execute** (or double-click the row) to run the shortcut in PyMOL.

Reopening the GUI from the command line
---------------------------------------

Once the shortcuts file is loaded, type ``scg`` or ``psm`` at the PyMOL
prompt to reopen the Shortcuts Manager GUI at any time.  Both call the
plugin's ``run_plugin_gui()`` launcher, so a return to the Plugin menu is
not needed.  ``scg`` stands for shortcut-manager GUI, and ``psm`` stands for
pymolshortcuts-manager.  Each locates the loaded manager module before
falling back to the common import paths, so it prints a short install hint
when the plugin is not yet available.


Plugin Tabs
===========

The plugin dialog contains eleven tabs organized by workflow.  The
Installation tab sits at the right end, because the bundled shortcuts load
automatically and a novice no longer needs it.

Shortcuts
---------

A searchable, sortable table of every shortcut parsed from the shortcuts
file.  Select a row to see the full docstring, PML scripts, and Python
code.  Double-click or press **Execute** to run the shortcut in PyMOL.
Buttons are provided to copy the vertical PML script or the Python code to
the clipboard.

Every shortcut carries a set of tags.  The table shows a Tags column, the
details panel lists the tags for the selected shortcut, and the **Tag**
selector beside the search box filters the table to one tag at a time.
Edit the tags in the **Tags** field and press **Save Tags** to write them.
The canonical tags live in a ``TAGS:`` section of each shortcut docstring,
placed after the ``DESCRIPTION:`` section, and a per-user overlay in
``~/.pymolshortcuts/tags.json`` records local changes on top of them.  The
tag vocabulary, the storage target, and the strict-vocabulary warning are
configured on the Settings tab.

Add Shortcut
------------

Author a new shortcut by filling in structured docstring fields
(description, usage, arguments, example, PML scripts, Python code).
Preview the generated function definition and submit it as a pull request
to the upstream GitHub repository.

AI Assistant
------------

Ask natural-language questions about shortcuts.  The tab provides sub-tabs
for each supported provider:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Provider
     - Configuration
   * - **Claude**
     - Paste your Anthropic API key; select a model
   * - **OpenAI**
     - Paste your OpenAI API key; select a model
   * - **Ollama**
     - Set the host URL; click *List Models* to discover installed models
   * - **Gemini**
     - Paste your Google AI Studio API key; select a model
   * - **Custom**
     - Enter any OpenAI-compatible endpoint, model, API key, and optional
       auth header/prefix

See :ref:`ai-assistant-details` for a full description of the RAG pipeline.

Agentic AI
----------

Wire a coding harness such as Claude Code or Pi to the plugin and use it to
generate, validate, and document a new shortcut without leaving PyMOL.  The
tab holds four panes.

**Harness** selects the coding agent, finds its executable, and proves it
answers.  Three adapters ship with the plugin: Claude Code driven through
``claude -p``, Pi driven through ``pi -p`` (or ``pi --mode json`` or
``pi --mode rpc``), and a generic adapter driven through a user-supplied argv
template with the placeholders ``%EXE%``, ``%PROMPT%``, ``%CWD%``,
``%SKILLS%``, ``%OUTDIR%``, and ``%MODEL%``.  The run happens on a worker
thread, so the PyMOL window stays responsive for the whole run.

**Workbench** runs the generate, test, and document loop.  Before the generate
prompt is sent, the three existing shortcuts most similar to the stated goal
are retrieved through the AI Assistant's engine and pasted in as style
examples.  Validation runs in three tiers: a static check against the
docstring contract, the generated pytest module, and an optional run inside
the live PyMOL session against a reference structure.  The live tier is gated
behind a dialog that shows the code, because the code came from a model.

**Skills** discovers every ``SKILL.md`` in the bundled ``skills/`` directory,
in the working directory's ``.claude/skills``, and in ``~/.claude/skills``.
Two first-party skills ship with the plugin: ``pymol-shortcuts-author`` and
``pymol-shortcuts-test``.

**Runs** keeps the record of past runs in
``~/.pymolshortcuts/agent/runs.json``.

Nothing the harness writes reaches the shortcuts file on its own.  Everything
lands in a scratch run directory under ``~/.pymolshortcuts/agent/`` until you
send it to the Add Shortcut tab or append it to the shortcuts file, and the
append writes a timestamped backup first.

History
-------

A timestamped log of every shortcut executed through the plugin.  Entries
record the shortcut name, execution count, and most-recent timestamp.
Re-execute a shortcut from history with a single click.  Export the full
history to CSV.

Favorites
---------

Star frequently used shortcuts for quick access and organize them by
user-defined categories.

Tutorial
--------

Seven guided walkthroughs that teach shortcut usage by running commands
directly in the PyMOL viewport.  See :ref:`tutorials` for the full list.

Citation
--------

Ready-to-copy BibTeX and EndNote entries for the Mooers 2020 *Protein
Science* paper.  Buttons are provided to copy either format to the
clipboard or save it to a file.

Settings
--------

Configure default file paths, auto-load behavior, AI provider preferences,
and display options.  Settings are persisted via ``QSettings`` and survive
PyMOL restarts.

Links
-----

Curated hyperlinks to documentation, the GitHub repository, and related
resources.

Installation
------------

An optional maintenance panel at the right end of the tab row.  Update the
cached shortcuts library, install the ``psico`` package via conda, detect the
operating system, or point the plugin at a different shortcuts file.  A novice
can ignore this tab, because the bundled shortcuts load automatically on first
launch.


.. _tutorials:

Tutorials
=========

The **Tutorial** tab provides seven self-contained lessons.  Each tutorial
includes explanatory text, the shortcut commands involved, and a **Run
Example** button that executes the commands directly in the PyMOL viewport.

.. list-table::
   :header-rows: 1
   :widths: 5 45 50

   * - #
     - Title
     - Shortcuts covered
   * - 1
     - Getting Started: Fetch and Display a Protein
     - ``fetch``, ``AO``
   * - 2
     - Coloring Shortcuts
     - ``CB``, ``CR``, color-by-chain
   * - 3
     - Symmetry Mates and Crystal Contacts
     - ``SC``, supercell generation
   * - 4
     - Making Publication-Quality Figures
     - ``BW``, ``AO``, ray-tracing settings
   * - 5
     - Working with Electron Density Maps
     - ``emaps``, mesh/surface display
   * - 6
     - Selections and Distances
     - ``SA``, distance measurements
   * - 7
     - Saving and Loading Sessions
     - Session file I/O shortcuts


.. _ai-assistant-details:

AI Assistant
============

The AI Assistant tab implements a lightweight RAG (Retrieval-Augmented
Generation) pipeline so that answers are grounded in the actual content of
``pymolshortcuts.py``.

RAG pipeline
------------

The pipeline consists of five stages:

1. **Load** — The shortcuts file is read into memory.
2. **Chunk** — The text is split into overlapping 500-token chunks
   (100-token overlap) to preserve context across boundaries.
3. **Embed** — Each chunk receives a simple term-frequency embedding vector.
   No external embedding model is required.
4. **Search** — At query time the user's question is embedded and compared to
   every chunk via cosine similarity; the top-*k* chunks are retrieved.
5. **Generate** — The retrieved chunks are prepended to the prompt sent to the
   selected LLM, which generates a context-aware answer.

Timing statistics for each step (file loading, chunking, embedding) are
printed to the status area during indexing.

The AI tab discovers the shortcuts file through the same three-level
fallback chain used by the Shortcuts tab (install-tab path → module-level
path → QSettings path), so it works immediately after a fresh install
without requiring a separate indexing step.

API request format by provider
------------------------------

Claude
~~~~~~

Uses the ``/v1/messages`` endpoint with an ``x-api-key`` header and a
system-prompt instructing the model to answer from the provided shortcut
context.

OpenAI
~~~~~~

Uses the ``/v1/chat/completions`` endpoint with a ``Bearer`` token and the
standard ``messages`` array.

Ollama
~~~~~~

Uses the ``/api/generate`` endpoint on the configured host (default
``http://localhost:11434``) with a prompt string.

Gemini
~~~~~~

Uses the ``generativelanguage.googleapis.com/v1beta`` endpoint with
``systemInstruction`` and ``generationConfig`` fields in the JSON body.

Custom
~~~~~~

Sends an OpenAI-compatible ``/v1/chat/completions`` request to the
user-specified endpoint.  The authentication header name and prefix are
configurable (default: ``Authorization: Bearer <key>``).


.. _class-reference:

Class Reference
===============

The plugin is structured as a set of independent tab classes wired together
by a top-level dialog.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Class
     - Responsibility
   * - ``ShortcutData``
     - Data class holding one shortcut's name, docstring sections, and
       keybinding
   * - ``ShortcutsParser``
     - Static methods for parsing ``pymolshortcuts.py`` into a list of
       ``ShortcutData`` objects
   * - ``InstallationTab``
     - System detection, file download, ``psico`` installation; emits
       ``shortcuts_installed`` signal on success
   * - ``AddShortcutTab``
     - New-shortcut authoring form with code preview and GitHub PR
       submission
   * - ``AIIntegrationTab``
     - RAG engine and five-provider LLM integration
   * - ``HistoryTab``
     - Execution history with persistence, re-execution, and CSV export
   * - ``FavoritesTab``
     - Starred shortcuts organized by category
   * - ``SettingsTab``
     - ``QSettings``-backed preference management
   * - ``TutorialTab``
     - Seven guided tutorials with in-viewport command execution
   * - ``CitationTab``
     - BibTeX and EndNote citation display, clipboard copy, and file save
   * - ``LinksTab``
     - Curated hyperlinks to documentation and resources
   * - ``ShortcutsTableModel``
     - ``QAbstractTableModel`` subclass driving the Shortcuts table view
   * - ``ShortcutsTab``
     - Shortcut browsing, filtering, detail display, and execution
   * - ``PyMOLShortcutsPlugin``
     - Top-level ``QDialog`` that assembles all tabs into a
       ``QTabWidget``; auto-populates the Shortcuts tab on startup via
       ``_auto_populate_shortcuts``


.. _testing:

Testing
=======

The test suite runs entirely without PyMOL or a display server by mocking
``pymol``, ``pymol.cmd``, and ``pymol.Qt`` at the module level.

Prerequisites
-------------

.. code-block:: bash

   pip install pytest pytest-cov

Running the tests
-----------------

Place ``test_pymolshortcuts_manager.py`` and ``pymolshortcuts_manager.py``
in the same directory, then use the provided Makefile:

.. code-block:: bash

   # Full suite
   make test

   # Verbose (one line per test)
   make verbose

   # HTML coverage report
   make coverage

   # Single test
   make single T=TestRAGEngine::test_cosine_similarity_identical

   # Re-run failures
   make failed

   # Lint
   make lint

   # Clean caches
   make clean

Or run directly:

.. code-block:: bash

   python -m pytest test_pymolshortcuts_manager.py -v

Test suite overview
-------------------

The suite contains **295 tests** across **42 test classes**:

.. list-table::
   :header-rows: 1
   :widths: 35 8 57

   * - Test class
     - Tests
     - Coverage
   * - ``TestShortcutData``
     - 3
     - Data class defaults, all fields, keybinding identity
   * - ``TestShortcutsParser``
     - 9
     - Parsing, empty and missing files, docstring extraction
   * - ``TestRAGEngine``
     - 17
     - Chunking, embeddings, cosine similarity, search, file loading
   * - ``TestRAGTimingStatistics``
     - 2
     - Timing output verification during indexing
   * - ``TestAPICallConstruction``
     - 13
     - Request payloads and error handling for all five providers
   * - ``TestAPITestConnections``
     - 4
     - Gemini and Custom test-connection methods
   * - ``TestTutorialTab``
     - 9
     - Tutorial data integrity, display, execution, clipboard
   * - ``TestCitationTab``
     - 18
     - BibTeX and EndNote accuracy, clipboard copy, file save
   * - ``TestHistoryTab``
     - 5
     - Persistence, add and increment, clear, CSV export
   * - ``TestFavoritesTab``
     - 5
     - Add, duplicate detection, remove, persistence
   * - ``TestSettingsTab``
     - 3
     - QSettings save, load, and clear
   * - ``TestShortcutsTableModel``
     - 11
     - Row and column counts, Tags column, data retrieval, description truncation
   * - ``TestPluginDialogAssembly``
     - 8
     - Eleven tab names, tab order, class and method existence
   * - ``TestAddShortcutCodeGeneration``
     - 5
     - Form validation, code generation with docstrings
   * - ``TestInstallationTabDownload``
     - 2
     - GitHub download success and network-error handling
   * - ``TestAutoPopulateShortcuts``
     - 3
     - Module-level, QSettings, and filesystem fallback discovery
   * - ``TestOnShortcutsInstalled``
     - 4
     - QSettings persistence, tab refresh, module-level update
   * - ``TestApplyAppearance``
     - 11
     - Font size, built-in themes, qdarktheme, save and reset paths
   * - ``TestDarkthemeInstallation``
     - 5
     - Detection and pip installation of pyqtdarktheme
   * - ``TestEdgeCases``
     - 5
     - Empty names, long lines, large vectors, UTF-8 content
   * - ``TestVersionAndMetadata``
     - 3
     - Version string, module docstring, author attribution
   * - ``TestHarnessAdapters``
     - 14
     - Argument vectors for Claude Code, Pi, and the generic CLI
   * - ``TestHarnessProcess``
     - 8
     - Line streaming, exit codes, timeout, stdin payload, stop
   * - ``TestHarnessRunner``
     - 9
     - Signal emission on success, failure, timeout, and exception
   * - ``TestSkillRegistry``
     - 11
     - Frontmatter parsing, directory scanning, precedence, install
   * - ``TestAgenticPromptTemplates``
     - 8
     - Template rendering and the retrieval context
   * - ``TestCandidateValidator``
     - 18
     - The static, pytest, and live validation tiers
   * - ``TestAgenticSettings``
     - 7
     - Round trip of every agentic/ key through QSettings
   * - ``TestAgentRunStore``
     - 6
     - Run log add, load, trim, clear, and export
   * - ``TestAgenticIntegration``
     - 11
     - Run directories, backup and append, form prefill, input checks
   * - ``TestMCPServer``
     - 12
     - JSON-RPC surface, tool registry, and the two guarded tools
   * - ``TestShortcutDataTags``
     - 3
     - Tags field defaults, assignment, and normalization on construction
   * - ``TestTagNormalization``
     - 5
     - Lowercasing, whitespace-to-hyphen, deduplication, order preservation
   * - ``TestTagStore``
     - 7
     - Overlay load and save, effective tag set, unknown-tag detection
   * - ``TestTagParsing``
     - 2
     - The ``TAGS:`` docstring marker and the empty-section default
   * - ``TestTagWriteback``
     - 7
     - In-file ``TAGS:`` rewrite, backup, parser round trip, missing shortcut
   * - ``TestTagFilterProxy``
     - 4
     - Tag-membership filtering and the text-filter AND behavior
   * - ``TestTagSettings``
     - 4
     - Round trip of every ``tags/`` key through QSettings
   * - ``TestAddShortcutTags``
     - 2
     - The Tags field and ``TAGS:`` output in generated shortcut code


Mock architecture
-----------------

The test file creates a complete mock hierarchy that replaces the PyMOL and
Qt runtime:

``sys.modules`` injection
   ``pymol``, ``pymol.cmd``, and ``pymol.Qt`` are replaced with
   ``MagicMock`` objects before the plugin module is imported.

``MockQSettings``
   An in-memory dictionary-backed replacement for ``QtCore.QSettings``
   supporting ``value()``, ``setValue()``, ``sync()``, and ``clear()``.

``MockWidget`` / ``MockDialog``
   Minimal stand-ins for ``QWidget`` and ``QDialog`` that satisfy the
   constructor chain without a running Qt event loop.

Dynamic module loading
   The plugin is loaded via ``importlib.util.spec_from_file_location`` so
   that the mocked ``pymol.Qt`` module is already in ``sys.modules`` when
   the top-level imports execute.


Makefile Targets
================

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Target
     - Description
   * - ``make test``
     - Run the full test suite (295 tests, 42 classes)
   * - ``make verbose``
     - Run with verbose output (one line per test)
   * - ``make quiet``
     - Run with minimal output (dot per test)
   * - ``make coverage``
     - Run tests and generate an HTML coverage report in ``htmlcov/``
   * - ``make single T=...``
     - Run a single test (e.g., ``T=TestRAGEngine::test_chunk_text_overlap``)
   * - ``make failed``
     - Re-run only previously failed tests
   * - ``make lint``
     - Check the plugin source for syntax errors
   * - ``make clean``
     - Remove pytest caches, coverage artifacts, and bytecode
   * - ``make help``
     - Display available targets


Project Layout
==============

::

   pymolshortcuts/
   ├── pymolshortcuts_manager.py           # Main plugin source
   ├── test_pymolshortcuts_manager.py     # Test suite (295 tests, 42 classes)
   ├── pymolshortcuts_mcp.py             # Companion MCP server (stdio)
   ├── skills/                           # Bundled skills for the Agentic AI tab
   ├── Makefile                          # Build and test automation
   ├── README.md                         # GitHub README
   ├── CONTRIBUTING.md                   # Contribution guidelines
   ├── SETUP_GUIDE.md                    # Detailed setup instructions
   ├── requirements.txt                  # Python dependencies
   ├── REUSE.toml                        # Machine-readable license declarations
   ├── docs/
   │   ├── index.rst                     # This file
   │   ├── conf.py                       # Sphinx configuration
   │   └── images/                       # Screenshots, licensed CC BY 4.0
   │       ├── LICENSE                   # CC BY 4.0 notice
   │       └── README.md                 # What each screenshot shows
   ├── LICENSE                           # MIT license
   └── pymolshortcuts.py                 # Shortcuts file (downloaded separately)


Citation
========

If you use the PyMOL shortcuts in your work, please cite:

   Mooers, B. H. M. (2020). Shortcuts for faster image creation in PyMOL.
   *Protein Science*, **29**\(1), 268–276.
   DOI: `10.1002/pro.3781 <https://doi.org/10.1002/pro.3781>`_

BibTeX
------

.. code-block:: bibtex

   @Article{Mooers2020ShortcutsForFasterImageCreationInPyMOL,
     author    = {Mooers, Blaine H. M.},
     title     = {Shortcuts for faster image creation in {PyMOL}},
     journal   = {Protein Science},
     year      = {2020},
     volume    = {29},
     number    = {1},
     pages     = {268--276},
     doi       = {10.1002/pro.3781},
     url       = {https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/pro.3781},
   }

EndNote
-------

.. code-block:: text

   %0 Journal Article
   %A Mooers, Blaine H. M.
   %T Shortcuts for faster image creation in PyMOL
   %J Protein Science
   %V 29
   %N 1
   %P 268-276
   %D 2020
   %@ 0961-8368
   %R 10.1002/pro.3781


Contributing
============

Contributions are welcome.  To get started:

1. Fork the repository and create a feature branch.
2. Make your changes.
3. Ensure all tests pass (``make test``).
4. Add new tests for any new functionality.
5. Open a pull request describing what you changed and why.

Coding conventions
------------------

- Follow `PEP 8 <https://peps.python.org/pep-0008/>`_ style guidelines.
- Use ``pymol.Qt`` imports exclusively (never import ``PyQt5`` or ``PyQt6``
  directly) to maintain compatibility with both Qt bindings.
- Keep all GUI code in tab-specific classes that inherit from
  ``QtWidgets.QWidget``.
- Document every new shortcut with a structured docstring containing
  ``DESCRIPTION``, ``USAGE``, ``ARGUMENTS``, ``EXAMPLE``, ``MORE DETAILS``,
  ``VERTICAL PML SCRIPT``, ``HORIZONTAL PML SCRIPT``, and ``PYTHON CODE``
  sections.


Licenses
========

This repository carries two licenses, because software and figures serve
different purposes for a reader.

The software is licensed under the `MIT License <LICENSE>`_.  That covers
``pymolshortcuts_manager.py``, ``pymolshortcuts_mcp.py``, the test suite,
the Makefile, and the bundled skills.

The screenshots in ``docs/images/`` are licensed under `CC BY 4.0
<https://creativecommons.org/licenses/by/4.0/>`_.  You may reuse any of
them in a paper, a talk, a course pack, a textbook, or a grant
application, including a commercial one, provided that you credit the
source, link the license, and say whether you changed the image.  The
notice and the suggested attribution wording are in
``docs/images/LICENSE``, and the full legal code is vendored at the
repository root as ``LICENSE-CC-BY-4.0.txt`` by ``make cc-license``.

Suggested attribution for an unmodified screenshot::

    "PyMOL Shortcuts Manager" screenshot by Blaine Mooers, University of
    Oklahoma Health Campus, licensed under CC BY 4.0.
    https://creativecommons.org/licenses/by/4.0/
    Source: https://github.com/MooersLab/pymolshortcuts-manager

A machine-readable declaration of both licenses is in ``REUSE.toml``.


Acknowledgments
===============

- `PyMOL <https://pymol.org/>`_ by Schrödinger for the molecular-graphics
  engine
- `MooersLab <https://github.com/MooersLab>`_ for the original
  pymolshortcuts collection
- The `psico <https://github.com/speleo3/pymol-psico>`_ package for
  additional PyMOL extensions


Indices and Tables
==================

* :ref:`genindex`
* :ref:`search`

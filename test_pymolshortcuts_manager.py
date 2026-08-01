
# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for PyMOL Shortcuts Manager Plugin
=============================================================

Tests all classes and features of pymolshortcuts_plugins.py using
mock objects to replace PyMOL and PyQt dependencies, so the suite
can run in any standard Python 3 environment (no PyMOL or display
server required).

Run with:
    python -m pytest test_pymolshortcuts_plugin.py -v

Author: Blaine Mooers
License: MIT
"""

import sys
import os
import ast
import io
import json
import tempfile
import shutil
import time
import re
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock, call
from datetime import datetime

# ---------------------------------------------------------------------------
# Mock the PyMOL and Qt imports BEFORE importing the module under test.
# This allows the test suite to run without PyMOL or a display server.
# ---------------------------------------------------------------------------

# Create a mock Qt module hierarchy that mirrors pymol.Qt
mock_QtWidgets = MagicMock()
mock_QtCore = MagicMock()
mock_QtGui = MagicMock()

# QSettings mock with in-memory storage
class MockQSettings:
    """In-memory QSettings replacement for testing."""
    _store = {}

    def __init__(self, *args, **kwargs):
        pass

    def value(self, key, default=None, type=None):
        val = self._store.get(key, default)
        if type is not None and val is not None:
            try:
                val = type(val)
            except (ValueError, TypeError):
                val = default
        return val

    def setValue(self, key, value):
        self._store[key] = value

    def sync(self):
        pass

    def clear(self):
        self._store.clear()

mock_QtCore.QSettings = MockQSettings
# Each Signal() must be a distinct object, otherwise every signal on every
# class would share one recorder and the emit assertions would be useless.
mock_QtCore.Signal = lambda *a, **kw: MagicMock()


class MockQObject:
    """Minimal QObject stand-in that can actually be subclassed."""

    def __init__(self, parent=None):
        self._parent = parent

    def moveToThread(self, thread):
        self._thread = thread

    def deleteLater(self):
        pass


class MockQThread:
    """Minimal QThread stand-in that runs nothing by itself."""

    def __init__(self, parent=None):
        self.started = MagicMock()
        self._running = False

    def start(self):
        self._running = True

    def quit(self):
        self._running = False

    def wait(self, msec=0):
        return True

    def isRunning(self):
        return self._running


mock_QtCore.QObject = MockQObject
mock_QtCore.QThread = MockQThread
mock_QtCore.Qt = MagicMock()
mock_QtCore.Qt.DisplayRole = 0
mock_QtCore.Qt.Horizontal = 1
mock_QtCore.Qt.CaseInsensitive = 1
mock_QtCore.QModelIndex = MagicMock
mock_QtCore.QAbstractTableModel = type('QAbstractTableModel', (), {
    '__init__': lambda self, *a, **kw: None,
})
mock_QtCore.QSortFilterProxyModel = MagicMock

# Provide realistic widget base classes
class MockWidget:
    """Minimal QWidget stand-in."""
    def __init__(self, parent=None):
        pass
    def setLayout(self, layout):
        pass
    def window(self):
        return MagicMock()
    def setWindowTitle(self, t):
        pass
    def setMinimumSize(self, w, h):
        pass

class MockDialog(MockWidget):
    def accept(self):
        pass
    def exec_(self):
        pass

mock_QtWidgets.QWidget = MockWidget
mock_QtWidgets.QDialog = MockDialog
mock_QtWidgets.QApplication = MagicMock()
mock_QtWidgets.QApplication.processEvents = MagicMock()
mock_QtWidgets.QApplication.clipboard = MagicMock(return_value=MagicMock())
mock_QtWidgets.QVBoxLayout = MagicMock
mock_QtWidgets.QHBoxLayout = MagicMock
mock_QtWidgets.QFormLayout = MagicMock
mock_QtWidgets.QGroupBox = MagicMock
mock_QtWidgets.QLabel = MagicMock
mock_QtWidgets.QLineEdit = MagicMock
mock_QtWidgets.QPushButton = MagicMock
mock_QtWidgets.QRadioButton = MagicMock
mock_QtWidgets.QButtonGroup = MagicMock
mock_QtWidgets.QCheckBox = MagicMock
mock_QtWidgets.QTextEdit = MagicMock
mock_QtWidgets.QTextBrowser = MagicMock
mock_QtWidgets.QComboBox = MagicMock
mock_QtWidgets.QSpinBox = MagicMock
mock_QtWidgets.QTabWidget = MagicMock
mock_QtWidgets.QTableView = MagicMock
mock_QtWidgets.QTableWidget = MagicMock
mock_QtWidgets.QTableWidgetItem = MagicMock
mock_QtWidgets.QListWidget = MagicMock
mock_QtWidgets.QSplitter = MagicMock
mock_QtWidgets.QScrollArea = MagicMock
mock_QtWidgets.QFileDialog = MagicMock
mock_QtWidgets.QInputDialog = MagicMock
mock_QtWidgets.QMessageBox = MagicMock
mock_QtWidgets.QDialogButtonBox = MagicMock
mock_QtWidgets.QAbstractItemView = MagicMock

# Patch pymol and pymol.Qt into sys.modules
sys.modules['pymol'] = MagicMock()
sys.modules['pymol.cmd'] = MagicMock()
sys.modules['pymol.Qt'] = MagicMock(
    QtWidgets=mock_QtWidgets,
    QtCore=mock_QtCore,
    QtGui=mock_QtGui,
)

# Now import the module under test.
# The module-level "from pymol.Qt import ..." will receive our mocks.
import importlib
spec = importlib.util.spec_from_file_location(
    "pymolshortcuts_manager",
    os.path.join(os.path.dirname(__file__), "pymolshortcuts_manager.py"),
)

# We need the source on disk next to this test file OR in uploads.
_plugin_candidates = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "pymolshortcuts_manager.py"),
    os.path.join(os.getcwd(), "pymolshortcuts_manager.py"),
]
_plugin_path = None
for _p in _plugin_candidates:
    if os.path.exists(_p):
        _plugin_path = _p
        break

if _plugin_path is None:
    raise FileNotFoundError(
        "Cannot locate pymolshortcuts_manager.py for testing. "
        f"Searched: {_plugin_candidates}"
    )

spec = importlib.util.spec_from_file_location("pymolshortcuts_manager", _plugin_path)
plugin_mod = importlib.util.module_from_spec(spec)

# Inject our mocked Qt into the module namespace before exec
plugin_mod.QtWidgets = mock_QtWidgets
plugin_mod.QtCore = mock_QtCore
plugin_mod.QtGui = mock_QtGui
plugin_mod.cmd = MagicMock()

spec.loader.exec_module(plugin_mod)

# Alias the classes for convenience
ShortcutData = plugin_mod.ShortcutData
ShortcutsParser = plugin_mod.ShortcutsParser
AIIntegrationTab = plugin_mod.AIIntegrationTab

# Agentic AI layer
HarnessConfig = plugin_mod.HarnessConfig
HarnessAdapter = plugin_mod.HarnessAdapter
ClaudeCodeAdapter = plugin_mod.ClaudeCodeAdapter
PIAdapter = plugin_mod.PIAdapter
GenericCLIAdapter = plugin_mod.GenericCLIAdapter
HarnessProcess = plugin_mod.HarnessProcess
HarnessRunner = plugin_mod.HarnessRunner
HarnessResult = plugin_mod.HarnessResult
SkillInfo = plugin_mod.SkillInfo
SkillRegistry = plugin_mod.SkillRegistry
CandidateValidator = plugin_mod.CandidateValidator
AgentRunStore = plugin_mod.AgentRunStore
AgenticAITab = plugin_mod.AgenticAITab
get_harness_adapter = plugin_mod.get_harness_adapter
agentic_render = plugin_mod.agentic_render
agentic_run_dir = plugin_mod.agentic_run_dir
agentic_append_to_shortcuts = plugin_mod.agentic_append_to_shortcuts


# ===================================================================
# Helper: create a realistic pymolshortcuts.py stub for parser tests
# ===================================================================

SAMPLE_SHORTCUTS_PY = """\
from pymol import cmd

def AO():
    '''
    DESCRIPTION:
    Ambient occlusion rendering for publication-quality images.

    USAGE:
    AO

    ARGUMENTS:
    None

    EXAMPLE:
    AO

    MORE DETAILS:
    Sets ambient occlusion parameters for soft shadows.

    VERTICAL PML SCRIPT:
    set ray_trace_mode, 0
    set ambient, 0.4

    HORIZONTAL PML SCRIPT:
    set ray_trace_mode, 0; set ambient, 0.4

    PYTHON CODE:
    cmd.set('ray_trace_mode', 0)
    cmd.set('ambient', 0.4)
    '''
    cmd.set('ray_trace_mode', 0)
    cmd.set('ambient', 0.4)
cmd.extend('AO', AO)


def BW():
    '''
    DESCRIPTION:
    Black and white rendering for journal figures.

    USAGE:
    BW

    ARGUMENTS:
    None

    EXAMPLE:
    BW

    VERTICAL PML SCRIPT:
    set ray_trace_mode, 1

    HORIZONTAL PML SCRIPT:
    set ray_trace_mode, 1

    PYTHON CODE:
    cmd.set('ray_trace_mode', 1)
    '''
    cmd.set('ray_trace_mode', 1)
cmd.extend('BW', BW)


def CB():
    '''
    DESCRIPTION:
    Color by B-factor with rainbow gradient.

    USAGE:
    CB

    ARGUMENTS:
    None

    EXAMPLE:
    CB

    VERTICAL PML SCRIPT:
    spectrum b

    HORIZONTAL PML SCRIPT:
    spectrum b

    PYTHON CODE:
    cmd.spectrum('b')
    '''
    cmd.spectrum('b')
cmd.extend('CB', CB)


def noDocFunc():
    pass
cmd.extend('noDocFunc', noDocFunc)
"""


# ===================================================================
# 1. ShortcutData tests
# ===================================================================

class TestShortcutData(unittest.TestCase):
    """Test the ShortcutData data class."""

    def test_default_values(self):
        s = ShortcutData(name="AO")
        self.assertEqual(s.name, "AO")
        self.assertEqual(s.keybinding, "AO")
        self.assertEqual(s.description, "")
        self.assertEqual(s.usage, "")
        self.assertEqual(s.pml_vertical, "")
        self.assertEqual(s.pml_horizontal, "")
        self.assertEqual(s.python_code, "")

    def test_all_fields(self):
        s = ShortcutData(
            name="CB",
            description="Color by B-factor",
            usage="CB",
            arguments="None",
            example="CB",
            details="Applies rainbow",
            pml_vertical="spectrum b",
            pml_horizontal="spectrum b",
            python_code="cmd.spectrum('b')",
        )
        self.assertEqual(s.description, "Color by B-factor")
        self.assertEqual(s.pml_horizontal, "spectrum b")

    def test_keybinding_equals_name(self):
        s = ShortcutData(name="FOO")
        self.assertEqual(s.keybinding, s.name)


# ===================================================================
# 2. ShortcutsParser tests
# ===================================================================

class TestShortcutsParser(unittest.TestCase):
    """Test parsing of pymolshortcuts.py files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sample_path = os.path.join(self.tmpdir, "pymolshortcuts.py")
        with open(self.sample_path, 'w') as f:
            f.write(SAMPLE_SHORTCUTS_PY)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_parse_returns_list(self):
        result = ShortcutsParser.parse_shortcuts(self.sample_path)
        self.assertIsInstance(result, list)

    def test_parses_expected_count(self):
        """Should find AO, BW, CB (noDocFunc has no docstring sections)."""
        result = ShortcutsParser.parse_shortcuts(self.sample_path)
        names = [s.name for s in result]
        self.assertIn("AO", names)
        self.assertIn("BW", names)
        self.assertIn("CB", names)
        # noDocFunc should NOT appear because it has no DESCRIPTION section
        self.assertNotIn("noDocFunc", names)

    def test_parsed_shortcut_description(self):
        result = ShortcutsParser.parse_shortcuts(self.sample_path)
        ao = [s for s in result if s.name == "AO"][0]
        self.assertIn("Ambient occlusion", ao.description)

    def test_parsed_shortcut_pml_horizontal(self):
        result = ShortcutsParser.parse_shortcuts(self.sample_path)
        ao = [s for s in result if s.name == "AO"][0]
        self.assertIn("set ray_trace_mode, 0", ao.pml_horizontal)

    def test_parsed_shortcut_python_code(self):
        result = ShortcutsParser.parse_shortcuts(self.sample_path)
        ao = [s for s in result if s.name == "AO"][0]
        self.assertIn("cmd.set", ao.python_code)

    def test_nonexistent_file_returns_empty(self):
        result = ShortcutsParser.parse_shortcuts("/nonexistent/path.py")
        self.assertEqual(result, [])

    def test_empty_file_returns_empty(self):
        empty_path = os.path.join(self.tmpdir, "empty.py")
        with open(empty_path, 'w') as f:
            f.write("")
        result = ShortcutsParser.parse_shortcuts(empty_path)
        self.assertEqual(result, [])

    def test_parse_docstring_no_description(self):
        """_parse_docstring returns None when DESCRIPTION is missing."""
        result = ShortcutsParser._parse_docstring("test", "USAGE:\nfoo\n")
        self.assertIsNone(result)

    def test_parse_docstring_with_description(self):
        doc = "DESCRIPTION:\nThis is a test shortcut.\nUSAGE:\ntest\n"
        result = ShortcutsParser._parse_docstring("test", doc)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "test")
        self.assertIn("test shortcut", result.description)


# ===================================================================
# 3. AI Integration Tab – RAG Engine (non-GUI logic)
# ===================================================================

class TestRAGEngine(unittest.TestCase):
    """Test the text chunking, embedding, and search logic in AIIntegrationTab."""

    def setUp(self):
        # Create an AIIntegrationTab with mocked Qt widgets
        with patch.object(AIIntegrationTab, '__init__', lambda self, *a, **kw: None):
            self.ai = AIIntegrationTab.__new__(AIIntegrationTab)
        self.ai.shortcuts_content = ""
        self.ai.shortcuts_chunks = []
        self.ai.chunk_embeddings = []
        # We need to manually assign a mock response_display
        self.ai.response_display = MagicMock()

    # --- chunk_text ---

    def test_chunk_text_single_chunk(self):
        text = "line one\nline two\nline three"
        chunks = self.ai.chunk_text(text, chunk_size=9999, overlap=10)
        self.assertEqual(len(chunks), 1)
        self.assertIn("line one", chunks[0])

    def test_chunk_text_multiple_chunks(self):
        # Each line is ~10 chars; chunk_size=25 should force multiple chunks
        lines = [f"line {i:04d} abcdef" for i in range(20)]
        text = "\n".join(lines)
        chunks = self.ai.chunk_text(text, chunk_size=50, overlap=15)
        self.assertGreater(len(chunks), 1)

    def test_chunk_text_overlap(self):
        """Overlapping chunks should share some content between adjacent chunks."""
        lines = [f"word{i:04d}" for i in range(100)]
        text = "\n".join(lines)
        chunks = self.ai.chunk_text(text, chunk_size=50, overlap=25)
        self.assertGreater(len(chunks), 1)
        # At least one line from the end of chunk 0 should appear in chunk 1
        lines_0 = set(chunks[0].strip().split('\n'))
        lines_1 = set(chunks[1].strip().split('\n'))
        overlap = lines_0 & lines_1
        self.assertGreater(len(overlap), 0, "Adjacent chunks should share overlapping lines")

    def test_chunk_text_empty_string(self):
        chunks = self.ai.chunk_text("", chunk_size=100, overlap=10)
        # Should return one chunk with the empty content or empty list
        self.assertIsInstance(chunks, list)

    # --- simple_embedding ---

    def test_simple_embedding_basic(self):
        emb = self.ai.simple_embedding("hello world hello")
        self.assertIsInstance(emb, dict)
        self.assertEqual(emb.get("hello"), 2)
        self.assertEqual(emb.get("world"), 1)

    def test_simple_embedding_filters_short_words(self):
        emb = self.ai.simple_embedding("I am a an the set")
        # Words with len <= 2 should be excluded
        self.assertNotIn("I", emb)
        self.assertNotIn("am", emb)
        self.assertNotIn("a", emb)
        self.assertNotIn("an", emb)
        self.assertEqual(emb.get("the"), 1)  # len == 3, included
        self.assertEqual(emb.get("set"), 1)

    def test_simple_embedding_case_insensitive(self):
        emb = self.ai.simple_embedding("PyMOL pymol PYMOL")
        self.assertEqual(emb.get("pymol"), 3)

    def test_simple_embedding_empty_string(self):
        emb = self.ai.simple_embedding("")
        self.assertEqual(emb, {})

    # --- cosine_similarity ---

    def test_cosine_similarity_identical(self):
        vec = {"alpha": 3, "beta": 2}
        sim = self.ai.cosine_similarity(vec, vec)
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_cosine_similarity_orthogonal(self):
        vec1 = {"alpha": 1}
        vec2 = {"beta": 1}
        sim = self.ai.cosine_similarity(vec1, vec2)
        self.assertAlmostEqual(sim, 0.0)

    def test_cosine_similarity_partial_overlap(self):
        vec1 = {"alpha": 1, "beta": 1}
        vec2 = {"beta": 1, "gamma": 1}
        sim = self.ai.cosine_similarity(vec1, vec2)
        self.assertGreater(sim, 0.0)
        self.assertLess(sim, 1.0)

    def test_cosine_similarity_empty_vectors(self):
        self.assertAlmostEqual(self.ai.cosine_similarity({}, {}), 0.0)
        self.assertAlmostEqual(self.ai.cosine_similarity({"a": 1}, {}), 0.0)

    # --- search_chunks ---

    def test_search_chunks_no_index(self):
        """Returns empty list when no chunks are indexed."""
        result = self.ai.search_chunks("test query")
        self.assertEqual(result, [])

    def test_search_chunks_returns_relevant(self):
        self.ai.shortcuts_chunks = [
            "This shortcut colors by B-factor temperature",
            "This shortcut generates symmetry mates crystal",
            "This shortcut sets ambient occlusion rendering",
        ]
        self.ai.chunk_embeddings = [
            self.ai.simple_embedding(c) for c in self.ai.shortcuts_chunks
        ]
        results = self.ai.search_chunks("color B-factor", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertIn("B-factor", results[0])

    def test_search_chunks_top_k(self):
        self.ai.shortcuts_chunks = [f"chunk number {i}" for i in range(10)]
        self.ai.chunk_embeddings = [
            self.ai.simple_embedding(c) for c in self.ai.shortcuts_chunks
        ]
        results = self.ai.search_chunks("chunk number", top_k=3)
        self.assertEqual(len(results), 3)

    # --- load_shortcuts_file ---

    def test_load_shortcuts_file_success(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("# shortcuts content\ndef AO(): pass\n")
            tmppath = f.name
        try:
            ok = self.ai.load_shortcuts_file(tmppath)
            self.assertTrue(ok)
            self.assertIn("def AO", self.ai.shortcuts_content)
        finally:
            os.unlink(tmppath)

    def test_load_shortcuts_file_missing(self):
        ok = self.ai.load_shortcuts_file("/nonexistent/file.py")
        self.assertFalse(ok)


# ===================================================================
# 4. AI Integration Tab – RAG Timing Statistics
# ===================================================================

class TestRAGTimingStatistics(unittest.TestCase):
    """Verify that the index_shortcuts method reports timing data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sample_path = os.path.join(self.tmpdir, "pymolshortcuts.py")
        with open(self.sample_path, 'w') as f:
            f.write(SAMPLE_SHORTCUTS_PY)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_index_shortcuts_reports_timing(self):
        """index_shortcuts should append timing statistics to response_display."""
        with patch.object(AIIntegrationTab, '__init__', lambda self, *a, **kw: None):
            ai = AIIntegrationTab.__new__(AIIntegrationTab)
        ai.shortcuts_content = ""
        ai.shortcuts_chunks = []
        ai.chunk_embeddings = []

        # Track all text appended to the display
        appended = []
        mock_display = MagicMock()
        mock_display.clear = MagicMock()
        mock_display.append = lambda text: appended.append(text)
        ai.response_display = mock_display

        # Mock the window to return install_tab with our sample path
        mock_window = MagicMock()
        mock_window.install_tab.last_installed_path = self.sample_path
        ai.window = MagicMock(return_value=mock_window)

        ai.index_shortcuts()

        full_output = "\n".join(appended)

        # Should contain timing keywords
        self.assertIn("File loading:", full_output)
        self.assertIn("Chunking:", full_output)
        self.assertIn("Embedding:", full_output)
        self.assertIn("RAG Indexing Statistics", full_output)
        self.assertIn("Total time:", full_output)
        self.assertIn("Chunks created:", full_output)
        self.assertIn("Avg chunk size:", full_output)
        self.assertIn("Vocabulary size:", full_output)
        self.assertIn("Ready to answer questions!", full_output)

    def test_index_shortcuts_creates_chunks(self):
        """After indexing, chunks and embeddings should be populated."""
        with patch.object(AIIntegrationTab, '__init__', lambda self, *a, **kw: None):
            ai = AIIntegrationTab.__new__(AIIntegrationTab)
        ai.shortcuts_content = ""
        ai.shortcuts_chunks = []
        ai.chunk_embeddings = []
        ai.response_display = MagicMock()

        mock_window = MagicMock()
        mock_window.install_tab.last_installed_path = self.sample_path
        ai.window = MagicMock(return_value=mock_window)

        ai.index_shortcuts()

        self.assertGreater(len(ai.shortcuts_chunks), 0)
        self.assertEqual(len(ai.shortcuts_chunks), len(ai.chunk_embeddings))


# ===================================================================
# 5. AI Integration Tab – API Call Construction
# ===================================================================

class TestAPICallConstruction(unittest.TestCase):
    """Test that API call methods construct correct request payloads."""

    def _make_ai_tab(self):
        with patch.object(AIIntegrationTab, '__init__', lambda self, *a, **kw: None):
            ai = AIIntegrationTab.__new__(AIIntegrationTab)
        ai.shortcuts_content = ""
        ai.shortcuts_chunks = []
        ai.chunk_embeddings = []
        ai.response_display = MagicMock()
        return ai

    # --- Claude ---

    @patch('urllib.request.urlopen')
    def test_call_claude_api_success(self, mock_urlopen):
        ai = self._make_ai_tab()
        ai.claude_api_key = MagicMock()
        ai.claude_api_key.text.return_value = "sk-ant-test123"
        ai.claude_model = MagicMock()
        ai.claude_model.currentText.return_value = "claude-sonnet-4-20250514"
        ai.claude_max_tokens = MagicMock()
        ai.claude_max_tokens.value.return_value = 500

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "content": [{"text": "Test response from Claude"}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        result = ai.call_claude_api("What is AO?", "context about AO")
        self.assertEqual(result, "Test response from Claude")

        # Verify the request was constructed correctly
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.get_header("X-api-key"), "sk-ant-test123")

    def test_call_claude_api_no_key(self):
        ai = self._make_ai_tab()
        ai.claude_api_key = MagicMock()
        ai.claude_api_key.text.return_value = ""
        with self.assertRaises(Exception) as ctx:
            ai.call_claude_api("query", "context")
        self.assertIn("API key", str(ctx.exception))

    # --- OpenAI ---

    @patch('urllib.request.urlopen')
    def test_call_openai_api_success(self, mock_urlopen):
        ai = self._make_ai_tab()
        ai.openai_api_key = MagicMock()
        ai.openai_api_key.text.return_value = "sk-test"
        ai.openai_model = MagicMock()
        ai.openai_model.currentText.return_value = "gpt-4o"
        ai.openai_max_tokens = MagicMock()
        ai.openai_max_tokens.value.return_value = 500

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "OpenAI response"}}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        result = ai.call_openai_api("query", "context")
        self.assertEqual(result, "OpenAI response")

    def test_call_openai_api_no_key(self):
        ai = self._make_ai_tab()
        ai.openai_api_key = MagicMock()
        ai.openai_api_key.text.return_value = ""
        with self.assertRaises(Exception):
            ai.call_openai_api("query", "context")

    # --- Ollama ---

    @patch('urllib.request.urlopen')
    def test_call_ollama_api_success(self, mock_urlopen):
        ai = self._make_ai_tab()
        ai.ollama_endpoint = MagicMock()
        ai.ollama_endpoint.text.return_value = "http://localhost:11434"
        ai.ollama_model = MagicMock()
        ai.ollama_model.text.return_value = "qwen2.5:7b"
        ai.ollama_max_tokens = MagicMock()
        ai.ollama_max_tokens.value.return_value = 500

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "response": "Ollama response"
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        result = ai.call_ollama_api("query", "context")
        self.assertEqual(result, "Ollama response")

    def test_call_ollama_api_no_config(self):
        ai = self._make_ai_tab()
        ai.ollama_endpoint = MagicMock()
        ai.ollama_endpoint.text.return_value = ""
        ai.ollama_model = MagicMock()
        ai.ollama_model.text.return_value = ""
        with self.assertRaises(Exception):
            ai.call_ollama_api("query", "context")

    # --- Gemini ---

    @patch('urllib.request.urlopen')
    def test_call_gemini_api_success(self, mock_urlopen):
        ai = self._make_ai_tab()
        ai.gemini_api_key = MagicMock()
        ai.gemini_api_key.text.return_value = "AIza_test_key"
        ai.gemini_model = MagicMock()
        ai.gemini_model.currentText.return_value = "gemini-2.0-flash"
        ai.gemini_max_tokens = MagicMock()
        ai.gemini_max_tokens.value.return_value = 500

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "Gemini response"}]}}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        result = ai.call_gemini_api("query", "context")
        self.assertEqual(result, "Gemini response")

        # Verify URL contains model and key
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertIn("gemini-2.0-flash", req.full_url)
        self.assertIn("AIza_test_key", req.full_url)

    def test_call_gemini_api_no_key(self):
        ai = self._make_ai_tab()
        ai.gemini_api_key = MagicMock()
        ai.gemini_api_key.text.return_value = ""
        with self.assertRaises(Exception) as ctx:
            ai.call_gemini_api("query", "context")
        self.assertIn("API key", str(ctx.exception))

    @patch('urllib.request.urlopen')
    def test_gemini_request_payload_structure(self, mock_urlopen):
        """Verify the Gemini request body matches the expected API format."""
        ai = self._make_ai_tab()
        ai.gemini_api_key = MagicMock()
        ai.gemini_api_key.text.return_value = "AIza_key"
        ai.gemini_model = MagicMock()
        ai.gemini_model.currentText.return_value = "gemini-1.5-pro"
        ai.gemini_max_tokens = MagicMock()
        ai.gemini_max_tokens.value.return_value = 1000

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        ai.call_gemini_api("test", "ctx")

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode('utf-8'))
        self.assertIn("contents", body)
        self.assertIn("systemInstruction", body)
        self.assertIn("generationConfig", body)
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 1000)

    # --- Custom API ---

    @patch('urllib.request.urlopen')
    def test_call_custom_api_success(self, mock_urlopen):
        ai = self._make_ai_tab()
        ai.custom_endpoint = MagicMock()
        ai.custom_endpoint.text.return_value = "https://api.deepseek.com/v1/chat/completions"
        ai.custom_api_key = MagicMock()
        ai.custom_api_key.text.return_value = "dsk-test-key"
        ai.custom_model = MagicMock()
        ai.custom_model.text.return_value = "deepseek-chat"
        ai.custom_auth_header = MagicMock()
        ai.custom_auth_header.text.return_value = "Authorization"
        ai.custom_auth_prefix = MagicMock()
        ai.custom_auth_prefix.text.return_value = "Bearer "
        ai.custom_max_tokens = MagicMock()
        ai.custom_max_tokens.value.return_value = 500

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Custom API response"}}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        result = ai.call_custom_api("query", "context")
        self.assertEqual(result, "Custom API response")

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer dsk-test-key")

    @patch('urllib.request.urlopen')
    def test_call_custom_api_no_auth(self, mock_urlopen):
        """Custom API with no API key should still work (e.g., local vLLM)."""
        ai = self._make_ai_tab()
        ai.custom_endpoint = MagicMock()
        ai.custom_endpoint.text.return_value = "http://localhost:8000/v1/chat/completions"
        ai.custom_api_key = MagicMock()
        ai.custom_api_key.text.return_value = ""  # No key
        ai.custom_model = MagicMock()
        ai.custom_model.text.return_value = "local-model"
        ai.custom_auth_header = MagicMock()
        ai.custom_auth_header.text.return_value = "Authorization"
        ai.custom_auth_prefix = MagicMock()
        ai.custom_auth_prefix.text.return_value = "Bearer "
        ai.custom_max_tokens = MagicMock()
        ai.custom_max_tokens.value.return_value = 300

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Local model response"}}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        result = ai.call_custom_api("query", "context")
        self.assertEqual(result, "Local model response")

        # Authorization header should NOT be set
        req = mock_urlopen.call_args[0][0]
        self.assertIsNone(req.get_header("Authorization"))

    def test_call_custom_api_no_endpoint(self):
        ai = self._make_ai_tab()
        ai.custom_endpoint = MagicMock()
        ai.custom_endpoint.text.return_value = ""
        ai.custom_api_key = MagicMock()
        ai.custom_api_key.text.return_value = ""
        ai.custom_model = MagicMock()
        ai.custom_model.text.return_value = "model"
        ai.custom_auth_header = MagicMock()
        ai.custom_auth_header.text.return_value = "Authorization"
        ai.custom_auth_prefix = MagicMock()
        ai.custom_auth_prefix.text.return_value = "Bearer "
        with self.assertRaises(Exception) as ctx:
            ai.call_custom_api("query", "context")
        self.assertIn("endpoint", str(ctx.exception).lower())

    def test_call_custom_api_no_model(self):
        ai = self._make_ai_tab()
        ai.custom_endpoint = MagicMock()
        ai.custom_endpoint.text.return_value = "http://localhost:8000"
        ai.custom_api_key = MagicMock()
        ai.custom_api_key.text.return_value = ""
        ai.custom_model = MagicMock()
        ai.custom_model.text.return_value = ""
        ai.custom_auth_header = MagicMock()
        ai.custom_auth_header.text.return_value = "Authorization"
        ai.custom_auth_prefix = MagicMock()
        ai.custom_auth_prefix.text.return_value = "Bearer "
        with self.assertRaises(Exception) as ctx:
            ai.call_custom_api("query", "context")
        self.assertIn("model", str(ctx.exception).lower())


# ===================================================================
# 6. AI Integration Tab – Test Connection Methods
# ===================================================================

class TestAPITestConnections(unittest.TestCase):
    """Test the test_* connection methods for each provider."""

    def _make_ai_tab(self):
        with patch.object(AIIntegrationTab, '__init__', lambda self, *a, **kw: None):
            ai = AIIntegrationTab.__new__(AIIntegrationTab)
        ai.response_display = MagicMock()
        return ai

    @patch('urllib.request.urlopen')
    def test_test_gemini_success(self, mock_urlopen):
        ai = self._make_ai_tab()
        ai.gemini_api_key = MagicMock()
        ai.gemini_api_key.text.return_value = "AIza_key"
        ai.gemini_model = MagicMock()
        ai.gemini_model.currentText.return_value = "gemini-2.0-flash"

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "Connection successful!"}]}}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        result = ai.test_gemini()
        self.assertEqual(result, "Connection successful!")

    def test_test_gemini_no_key(self):
        ai = self._make_ai_tab()
        ai.gemini_api_key = MagicMock()
        ai.gemini_api_key.text.return_value = ""
        with self.assertRaises(Exception):
            ai.test_gemini()

    @patch('urllib.request.urlopen')
    def test_test_custom_success(self, mock_urlopen):
        ai = self._make_ai_tab()
        ai.custom_endpoint = MagicMock()
        ai.custom_endpoint.text.return_value = "http://localhost:8000/v1/chat/completions"
        ai.custom_api_key = MagicMock()
        ai.custom_api_key.text.return_value = "key"
        ai.custom_model = MagicMock()
        ai.custom_model.text.return_value = "model"
        ai.custom_auth_header = MagicMock()
        ai.custom_auth_header.text.return_value = "Authorization"
        ai.custom_auth_prefix = MagicMock()
        ai.custom_auth_prefix.text.return_value = "Bearer "

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Connection successful!"}}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        result = ai.test_custom()
        self.assertEqual(result, "Connection successful!")

    def test_test_custom_no_config(self):
        ai = self._make_ai_tab()
        ai.custom_endpoint = MagicMock()
        ai.custom_endpoint.text.return_value = ""
        ai.custom_model = MagicMock()
        ai.custom_model.text.return_value = ""
        with self.assertRaises(Exception):
            ai.test_custom()


# ===================================================================
# 7. Tutorial Tab
# ===================================================================

class TestTutorialTab(unittest.TestCase):
    """Test TutorialTab data integrity and behaviour."""

    def setUp(self):
        TutorialTab = plugin_mod.TutorialTab
        with patch.object(TutorialTab, '__init__', lambda self, *a, **kw: None):
            self.tab = TutorialTab.__new__(TutorialTab)
        self.tab.tutorials = []
        self.tab.tutorial_list = MagicMock()
        self.tab.tutorial_browser = MagicMock()
        self.tab._build_tutorials()

    def test_tutorials_not_empty(self):
        self.assertGreater(len(self.tab.tutorials), 0)

    def test_tutorials_have_required_keys(self):
        for t in self.tab.tutorials:
            self.assertIn("title", t)
            self.assertIn("description", t)
            self.assertIn("steps", t)
            self.assertIn("commands", t)
            self.assertIsInstance(t["steps"], list)
            self.assertIsInstance(t["commands"], list)
            self.assertGreater(len(t["steps"]), 0)
            self.assertGreater(len(t["commands"]), 0)

    def test_tutorial_count(self):
        """There should be 7 tutorials as defined."""
        self.assertEqual(len(self.tab.tutorials), 7)

    def test_show_tutorial_valid_row(self):
        self.tab.show_tutorial(0)
        self.tab.tutorial_browser.setHtml.assert_called_once()
        html = self.tab.tutorial_browser.setHtml.call_args[0][0]
        self.assertIn(self.tab.tutorials[0]["title"], html)

    def test_show_tutorial_invalid_row_negative(self):
        self.tab.tutorial_browser.reset_mock()
        self.tab.show_tutorial(-1)
        self.tab.tutorial_browser.setHtml.assert_not_called()

    def test_show_tutorial_invalid_row_too_large(self):
        self.tab.tutorial_browser.reset_mock()
        self.tab.show_tutorial(999)
        self.tab.tutorial_browser.setHtml.assert_not_called()

    def test_run_current_example_valid(self):
        """Running a tutorial should call cmd.do for each command."""
        self.tab.tutorial_list.currentRow.return_value = 0
        plugin_mod.cmd.do = MagicMock()
        self.tab.run_current_example()
        expected_calls = len(self.tab.tutorials[0]["commands"])
        self.assertEqual(plugin_mod.cmd.do.call_count, expected_calls)

    def test_run_current_example_invalid_row(self):
        self.tab.tutorial_list.currentRow.return_value = -1
        plugin_mod.cmd.do = MagicMock()
        self.tab.run_current_example()
        plugin_mod.cmd.do.assert_not_called()

    def test_copy_current_commands(self):
        """Copying should place newline-joined commands on the clipboard."""
        self.tab.tutorial_list.currentRow.return_value = 0
        mock_clipboard = MagicMock()
        mock_QtWidgets.QApplication.clipboard.return_value = mock_clipboard
        self.tab.copy_current_commands()
        expected = "\n".join(self.tab.tutorials[0]["commands"])
        mock_clipboard.setText.assert_called_once_with(expected)


# ===================================================================
# 8. Citation Tab
# ===================================================================

class TestCitationTab(unittest.TestCase):
    """Test CitationTab content accuracy and clipboard operations."""

    def setUp(self):
        CitationTab = plugin_mod.CitationTab
        with patch.object(CitationTab, '__init__', lambda self, *a, **kw: None):
            self.tab = CitationTab.__new__(CitationTab)
        # Simulate the text widgets
        self.bibtex_content = (
            "@Article{Mooers2020ShortcutsForFasterImageCreationInPyMOL,\n"
            "  author    = {Mooers, Blaine HM},\n"
            "  title     = {Shortcuts for faster image creation in PyMOL},\n"
            "  number    = {1},\n"
            "  pages     = {268--276},\n"
            "  volume    = {29},\n"
            "  file      = {:Mooers2020ShortcutsForFasterImageCreationInPyMOL.pdf:PDF},\n"
            "  url       = {https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/pro.3781},\n"
            "  journal   = {Protein Science},\n"
            "  publisher = {Wiley Online Library},\n"
            "  doi       = {10.1002/pro.3781},\n"
            "  year      = {2020},\n"
            "}"
        )
        self.endnote_content = (
            "%0 Journal Article\n"
            "%T Shortcuts for faster image creation in PyMOL\n"
            "%A Mooers, Blaine HM\n"
            "%J Protein Science\n"
            "%V 29\n"
            "%N 1\n"
            "%P 268-276\n"
            "%@ 0961-8368\n"
            "%D 2020\n"
            "%I Wiley Online Library"
        )
        self.tab.bibtex_text = MagicMock()
        self.tab.bibtex_text.toPlainText.return_value = self.bibtex_content
        self.tab.endnote_text = MagicMock()
        self.tab.endnote_text.toPlainText.return_value = self.endnote_content

    # --- BibTeX content correctness ---

    def test_bibtex_contains_article_type(self):
        self.assertIn("@Article{", self.bibtex_content)

    def test_bibtex_contains_author(self):
        self.assertIn("Mooers, Blaine HM", self.bibtex_content)

    def test_bibtex_contains_title(self):
        self.assertIn("Shortcuts for faster image creation in PyMOL", self.bibtex_content)

    def test_bibtex_contains_doi(self):
        self.assertIn("10.1002/pro.3781", self.bibtex_content)

    def test_bibtex_contains_journal(self):
        self.assertIn("Protein Science", self.bibtex_content)

    def test_bibtex_contains_year(self):
        self.assertIn("2020", self.bibtex_content)

    def test_bibtex_contains_volume(self):
        self.assertIn("29", self.bibtex_content)

    def test_bibtex_contains_pages(self):
        self.assertIn("268--276", self.bibtex_content)

    # --- EndNote content correctness ---

    def test_endnote_contains_article_type(self):
        self.assertIn("%0 Journal Article", self.endnote_content)

    def test_endnote_contains_author(self):
        self.assertIn("%A Mooers, Blaine HM", self.endnote_content)

    def test_endnote_contains_title(self):
        self.assertIn("%T Shortcuts for faster image creation in PyMOL", self.endnote_content)

    def test_endnote_contains_year(self):
        self.assertIn("%D 2020", self.endnote_content)

    def test_endnote_contains_issn(self):
        self.assertIn("%@ 0961-8368", self.endnote_content)

    # --- Clipboard operations ---

    def test_copy_bibtex(self):
        mock_clipboard = MagicMock()
        mock_QtWidgets.QApplication.clipboard.return_value = mock_clipboard
        self.tab.copy_bibtex()
        mock_clipboard.setText.assert_called_once_with(self.bibtex_content)

    def test_copy_endnote(self):
        mock_clipboard = MagicMock()
        mock_QtWidgets.QApplication.clipboard.return_value = mock_clipboard
        self.tab.copy_endnote()
        mock_clipboard.setText.assert_called_once_with(self.endnote_content)

    # --- File saving ---

    def _patch_qt_dialogs(self, getSaveFileName_return):
        """Temporarily set QFileDialog.getSaveFileName and ensure QMessageBox works."""
        plugin_mod.QtWidgets.QFileDialog.getSaveFileName = MagicMock(
            return_value=getSaveFileName_return
        )
        plugin_mod.QtWidgets.QMessageBox.information = MagicMock()
        plugin_mod.QtWidgets.QMessageBox.critical = MagicMock()

    def test_save_bibtex_writes_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.bib', delete=False) as f:
            tmppath = f.name
        try:
            self._patch_qt_dialogs((tmppath, "BibTeX Files (*.bib)"))
            self.tab.save_bibtex()
            with open(tmppath, 'r') as f:
                saved = f.read()
            self.assertEqual(saved, self.bibtex_content)
        finally:
            os.unlink(tmppath)

    def test_save_endnote_writes_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.enw', delete=False) as f:
            tmppath = f.name
        try:
            self._patch_qt_dialogs((tmppath, "EndNote Files (*.enw)"))
            self.tab.save_endnote()
            with open(tmppath, 'r') as f:
                saved = f.read()
            self.assertEqual(saved, self.endnote_content)
        finally:
            os.unlink(tmppath)

    def test_save_bibtex_cancelled(self):
        """If user cancels the dialog, no file should be written."""
        self._patch_qt_dialogs(("", ""))
        # Should not raise
        self.tab.save_bibtex()


# ===================================================================
# 9. History Tab
# ===================================================================

class TestHistoryTab(unittest.TestCase):
    """Test HistoryTab persistence and logic."""

    def setUp(self):
        HistoryTab = plugin_mod.HistoryTab
        self.tmpdir = tempfile.mkdtemp()
        with patch.object(HistoryTab, '__init__', lambda self, *a, **kw: None):
            self.tab = HistoryTab.__new__(HistoryTab)
        self.tab.history_file = os.path.join(self.tmpdir, "history.json")
        self.tab.history_data = []
        self.tab.history_table = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_save_and_load(self):
        self.tab.history_data = [
            {"shortcut": "AO", "last_used": "2025-01-01T10:00:00", "count": 3, "arguments": ""}
        ]
        self.tab.save_history()
        self.assertTrue(os.path.exists(self.tab.history_file))

        self.tab.history_data = []
        self.tab.load_history()
        self.assertEqual(len(self.tab.history_data), 1)
        self.assertEqual(self.tab.history_data[0]["shortcut"], "AO")
        self.assertEqual(self.tab.history_data[0]["count"], 3)

    def test_add_new_entry(self):
        self.tab.refresh_display = MagicMock()
        self.tab.add_to_history("BW")
        self.assertEqual(len(self.tab.history_data), 1)
        self.assertEqual(self.tab.history_data[0]["shortcut"], "BW")
        self.assertEqual(self.tab.history_data[0]["count"], 1)

    def test_add_existing_increments_count(self):
        self.tab.refresh_display = MagicMock()
        self.tab.add_to_history("CB")
        self.tab.add_to_history("CB")
        self.tab.add_to_history("CB")
        self.assertEqual(len(self.tab.history_data), 1)
        self.assertEqual(self.tab.history_data[0]["count"], 3)

    def test_clear_history(self):
        self.tab.refresh_display = MagicMock()
        self.tab.add_to_history("AO")
        self.tab.add_to_history("BW")
        self.tab.history_data = []
        self.tab.save_history()
        self.tab.load_history()
        self.assertEqual(len(self.tab.history_data), 0)

    def test_export_history_csv(self):
        self.tab.refresh_display = MagicMock()
        self.tab.add_to_history("AO", arguments="sel1")
        csv_path = os.path.join(self.tmpdir, "export.csv")
        plugin_mod.QtWidgets.QFileDialog.getSaveFileName = MagicMock(
            return_value=(csv_path, "CSV Files (*.csv)")
        )
        plugin_mod.QtWidgets.QMessageBox.information = MagicMock()
        plugin_mod.QtWidgets.QMessageBox.critical = MagicMock()
        self.tab.export_history()
        with open(csv_path, 'r') as f:
            content = f.read()
        self.assertIn("Shortcut,Last Used,Times Used,Arguments", content)
        self.assertIn("AO", content)


# ===================================================================
# 10. Favorites Tab
# ===================================================================

class TestFavoritesTab(unittest.TestCase):
    """Test FavoritesTab persistence and operations."""

    def setUp(self):
        FavoritesTab = plugin_mod.FavoritesTab
        self.tmpdir = tempfile.mkdtemp()
        with patch.object(FavoritesTab, '__init__', lambda self, *a, **kw: None):
            self.tab = FavoritesTab.__new__(FavoritesTab)
        self.tab.favorites_file = os.path.join(self.tmpdir, "favorites.json")
        self.tab.favorites_data = []
        self.tab.favorites_list = MagicMock()
        self.tab.category_filter = MagicMock()
        self.tab.category_filter.findText = MagicMock(return_value=-1)
        self.tab.favorite_changed = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_add_favorite(self):
        result = self.tab.add_favorite("AO", category="Rendering")
        self.assertTrue(result)
        self.assertTrue(self.tab.is_favorite("AO"))

    def test_add_duplicate_favorite(self):
        self.tab.add_favorite("AO")
        result = self.tab.add_favorite("AO")
        self.assertFalse(result)
        self.assertEqual(len(self.tab.favorites_data), 1)

    def test_is_favorite(self):
        self.assertFalse(self.tab.is_favorite("BW"))
        self.tab.add_favorite("BW")
        self.assertTrue(self.tab.is_favorite("BW"))

    def test_remove_favorite_by_name(self):
        self.tab.add_favorite("CB")
        self.assertTrue(self.tab.is_favorite("CB"))
        self.tab.remove_favorite_by_name("CB")
        self.assertFalse(self.tab.is_favorite("CB"))

    def test_save_and_load(self):
        self.tab.add_favorite("AO", category="Rendering")
        self.tab.add_favorite("BW", category="Figures")
        self.tab.save_favorites()

        self.tab.favorites_data = []
        self.tab.load_favorites()
        self.assertEqual(len(self.tab.favorites_data), 2)
        names = [f["shortcut"] for f in self.tab.favorites_data]
        self.assertIn("AO", names)
        self.assertIn("BW", names)


# ===================================================================
# 11. Settings Tab (QSettings mock)
# ===================================================================

class TestSettingsTab(unittest.TestCase):
    """Test that settings are saved and loaded correctly."""

    def setUp(self):
        MockQSettings._store.clear()

    def test_save_and_retrieve(self):
        s = MockQSettings("MooersLab", "Test")
        s.setValue("ai/remember_provider", True)
        s.setValue("history/max_items", 200)

        s2 = MockQSettings("MooersLab", "Test")
        self.assertTrue(s2.value("ai/remember_provider", False, type=bool))
        self.assertEqual(s2.value("history/max_items", 100, type=int), 200)

    def test_defaults(self):
        s = MockQSettings("MooersLab", "Test")
        self.assertEqual(s.value("nonexistent/key", "fallback"), "fallback")
        self.assertFalse(s.value("nonexistent/bool", False, type=bool))

    def test_clear(self):
        s = MockQSettings("MooersLab", "Test")
        s.setValue("key", "value")
        s.clear()
        self.assertIsNone(s.value("key"))


# ===================================================================
# 12. ShortcutsTableModel
# ===================================================================

class TestShortcutsTableModel(unittest.TestCase):
    """Test the table model for shortcuts display."""

    def setUp(self):
        self.shortcuts = [
            ShortcutData(name="AO", description="Ambient occlusion"),
            ShortcutData(name="BW", description="Black and white"),
            ShortcutData(name="CB", description="Color by B-factor"),
        ]
        ShortcutsTableModel = plugin_mod.ShortcutsTableModel
        # The model inherits from our mock QAbstractTableModel
        self.model = ShortcutsTableModel(self.shortcuts)

    def test_row_count(self):
        self.assertEqual(self.model.rowCount(), 3)

    def test_column_count(self):
        self.assertEqual(self.model.columnCount(), 3)

    def test_headers(self):
        self.assertEqual(self.model.headers, ['Name', 'Keybinding', 'Description'])

    def test_get_shortcut_valid(self):
        s = self.model.get_shortcut(0)
        self.assertIsNotNone(s)
        self.assertEqual(s.name, "AO")

    def test_get_shortcut_invalid(self):
        self.assertIsNone(self.model.get_shortcut(-1))
        self.assertIsNone(self.model.get_shortcut(999))

    def test_data_returns_name(self):
        mock_index = MagicMock()
        mock_index.isValid.return_value = True
        mock_index.row.return_value = 1
        mock_index.column.return_value = 0
        result = self.model.data(mock_index, role=0)
        self.assertEqual(result, "BW")

    def test_data_returns_keybinding(self):
        mock_index = MagicMock()
        mock_index.isValid.return_value = True
        mock_index.row.return_value = 2
        mock_index.column.return_value = 1
        result = self.model.data(mock_index, role=0)
        self.assertEqual(result, "CB")

    def test_data_returns_description(self):
        mock_index = MagicMock()
        mock_index.isValid.return_value = True
        mock_index.row.return_value = 0
        mock_index.column.return_value = 2
        result = self.model.data(mock_index, role=0)
        self.assertIn("Ambient occlusion", result)

    def test_data_invalid_index(self):
        mock_index = MagicMock()
        mock_index.isValid.return_value = False
        self.assertIsNone(self.model.data(mock_index, role=0))

    def test_data_truncates_long_description(self):
        long_desc = "A" * 200
        shortcuts = [ShortcutData(name="X", description=long_desc)]
        model = plugin_mod.ShortcutsTableModel(shortcuts)
        mock_index = MagicMock()
        mock_index.isValid.return_value = True
        mock_index.row.return_value = 0
        mock_index.column.return_value = 2
        result = model.data(mock_index, role=0)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), 104)  # 100 + "..."


# ===================================================================
# 13. Main Plugin Dialog Assembly
# ===================================================================

class TestPluginDialogAssembly(unittest.TestCase):
    """Verify that the main dialog creates all expected tabs."""

    def test_tab_names(self):
        """The plugin should register exactly 11 tabs in the expected order."""
        expected = [
            "Installation", "Shortcuts", "Add Shortcut", "AI Assistant",
            "Agentic AI", "History", "Favorites", "Tutorial", "Citation",
            "Settings", "Links",
        ]
        # We cannot easily instantiate the full dialog (too many Qt deps),
        # but we can verify the tab label strings are passed to addTab.
        # Check the source code for the expected calls.
        source_path = _plugin_path
        with open(source_path, 'r') as f:
            src = f.read()
        for name in expected:
            pattern = rf'addTab\(.*"{name}"\)'
            self.assertRegex(src, pattern, f"Tab '{name}' not found in source")

    def test_has_tutorial_tab_class(self):
        self.assertTrue(hasattr(plugin_mod, 'TutorialTab'))

    def test_has_citation_tab_class(self):
        self.assertTrue(hasattr(plugin_mod, 'CitationTab'))

    def test_has_ai_integration_gemini_method(self):
        self.assertTrue(hasattr(AIIntegrationTab, 'call_gemini_api'))
        self.assertTrue(hasattr(AIIntegrationTab, 'test_gemini'))

    def test_has_ai_integration_custom_method(self):
        self.assertTrue(hasattr(AIIntegrationTab, 'call_custom_api'))
        self.assertTrue(hasattr(AIIntegrationTab, 'test_custom'))

    def test_has_agentic_tab_class(self):
        self.assertTrue(hasattr(plugin_mod, 'AgenticAITab'))

    def test_agentic_tab_registered_after_ai_assistant(self):
        with open(_plugin_path, 'r') as f:
            src = f.read()
        ai_index = src.index('addTab(self.ai_tab, "AI Assistant")')
        agentic_index = src.index('addTab(self.agentic_tab, "Agentic AI")')
        history_index = src.index('addTab(self.history_tab, "History")')
        self.assertLess(ai_index, agentic_index)
        self.assertLess(agentic_index, history_index)

    def test_tab_count_is_eleven(self):
        with open(_plugin_path, 'r') as f:
            src = f.read()
        self.assertEqual(src.count('self.tabs.addTab('), 11)


# ===================================================================
# 14. AddShortcutTab – Code Generation
# ===================================================================

class TestAddShortcutCodeGeneration(unittest.TestCase):
    """Test code generation and validation in AddShortcutTab."""

    def setUp(self):
        AddShortcutTab = plugin_mod.AddShortcutTab
        with patch.object(AddShortcutTab, '__init__', lambda self, *a, **kw: None):
            self.tab = AddShortcutTab.__new__(AddShortcutTab)
        self.tab.name_edit = MagicMock()
        self.tab.desc_edit = MagicMock()
        self.tab.usage_edit = MagicMock()
        self.tab.args_edit = MagicMock()
        self.tab.example_edit = MagicMock()
        self.tab.details_edit = MagicMock()
        self.tab.pml_v_edit = MagicMock()
        self.tab.pml_h_edit = MagicMock()
        self.tab.python_edit = MagicMock()
        self.tab.status_text = MagicMock()

    def _fill_required(self):
        self.tab.name_edit.text.return_value = "myShortcut"
        self.tab.desc_edit.toPlainText.return_value = "A test shortcut"
        self.tab.usage_edit.toPlainText.return_value = "myShortcut"
        self.tab.args_edit.toPlainText.return_value = ""
        self.tab.example_edit.toPlainText.return_value = "myShortcut"
        self.tab.details_edit.toPlainText.return_value = ""
        self.tab.pml_v_edit.toPlainText.return_value = ""
        self.tab.pml_h_edit.toPlainText.return_value = ""
        self.tab.python_edit.toPlainText.return_value = (
            "def myShortcut():\n    cmd.do('bg_color white')\ncmd.extend('myShortcut', myShortcut)"
        )

    def test_validate_empty_form(self):
        self.tab.name_edit.text.return_value = ""
        self.tab.desc_edit.toPlainText.return_value = ""
        self.tab.usage_edit.toPlainText.return_value = ""
        self.tab.example_edit.toPlainText.return_value = ""
        self.tab.python_edit.toPlainText.return_value = ""
        errors = self.tab.validate_form()
        self.assertGreater(len(errors), 0)

    def test_validate_invalid_name(self):
        self._fill_required()
        self.tab.name_edit.text.return_value = "123invalid"
        errors = self.tab.validate_form()
        self.assertTrue(any("name" in e.lower() for e in errors))

    def test_validate_valid_form(self):
        self._fill_required()
        errors = self.tab.validate_form()
        self.assertEqual(len(errors), 0)

    def test_generate_code_with_docstring(self):
        self._fill_required()
        code = self.tab.generate_shortcut_code()
        self.assertIsNotNone(code)
        self.assertIn("DESCRIPTION:", code)
        self.assertIn("def myShortcut", code)

    def test_generate_code_no_python(self):
        self._fill_required()
        self.tab.python_edit.toPlainText.return_value = ""
        code = self.tab.generate_shortcut_code()
        self.assertIsNone(code)


# ===================================================================
# 15. InstallationTab – download_from_github
# ===================================================================

class TestInstallationTabDownload(unittest.TestCase):
    """Test the GitHub download logic."""

    def setUp(self):
        InstallationTab = plugin_mod.InstallationTab
        with patch.object(InstallationTab, '__init__', lambda self, *a, **kw: None):
            self.tab = InstallationTab.__new__(InstallationTab)
        self.tab.shortcuts_status = MagicMock()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    @patch('urllib.request.urlopen')
    def test_download_success_with_save(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b"# shortcuts content\ndef AO(): pass\n"
        mock_urlopen.return_value = mock_response

        save_path = os.path.join(self.tmpdir, "shortcuts.py")
        result = self.tab.download_from_github(
            "https://raw.githubusercontent.com/test/test.py",
            save_path=save_path
        )
        self.assertEqual(result, save_path)
        self.assertTrue(os.path.exists(save_path))
        with open(save_path, 'r') as f:
            self.assertIn("def AO", f.read())

    @patch('urllib.request.urlopen')
    def test_download_network_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Network unreachable")
        result = self.tab.download_from_github("https://bad.url/test.py")
        self.assertIsNone(result)


# ===================================================================
# 16. Apply Appearance Tests
# ===================================================================

# ===================================================================
# 16a. Shortcut Persistence Tests
# ===================================================================

class TestAutoPopulateShortcuts(unittest.TestCase):
    """Test that _auto_populate_shortcuts restores shortcuts on startup."""

    def _make_dialog(self):
        """Create a minimal PyMOLShortcutsPlugin mock (bypassing __init__)."""
        Dialog = plugin_mod.PyMOLShortcutsPlugin
        dlg = Dialog.__new__(Dialog)
        dlg.shortcuts_tab = MagicMock()
        dlg.install_tab = MagicMock()
        dlg.settings_tab = MagicMock()
        dlg.agentic_tab = MagicMock()
        dlg.tabs = MagicMock()
        return dlg

    def test_auto_populate_from_global_path(self):
        dlg = self._make_dialog()
        saved = getattr(plugin_mod, '_auto_loaded_shortcuts_path', None)
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"# shortcuts\n")
            tmp = f.name
        try:
            plugin_mod._auto_loaded_shortcuts_path = tmp
            dlg._auto_populate_shortcuts()
            dlg.shortcuts_tab.set_shortcuts_file.assert_called_once_with(tmp)
            self.assertEqual(dlg.install_tab.last_installed_path, tmp)
        finally:
            plugin_mod._auto_loaded_shortcuts_path = saved
            os.unlink(tmp)

    def test_auto_populate_from_qsettings(self):
        dlg = self._make_dialog()
        saved = getattr(plugin_mod, '_auto_loaded_shortcuts_path', None)
        plugin_mod._auto_loaded_shortcuts_path = None
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"# shortcuts\n")
            tmp = f.name
        # Mock QSettings to return the path
        mock_settings = MagicMock()
        mock_settings.value = MagicMock(return_value=tmp)
        orig_qsettings = plugin_mod.QtCore.QSettings
        plugin_mod.QtCore.QSettings = MagicMock(return_value=mock_settings)
        try:
            dlg._auto_populate_shortcuts()
            dlg.shortcuts_tab.set_shortcuts_file.assert_called_once_with(tmp)
        finally:
            plugin_mod._auto_loaded_shortcuts_path = saved
            plugin_mod.QtCore.QSettings = orig_qsettings
            os.unlink(tmp)

    def test_auto_populate_no_file_found(self):
        dlg = self._make_dialog()
        saved = getattr(plugin_mod, '_auto_loaded_shortcuts_path', None)
        plugin_mod._auto_loaded_shortcuts_path = None
        # Mock QSettings to return empty string
        mock_settings = MagicMock()
        mock_settings.value = MagicMock(return_value="")
        orig_qsettings = plugin_mod.QtCore.QSettings
        plugin_mod.QtCore.QSettings = MagicMock(return_value=mock_settings)
        # Patch os.path.exists so the Priority-3 well-known-locations scan
        # does not accidentally find a real pymolshortcuts.py on disk.
        orig_exists = os.path.exists
        plugin_mod.os = MagicMock()
        plugin_mod.os.path.exists = MagicMock(return_value=False)
        plugin_mod.os.path.expanduser = os.path.expanduser
        plugin_mod.os.path.join = os.path.join
        plugin_mod.os.environ = os.environ
        try:
            dlg._auto_populate_shortcuts()
            dlg.shortcuts_tab.set_shortcuts_file.assert_not_called()
        finally:
            plugin_mod._auto_loaded_shortcuts_path = saved
            plugin_mod.QtCore.QSettings = orig_qsettings
            plugin_mod.os = os


class TestOnShortcutsInstalled(unittest.TestCase):
    """Test on_shortcuts_installed persists path and refreshes UI."""

    def _make_dialog(self):
        Dialog = plugin_mod.PyMOLShortcutsPlugin
        dlg = Dialog.__new__(Dialog)
        dlg.shortcuts_tab = MagicMock()
        dlg.install_tab = MagicMock()
        dlg.settings_tab = MagicMock()
        dlg.agentic_tab = MagicMock()
        dlg.tabs = MagicMock()
        return dlg

    def test_persists_path_and_refreshes(self):
        dlg = self._make_dialog()
        saved_global = getattr(plugin_mod, '_auto_loaded_shortcuts_path', None)
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"# shortcuts\n")
            tmp = f.name
        mock_settings = MagicMock()
        orig_qsettings = plugin_mod.QtCore.QSettings
        plugin_mod.QtCore.QSettings = MagicMock(return_value=mock_settings)
        try:
            dlg.on_shortcuts_installed(tmp)
            # Shortcuts tab was refreshed
            dlg.shortcuts_tab.set_shortcuts_file.assert_called_once_with(tmp)
            # Path was persisted to QSettings
            mock_settings.setValue.assert_called_with("shortcuts/default_path", tmp)
            mock_settings.sync.assert_called_once()
            # Settings tab path widget was updated
            dlg.settings_tab.default_shortcuts_path.setText.assert_called_once_with(tmp)
            # Global variable was updated
            self.assertEqual(plugin_mod._auto_loaded_shortcuts_path, tmp)
            # Switched to Shortcuts tab
            dlg.tabs.setCurrentIndex.assert_called_with(1)
        finally:
            plugin_mod._auto_loaded_shortcuts_path = saved_global
            plugin_mod.QtCore.QSettings = orig_qsettings
            os.unlink(tmp)

    def test_ignores_nonexistent_path(self):
        dlg = self._make_dialog()
        dlg.on_shortcuts_installed("/nonexistent/path.py")
        dlg.shortcuts_tab.set_shortcuts_file.assert_not_called()

    def test_ignores_empty_path(self):
        dlg = self._make_dialog()
        dlg.on_shortcuts_installed("")
        dlg.shortcuts_tab.set_shortcuts_file.assert_not_called()

    def test_ignores_none_path(self):
        dlg = self._make_dialog()
        dlg.on_shortcuts_installed(None)
        dlg.shortcuts_tab.set_shortcuts_file.assert_not_called()


# ===================================================================
# 16b. Apply Appearance Tests
# ===================================================================

class TestApplyAppearance(unittest.TestCase):
    """Test SettingsTab.apply_appearance() with built-in and qdarktheme."""

    def _make_tab(self):
        SettingsTab = plugin_mod.SettingsTab
        tab = SettingsTab.__new__(SettingsTab)
        tab.settings = MockQSettings("MooersLab", "Test")
        tab.font_size = MagicMock()
        tab.theme = MagicMock()
        # The Agentic AI group added in 0.2.0 is touched by save_settings
        # and load_settings, so the fixture has to supply it too.
        for widget in ("agentic_harness", "agentic_executable",
                       "agentic_working_dir", "agentic_scratch_dir",
                       "agentic_reference", "agentic_timeout",
                       "agentic_confirm_live", "agentic_skills_dir"):
            setattr(tab, widget, MagicMock())
        tab.agentic_harness.findData = MagicMock(return_value=-1)
        mock_window = MagicMock()
        tab.window = MagicMock(return_value=mock_window)
        return tab, mock_window

    # -- Built-in stylesheet tests --

    def test_dark_theme_sets_stylesheet(self):
        tab, _ = self._make_tab()
        target = MagicMock()
        tab.font_size.value.return_value = 12
        tab.theme.currentText.return_value = "Dark"
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = False
        try:
            tab.apply_appearance(target=target)
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
        target.setStyleSheet.assert_called_once()
        ss = target.setStyleSheet.call_args[0][0]
        self.assertIn("font-size: 12pt", ss)
        self.assertIn("#2b2b2b", ss)

    def test_light_theme_sets_stylesheet(self):
        tab, _ = self._make_tab()
        target = MagicMock()
        tab.font_size.value.return_value = 14
        tab.theme.currentText.return_value = "Light"
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = False
        try:
            tab.apply_appearance(target=target)
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
        ss = target.setStyleSheet.call_args[0][0]
        self.assertIn("font-size: 14pt", ss)
        self.assertIn("#ffffff", ss)

    def test_system_default_font_only(self):
        tab, _ = self._make_tab()
        target = MagicMock()
        tab.font_size.value.return_value = 10
        tab.theme.currentText.return_value = "System Default"
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = False
        try:
            tab.apply_appearance(target=target)
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
        ss = target.setStyleSheet.call_args[0][0]
        self.assertIn("font-size: 10pt", ss)
        self.assertNotIn("#2b2b2b", ss)
        self.assertNotIn("#ffffff", ss)

    def test_window_fallback_when_no_target(self):
        tab, mock_window = self._make_tab()
        tab.font_size.value.return_value = 11
        tab.theme.currentText.return_value = "System Default"
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = False
        try:
            tab.apply_appearance()
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
        mock_window.setStyleSheet.assert_called_once()

    def test_save_settings_calls_apply(self):
        tab, _ = self._make_tab()
        tab._appearance_target = MagicMock()
        tab.font_size.value.return_value = 12
        tab.theme.currentText.return_value = "System Default"
        tab.theme.findText = MagicMock(return_value=-1)
        tab.auto_load = MagicMock()
        tab.auto_load.isChecked.return_value = False
        tab.default_shortcuts_path = MagicMock()
        tab.default_shortcuts_path.text.return_value = ""
        tab.remember_provider = MagicMock()
        tab.remember_provider.isChecked.return_value = False
        tab.ai_provider = MagicMock()
        tab.ai_provider.currentText.return_value = ""
        tab.auto_index = MagicMock()
        tab.auto_index.isChecked.return_value = False
        tab.save_api_keys = MagicMock()
        tab.save_api_keys.isChecked.return_value = False
        tab.enable_history = MagicMock()
        tab.enable_history.isChecked.return_value = True
        tab.max_history = MagicMock()
        tab.max_history.value.return_value = 100
        tab.check_updates = MagicMock()
        tab.check_updates.isChecked.return_value = False
        # Mock the QMessageBox.information call
        plugin_mod.QtWidgets.QMessageBox.information = MagicMock()
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = False
        try:
            tab.save_settings()
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
        tab._appearance_target.setStyleSheet.assert_called_once()

    def test_reset_settings_calls_apply(self):
        tab, _ = self._make_tab()
        tab._appearance_target = MagicMock()
        tab.font_size.value.return_value = 12
        tab.theme.currentText.return_value = "System Default"
        tab.theme.findText = MagicMock(return_value=-1)
        tab.auto_load = MagicMock()
        tab.default_shortcuts_path = MagicMock()
        tab.remember_provider = MagicMock()
        tab.ai_provider = MagicMock()
        tab.auto_index = MagicMock()
        tab.save_api_keys = MagicMock()
        tab.enable_history = MagicMock()
        tab.max_history = MagicMock()
        tab.check_updates = MagicMock()
        tab.font_size.setValue = MagicMock()
        tab.theme.setCurrentIndex = MagicMock()
        # Mock QMessageBox.question to return Yes sentinel
        yes_sentinel = MagicMock()
        plugin_mod.QtWidgets.QMessageBox.Yes = yes_sentinel
        plugin_mod.QtWidgets.QMessageBox.No = MagicMock()
        plugin_mod.QtWidgets.QMessageBox.question = MagicMock(return_value=yes_sentinel)
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = False
        try:
            tab.reset_settings()
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
        tab._appearance_target.setStyleSheet.assert_called_once()

    # -- qdarktheme integration tests --

    def test_qdarktheme_dark_theme(self):
        tab, _ = self._make_tab()
        target = MagicMock()
        tab.font_size.value.return_value = 14
        tab.theme.currentText.return_value = "Dark"
        mock_qdt = MagicMock()
        mock_qdt.load_stylesheet.return_value = "/* qdarktheme dark */"
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = True
        plugin_mod.qdarktheme = mock_qdt
        try:
            tab.apply_appearance(target=target)
            mock_qdt.load_stylesheet.assert_called_once_with("dark")
            ss = target.setStyleSheet.call_args[0][0]
            self.assertIn("qdarktheme dark", ss)
            self.assertIn("font-size: 14pt", ss)
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
            if hasattr(plugin_mod, 'qdarktheme'):
                del plugin_mod.qdarktheme

    def test_qdarktheme_light_theme(self):
        tab, _ = self._make_tab()
        target = MagicMock()
        tab.font_size.value.return_value = 12
        tab.theme.currentText.return_value = "Light"
        mock_qdt = MagicMock()
        mock_qdt.load_stylesheet.return_value = "/* qdarktheme light */"
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = True
        plugin_mod.qdarktheme = mock_qdt
        try:
            tab.apply_appearance(target=target)
            mock_qdt.load_stylesheet.assert_called_once_with("light")
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
            if hasattr(plugin_mod, 'qdarktheme'):
                del plugin_mod.qdarktheme

    def test_qdarktheme_system_default_bypasses(self):
        tab, _ = self._make_tab()
        target = MagicMock()
        tab.font_size.value.return_value = 12
        tab.theme.currentText.return_value = "System Default"
        mock_qdt = MagicMock()
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = True
        plugin_mod.qdarktheme = mock_qdt
        try:
            tab.apply_appearance(target=target)
            mock_qdt.load_stylesheet.assert_not_called()
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
            if hasattr(plugin_mod, 'qdarktheme'):
                del plugin_mod.qdarktheme

    def test_qdarktheme_exception_falls_back(self):
        tab, _ = self._make_tab()
        target = MagicMock()
        tab.font_size.value.return_value = 12
        tab.theme.currentText.return_value = "Dark"
        mock_qdt = MagicMock()
        mock_qdt.load_stylesheet.side_effect = RuntimeError("fail")
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = True
        plugin_mod.qdarktheme = mock_qdt
        try:
            tab.apply_appearance(target=target)
            ss = target.setStyleSheet.call_args[0][0]
            self.assertIn("#2b2b2b", ss)
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved
            if hasattr(plugin_mod, 'qdarktheme'):
                del plugin_mod.qdarktheme

    def test_stored_target_reused_on_second_call(self):
        tab, _ = self._make_tab()
        target = MagicMock()
        tab.font_size.value.return_value = 12
        tab.theme.currentText.return_value = "System Default"
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        plugin_mod.QDARKTHEME_AVAILABLE = False
        try:
            tab.apply_appearance(target=target)
            target.setStyleSheet.reset_mock()
            tab.apply_appearance()
            target.setStyleSheet.assert_called_once()
        finally:
            plugin_mod.QDARKTHEME_AVAILABLE = saved


# ===================================================================
# 17. Dark Theme Installation Tests
# ===================================================================

class TestDarkthemeInstallation(unittest.TestCase):
    """Test InstallationTab check/install for pyqtdarktheme."""

    def setUp(self):
        InstallationTab = plugin_mod.InstallationTab
        with patch.object(InstallationTab, '__init__', lambda self, *a, **kw: None):
            self.tab = InstallationTab.__new__(InstallationTab)
        self.tab.darktheme_status = MagicMock()
        self.tab.darktheme_label = MagicMock()

    def test_check_darktheme_when_installed(self):
        mock_module = MagicMock()
        mock_module.__version__ = "2.1.0"
        mock_module.get_themes = MagicMock(return_value=["dark", "light"])
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        with patch.dict('sys.modules', {'qdarktheme': mock_module}):
            self.tab.check_darktheme()
        self.assertTrue(plugin_mod.QDARKTHEME_AVAILABLE)
        # Status should have been updated with success text
        calls = [str(c) for c in self.tab.darktheme_status.append.call_args_list]
        combined = " ".join(calls)
        self.assertIn("2.1.0", combined)
        self.assertIn("installed", combined.lower())
        plugin_mod.QDARKTHEME_AVAILABLE = saved

    def test_check_darktheme_when_not_installed(self):
        saved = plugin_mod.QDARKTHEME_AVAILABLE
        # Force ImportError by removing any existing qdarktheme module and patching
        with patch.dict('sys.modules', {'qdarktheme': None}):
            # builtins.__import__ will raise ImportError for qdarktheme=None
            self.tab.check_darktheme()
        self.assertFalse(plugin_mod.QDARKTHEME_AVAILABLE)
        calls = [str(c) for c in self.tab.darktheme_status.append.call_args_list]
        combined = " ".join(calls)
        self.assertIn("NOT installed", combined)
        plugin_mod.QDARKTHEME_AVAILABLE = saved

    @patch('subprocess.Popen')
    def test_install_darktheme_success(self, mock_popen):
        mock_process = MagicMock()
        mock_process.stdout = iter(["Collecting pyqtdarktheme\n", "Successfully installed\n"])
        mock_process.stderr = MagicMock()
        mock_process.returncode = 0
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        # Mock QApplication.processEvents
        plugin_mod.QtWidgets.QApplication.processEvents = MagicMock()
        # Mock check_darktheme so it does not do real imports
        self.tab.check_darktheme = MagicMock()

        self.tab.install_darktheme()

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertIn("pip", cmd)
        self.assertIn("pyqtdarktheme", cmd)
        # On success, check_darktheme should be called
        self.tab.check_darktheme.assert_called_once()

    @patch('subprocess.Popen')
    def test_install_darktheme_failure(self, mock_popen):
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.stderr.read.return_value = "ERROR: Could not find package"
        mock_process.returncode = 1
        mock_process.wait.return_value = 1
        mock_popen.return_value = mock_process
        plugin_mod.QtWidgets.QApplication.processEvents = MagicMock()
        self.tab.check_darktheme = MagicMock()

        self.tab.install_darktheme()

        # On failure, check_darktheme should NOT be called
        self.tab.check_darktheme.assert_not_called()
        calls = [str(c) for c in self.tab.darktheme_status.append.call_args_list]
        combined = " ".join(calls)
        self.assertIn("Error", combined)

    @patch('subprocess.Popen')
    def test_install_darktheme_exception(self, mock_popen):
        mock_popen.side_effect = FileNotFoundError("pip not found")
        plugin_mod.QtWidgets.QApplication.processEvents = MagicMock()

        self.tab.install_darktheme()

        calls = [str(c) for c in self.tab.darktheme_status.append.call_args_list]
        combined = " ".join(calls)
        self.assertIn("Error", combined)


# ===================================================================
# 18. Edge Cases and Regression Tests
# ===================================================================

class TestEdgeCases(unittest.TestCase):
    """Miscellaneous edge cases and regressions."""

    def test_shortcut_data_empty_name(self):
        s = ShortcutData(name="")
        self.assertEqual(s.name, "")
        self.assertEqual(s.keybinding, "")

    def test_chunk_text_single_long_line(self):
        with patch.object(AIIntegrationTab, '__init__', lambda self, *a, **kw: None):
            ai = AIIntegrationTab.__new__(AIIntegrationTab)
        text = "A" * 5000
        chunks = ai.chunk_text(text, chunk_size=100, overlap=20)
        # Single line exceeding chunk_size should still appear
        self.assertGreater(len(chunks), 0)
        reconstructed = "".join(chunks)
        self.assertIn("A" * 50, reconstructed)

    def test_cosine_similarity_large_vectors(self):
        with patch.object(AIIntegrationTab, '__init__', lambda self, *a, **kw: None):
            ai = AIIntegrationTab.__new__(AIIntegrationTab)
        vec1 = {f"word{i}": i for i in range(1000)}
        vec2 = {f"word{i}": i for i in range(500, 1500)}
        sim = ai.cosine_similarity(vec1, vec2)
        self.assertGreater(sim, 0.0)
        self.assertLessEqual(sim, 1.0)

    def test_parser_handles_utf8_content(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "test.py")
            with open(path, 'w', encoding='utf-8') as f:
                f.write("""
def unicodeShortcut():
    '''
    DESCRIPTION:
    Shortcut with unicode: αβγδ Å Ångström.

    USAGE:
    unicodeShortcut
    '''
    pass
""")
            result = ShortcutsParser.parse_shortcuts(path)
            self.assertGreater(len(result), 0)
            self.assertIn("αβγδ", result[0].description)
        finally:
            shutil.rmtree(tmpdir)

    def test_multiple_shortcuts_in_one_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "multi.py")
            with open(path, 'w') as f:
                f.write(SAMPLE_SHORTCUTS_PY)
            result = ShortcutsParser.parse_shortcuts(path)
            names = {s.name for s in result}
            self.assertEqual(names, {"AO", "BW", "CB"})
        finally:
            shutil.rmtree(tmpdir)


# ===================================================================
# 17. Version and Metadata
# ===================================================================

class TestVersionAndMetadata(unittest.TestCase):
    """Verify plugin metadata in source."""

    def test_version_string_in_source(self):
        with open(_plugin_path, 'r') as f:
            src = f.read()
        self.assertIn("v3.0", src)

    def test_module_docstring_present(self):
        with open(_plugin_path, 'r') as f:
            src = f.read()
        self.assertIn("PyMOL Shortcuts Manager Plugin", src)

    def test_author_present(self):
        with open(_plugin_path, 'r') as f:
            src = f.read()
        self.assertIn("Blaine Mooers", src)



# ===================================================================
# 18. Agentic AI — harness adapters
# ===================================================================

class FakePopen:
    """Scripted stand-in for subprocess.Popen.

    Class attributes configure the next instance, which keeps the tests
    free of a real child process while still exercising the read loop,
    the stdin handling, and the exit-code path.
    """

    instances = []
    script = []
    returncode_value = 0
    line_delay = 0.0

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 999999
        self.terminated = False
        self.written = []
        self.stdin = self._Stdin(self.written)
        FakePopen.instances.append(self)

    class _Stdin(object):
        """Records writes and survives being closed."""

        def __init__(self, sink):
            self.sink = sink

        def write(self, text):
            self.sink.append(text)

        def flush(self):
            pass

        def close(self):
            pass

        def getvalue(self):
            return "".join(self.sink)

    @property
    def stdout(self):
        def generate():
            for line in FakePopen.script:
                if FakePopen.line_delay:
                    time.sleep(FakePopen.line_delay)
                yield line
        return generate()

    def wait(self):
        return FakePopen.returncode_value

    def terminate(self):
        self.terminated = True

    @classmethod
    def reset(cls, script=None, returncode=0, line_delay=0.0):
        cls.instances = []
        cls.script = list(script or [])
        cls.returncode_value = returncode
        cls.line_delay = line_delay


class TestHarnessAdapters(unittest.TestCase):
    """Argument-vector construction and executable discovery."""

    def test_claude_argv_carries_the_prompt(self):
        adapter = ClaudeCodeAdapter(
            HarnessConfig(harness="claude-code", executable="/bin/claude")
        )
        argv = adapter.run_argv("write a shortcut")
        self.assertEqual(argv[0], "/bin/claude")
        self.assertIn("-p", argv)
        self.assertIn("write a shortcut", argv)

    def test_claude_argv_adds_model_and_permission_mode(self):
        adapter = ClaudeCodeAdapter(HarnessConfig(
            executable="/bin/claude", model="claude-sonnet-4-20250514",
            permission_mode="acceptEdits",
        ))
        argv = adapter.run_argv("go")
        self.assertIn("--model", argv)
        self.assertIn("claude-sonnet-4-20250514", argv)
        self.assertIn("--permission-mode", argv)
        self.assertIn("acceptEdits", argv)

    def test_claude_stream_json_implies_verbose(self):
        adapter = ClaudeCodeAdapter(HarnessConfig(
            executable="/bin/claude", output_format="stream-json"
        ))
        argv = adapter.run_argv("go")
        self.assertIn("--output-format", argv)
        self.assertIn("stream-json", argv)
        self.assertIn("--verbose", argv)

    def test_claude_text_format_adds_no_output_flag(self):
        adapter = ClaudeCodeAdapter(HarnessConfig(
            executable="/bin/claude", output_format="text"
        ))
        self.assertNotIn("--output-format", adapter.run_argv("go"))

    def test_pi_print_mode_is_the_default(self):
        adapter = PIAdapter(HarnessConfig(harness="pi", executable="/bin/pi"))
        argv = adapter.run_argv("go")
        self.assertEqual(argv[:3], ["/bin/pi", "-p", "go"])
        self.assertIn("--no-session", argv)
        self.assertIsNone(adapter.stdin_payload("go"))

    def test_pi_json_mode_sets_the_mode_flag(self):
        adapter = PIAdapter(HarnessConfig(
            harness="pi", executable="/bin/pi", mode="json"
        ))
        argv = adapter.run_argv("go")
        self.assertEqual(argv[:4], ["/bin/pi", "--mode", "json", "-p"])

    def test_pi_rpc_mode_writes_the_prompt_to_stdin(self):
        adapter = PIAdapter(HarnessConfig(
            harness="pi", executable="/bin/pi", mode="rpc"
        ))
        argv = adapter.run_argv("go")
        self.assertEqual(argv[:3], ["/bin/pi", "--mode", "rpc"])
        self.assertNotIn("-p", argv)
        payload = adapter.stdin_payload("go")
        self.assertIsNotNone(payload)
        decoded = json.loads(payload)
        self.assertEqual(decoded["params"]["prompt"], "go")

    def test_pi_passes_provider_and_thinking(self):
        adapter = PIAdapter(HarnessConfig(
            harness="pi", executable="/bin/pi",
            provider="anthropic", thinking="high",
        ))
        argv = adapter.run_argv("go")
        self.assertIn("--provider", argv)
        self.assertIn("anthropic", argv)
        self.assertIn("--thinking", argv)
        self.assertIn("high", argv)

    def test_generic_template_substitutes_every_placeholder(self):
        adapter = GenericCLIAdapter(HarnessConfig(
            harness="generic", executable="/bin/agent",
            argv_template="%EXE% --cwd %CWD% --out %OUTDIR% --model %MODEL% %PROMPT%",
            working_dir="/tmp/work", model="m1",
        ))
        argv = adapter.run_argv("go", output_dir="/tmp/run")
        self.assertEqual(argv, ["/bin/agent", "--cwd", "/tmp/work", "--out",
                                "/tmp/run", "--model", "m1", "go"])

    def test_generic_inlines_skill_bodies(self):
        skill = SkillInfo(name="s1", body="do the thing")
        adapter = GenericCLIAdapter(HarnessConfig(
            harness="generic", executable="/bin/agent",
            argv_template="%EXE% %PROMPT%",
        ))
        argv = adapter.run_argv("go", skills=[skill])
        self.assertIn("do the thing", argv[-1])

    def test_extra_flags_are_split_like_a_shell(self):
        config = HarnessConfig(extra_flags='--flag "two words" -x')
        self.assertEqual(config.extra_flag_list(),
                         ["--flag", "two words", "-x"])

    def test_detect_finds_an_executable_in_an_extra_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "claude")
            with open(fake, 'w') as handle:
                handle.write("#!/bin/sh\n")
            os.chmod(fake, 0o755)
            with patch.object(plugin_mod.shutil, 'which', return_value=None):
                found = ClaudeCodeAdapter.detect(extra_paths=[tmp])
            self.assertEqual(found, fake)

    def test_get_harness_adapter_falls_back_to_generic(self):
        adapter = get_harness_adapter(HarnessConfig(harness="nope"))
        self.assertIsInstance(adapter, GenericCLIAdapter)

    def test_skill_preamble_names_the_selected_skills(self):
        adapter = ClaudeCodeAdapter(HarnessConfig(executable="/bin/claude"))
        preamble = adapter.skill_preamble(
            [SkillInfo(name="a"), SkillInfo(name="b")]
        )
        self.assertIn("a, b", preamble)


# ===================================================================
# 19. Agentic AI — HarnessProcess and HarnessRunner
# ===================================================================

class TestHarnessProcess(unittest.TestCase):
    """The Qt-free process wrapper."""

    def setUp(self):
        FakePopen.reset(script=["one\n", "two\n"])
        self.adapter = ClaudeCodeAdapter(
            HarnessConfig(executable="/bin/claude", timeout=30)
        )

    def test_run_collects_every_line(self):
        process = HarnessProcess(self.adapter, "go")
        with patch.object(plugin_mod.subprocess, 'Popen', FakePopen):
            result = process.run()
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "one\ntwo")

    def test_run_invokes_the_line_callback(self):
        seen = []
        process = HarnessProcess(self.adapter, "go")
        with patch.object(plugin_mod.subprocess, 'Popen', FakePopen):
            process.run(on_line=seen.append)
        self.assertEqual(seen, ["one", "two"])

    def test_non_zero_exit_is_not_ok(self):
        FakePopen.reset(script=["boom\n"], returncode=2)
        process = HarnessProcess(self.adapter, "go")
        with patch.object(plugin_mod.subprocess, 'Popen', FakePopen):
            result = process.run()
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(result.ok)

    def test_a_missing_executable_is_reported_not_raised(self):
        def explode(*args, **kwargs):
            raise OSError("No such file")
        process = HarnessProcess(self.adapter, "go")
        with patch.object(plugin_mod.subprocess, 'Popen', explode):
            result = process.run()
        self.assertFalse(result.ok)
        self.assertIn("No such file", result.error)

    def test_timeout_marks_the_result(self):
        FakePopen.reset(script=["slow\n", "slower\n"], line_delay=0.25)
        process = HarnessProcess(self.adapter, "go", timeout=0.05)
        with patch.object(plugin_mod.subprocess, 'Popen', FakePopen), \
                patch.object(os, 'killpg'), \
                patch.object(os, 'getpgid', return_value=1):
            result = process.run()
        self.assertTrue(result.timed_out)

    def test_rpc_payload_reaches_stdin(self):
        adapter = PIAdapter(HarnessConfig(
            harness="pi", executable="/bin/pi", mode="rpc"
        ))
        process = HarnessProcess(adapter, "go")
        with patch.object(plugin_mod.subprocess, 'Popen', FakePopen):
            process.run()
        self.assertIn("go", FakePopen.instances[0].stdin.getvalue())

    def test_stop_terminates_when_the_group_kill_fails(self):
        process = HarnessProcess(self.adapter, "go")
        process._process = FakePopen(["x"])
        with patch.object(os, 'getpgid', side_effect=OSError("gone")):
            self.assertTrue(process.stop())
        self.assertTrue(process._process.terminated)

    def test_collect_artifacts_lists_run_directory_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "candidate_x.py"), 'w') as handle:
                handle.write("# x\n")
            process = HarnessProcess(self.adapter, "go", output_dir=tmp)
            artifacts = process.collect_artifacts()
        self.assertEqual(len(artifacts), 1)
        self.assertTrue(artifacts[0].endswith("candidate_x.py"))


class TestHarnessRunner(unittest.TestCase):
    """Signal emission from the worker."""

    def setUp(self):
        HarnessRunner.line_received.reset_mock()
        HarnessRunner.finished.reset_mock()
        HarnessRunner.failed.reset_mock()

    @staticmethod
    def _process(result=None, raises=None, timeout=30):
        process = MagicMock()
        process.timeout = timeout
        if raises is not None:
            process.run.side_effect = raises
        else:
            process.run.return_value = result
        return process

    def test_success_emits_finished(self):
        runner = HarnessRunner(self._process(
            HarnessResult(exit_code=0, output="done")
        ))
        runner.run()
        runner.finished.emit.assert_called_once()
        self.assertEqual(runner.finished.emit.call_args[0][0], 0)

    def test_non_zero_exit_still_emits_finished(self):
        runner = HarnessRunner(self._process(HarnessResult(exit_code=3)))
        runner.run()
        self.assertEqual(runner.finished.emit.call_args[0][0], 3)

    def test_error_emits_failed(self):
        runner = HarnessRunner(self._process(
            HarnessResult(exit_code=None, error="cannot start")
        ))
        runner.run()
        runner.failed.emit.assert_called_once_with("cannot start")

    def test_timeout_emits_failed(self):
        runner = HarnessRunner(self._process(
            HarnessResult(exit_code=None, timed_out=True), timeout=42
        ))
        runner.run()
        runner.failed.emit.assert_called_once()
        self.assertIn("42", runner.failed.emit.call_args[0][0])

    def test_an_exception_in_run_emits_failed(self):
        runner = HarnessRunner(self._process(raises=RuntimeError("boom")))
        runner.run()
        runner.failed.emit.assert_called_once_with("boom")

    def test_lines_are_forwarded_to_the_signal(self):
        process = MagicMock()
        process.timeout = 30

        def fake_run(on_line=None):
            on_line("hello")
            return HarnessResult(exit_code=0)

        process.run.side_effect = fake_run
        runner = HarnessRunner(process)
        runner.run()
        runner.line_received.emit.assert_called_once_with("hello")

    def test_result_is_kept_on_the_runner(self):
        result = HarnessResult(exit_code=0, output="x")
        runner = HarnessRunner(self._process(result))
        runner.run()
        self.assertIs(runner.result, result)

    def test_stop_is_delegated_to_the_process(self):
        process = self._process(HarnessResult(exit_code=0))
        runner = HarnessRunner(process)
        runner.stop()
        process.stop.assert_called_once()

    def test_result_to_dict_is_json_serializable(self):
        result = HarnessResult(exit_code=0, argv=["a"], artifacts=["b"])
        json.dumps(result.to_dict())


# ===================================================================
# 20. Agentic AI — SkillRegistry
# ===================================================================

SAMPLE_SKILL_MD = """\
---
name: pymol-shortcuts-author
description: Write one new shortcut for pymolshortcuts.py that satisfies
  the docstring contract.
---

# Authoring

Body text.
"""


class TestSkillRegistry(unittest.TestCase):
    """Discovery and frontmatter parsing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_skill(self, directory, folder, text=SAMPLE_SKILL_MD):
        path = os.path.join(directory, folder)
        os.makedirs(path, exist_ok=True)
        skill_md = os.path.join(path, "SKILL.md")
        with open(skill_md, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return skill_md

    def test_frontmatter_yields_name_and_description(self):
        path = self._write_skill(self.tmp, "author")
        info = SkillRegistry.parse_skill_md(path)
        self.assertEqual(info.name, "pymol-shortcuts-author")
        self.assertIn("docstring contract", info.description)
        self.assertIn("Body text.", info.body)

    def test_a_folded_description_loses_its_indicator(self):
        text = "---\nname: s\ndescription: >\n  folded text here\n---\nbody\n"
        path = self._write_skill(self.tmp, "folded", text)
        info = SkillRegistry.parse_skill_md(path)
        self.assertEqual(info.description, "folded text here")

    def test_a_quoted_description_loses_its_quotes(self):
        text = '---\nname: s\ndescription: "quoted"\n---\nbody\n'
        path = self._write_skill(self.tmp, "quoted", text)
        self.assertEqual(SkillRegistry.parse_skill_md(path).description,
                         "quoted")

    def test_a_missing_frontmatter_falls_back_to_the_folder_name(self):
        path = self._write_skill(self.tmp, "bare", "# Just a heading\n")
        self.assertEqual(SkillRegistry.parse_skill_md(path).name, "bare")

    def test_an_unreadable_file_returns_none(self):
        self.assertIsNone(
            SkillRegistry.parse_skill_md(os.path.join(self.tmp, "nope.md"))
        )

    def test_scan_finds_bundled_skills(self):
        self._write_skill(self.tmp, "author")
        registry = SkillRegistry(bundled_dir=self.tmp)
        names = [skill.name for skill in registry.scan()]
        self.assertIn("pymol-shortcuts-author", names)

    def test_a_user_skill_wins_over_a_bundled_one_of_the_same_name(self):
        user_dir = os.path.join(self.tmp, "user")
        bundled_dir = os.path.join(self.tmp, "bundled")
        self._write_skill(bundled_dir, "author")
        self._write_skill(user_dir, "author")
        registry = SkillRegistry(bundled_dir=bundled_dir)
        with patch.object(SkillRegistry, 'USER_DIR', user_dir):
            skills = registry.scan()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].source, "user")

    def test_scan_of_an_empty_tree_returns_nothing(self):
        registry = SkillRegistry(bundled_dir=os.path.join(self.tmp, "absent"))
        with patch.object(SkillRegistry, 'USER_DIR',
                          os.path.join(self.tmp, "absent2")):
            self.assertEqual(registry.scan(), [])

    def test_search_paths_are_unique_and_ordered(self):
        registry = SkillRegistry(working_dir="/tmp/project",
                                 bundled_dir="/tmp/bundled")
        paths = registry.search_paths()
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(paths[0], "/tmp/bundled")
        self.assertTrue(paths[-1].endswith(os.path.join(".claude", "skills")))

    def test_install_copies_the_skill_directory(self):
        path = self._write_skill(os.path.join(self.tmp, "src"), "author")
        info = SkillRegistry.parse_skill_md(path)
        dest_root = os.path.join(self.tmp, "dest")
        installed = SkillRegistry.install(info, dest_root=dest_root)
        self.assertTrue(os.path.isfile(os.path.join(installed, "SKILL.md")))

    def test_the_bundled_skills_ship_with_the_plugin(self):
        bundled = os.path.join(os.path.dirname(_plugin_path), "skills")
        if not os.path.isdir(bundled):
            self.skipTest("the bundled skills directory is absent")
        names = [skill.name for skill in
                 SkillRegistry(bundled_dir=bundled).scan()]
        self.assertIn("pymol-shortcuts-author", names)
        self.assertIn("pymol-shortcuts-test", names)


# ===================================================================
# 21. Agentic AI — prompt templates
# ===================================================================

class TestAgenticPromptTemplates(unittest.TestCase):
    """Template rendering and the retrieval context."""

    def test_every_stage_has_a_default_template(self):
        for stage in ("generate", "test", "document", "review"):
            self.assertIn(stage, plugin_mod.AGENTIC_PROMPT_TEMPLATES)

    def test_render_substitutes_known_placeholders(self):
        text = agentic_render("hello {name}", {"name": "colorBP"})
        self.assertEqual(text, "hello colorBP")

    def test_render_leaves_unknown_placeholders_alone(self):
        text = agentic_render("hello {mystery}", {"name": "x"})
        self.assertEqual(text, "hello {mystery}")

    def test_render_survives_an_unbalanced_brace(self):
        text = agentic_render("hello {", {})
        self.assertEqual(text, "hello {")

    def test_the_generate_template_states_the_contract(self):
        template = plugin_mod.AGENTIC_PROMPT_TEMPLATES["generate"]
        for header in ("DESCRIPTION:", "HORIZONTAL PML SCRIPT:",
                       "PYTHON CODE:", "cmd.extend"):
            self.assertIn(header, template)

    def test_the_review_template_carries_the_failures(self):
        rendered = agentic_render(
            plugin_mod.AGENTIC_PROMPT_TEMPLATES["review"],
            {"name": "x", "output_dir": "/tmp/r", "failures": "- broken"},
        )
        self.assertIn("- broken", rendered)

    def test_build_context_reports_when_no_engine_is_available(self):
        tab = AgenticAITab.__new__(AgenticAITab)
        tab.ai_tab = None
        tab.use_context_check = MagicMock()
        tab.use_context_check.isChecked.return_value = True
        self.assertIn("no examples", tab.build_context("goal"))

    def test_build_context_uses_the_retrieval_engine(self):
        tab = AgenticAITab.__new__(AgenticAITab)
        tab.shortcuts_file = ""
        tab.use_context_check = MagicMock()
        tab.use_context_check.isChecked.return_value = True
        tab.ai_tab = MagicMock()
        tab.ai_tab.shortcuts_chunks = ["chunk"]
        tab.ai_tab.search_chunks.return_value = [("def AO(): pass", 0.9)]
        self.assertIn("def AO()", tab.build_context("ambient occlusion"))


# ===================================================================
# 22. Agentic AI — CandidateValidator
# ===================================================================

GOOD_CANDIDATE = '''\
from pymol import cmd


def colorBP(selection='all', purine='skyblue'):
    """
    DESCRIPTION:
    Color nucleic acid bases by purine or pyrimidine identity.

    USAGE:
    colorBP [selection [, purine]]

    ARGUMENTS:
    selection: PyMOL selection (default: all)

    EXAMPLE:
    colorBP chain A

    MORE DETAILS:
    Colors only base atoms.

    VERTICAL PML SCRIPT:
    color skyblue, all and resn A+G

    HORIZONTAL PML SCRIPT:
    color skyblue, all and resn A+G

    PYTHON CODE:
    cmd.color(purine, selection)
    """
    cmd.color(purine, selection)


cmd.extend('colorBP', colorBP)
'''


class TestCandidateValidator(unittest.TestCase):
    """The static tier, the pytest tier, and the live tier."""

    def test_a_good_candidate_passes(self):
        result = CandidateValidator.static_check(GOOD_CANDIDATE, "colorBP")
        self.assertTrue(result.ok, result.failure_text())

    def test_a_syntax_error_is_caught(self):
        result = CandidateValidator.static_check("def (:", "x")
        self.assertFalse(result.ok)
        self.assertIn("does not parse", result.failure_text())

    def test_two_top_level_functions_are_rejected(self):
        source = GOOD_CANDIDATE + "\n\ndef extra():\n    pass\n"
        result = CandidateValidator.static_check(source, "colorBP")
        self.assertFalse(result.ok)
        self.assertIn("exactly one top-level function", result.failure_text())

    def test_a_name_mismatch_is_reported(self):
        result = CandidateValidator.static_check(GOOD_CANDIDATE, "somethingElse")
        self.assertFalse(result.ok)
        self.assertIn("somethingElse", result.failure_text())

    def test_a_missing_docstring_is_reported(self):
        source = "from pymol import cmd\n\n\ndef x():\n    pass\n\n\ncmd.extend('x', x)\n"
        result = CandidateValidator.static_check(source, "x")
        self.assertFalse(result.ok)
        self.assertIn("no docstring", result.failure_text())

    def test_a_missing_cmd_extend_is_reported(self):
        source = GOOD_CANDIDATE.replace("cmd.extend('colorBP', colorBP)", "")
        result = CandidateValidator.static_check(source, "colorBP")
        self.assertFalse(result.ok)
        self.assertIn("cmd.extend", result.failure_text())

    def test_a_cmd_extend_under_the_wrong_name_is_reported(self):
        source = GOOD_CANDIDATE.replace("cmd.extend('colorBP', colorBP)",
                                        "cmd.extend('other', colorBP)")
        result = CandidateValidator.static_check(source, "colorBP")
        self.assertFalse(result.ok)

    def test_an_empty_required_section_is_reported(self):
        source = GOOD_CANDIDATE.replace("    colorBP chain A\n", "")
        result = CandidateValidator.static_check(source, "colorBP")
        self.assertFalse(result.ok)
        self.assertIn("example", result.failure_text())

    def test_a_banned_call_is_reported(self):
        source = GOOD_CANDIDATE.replace(
            "    cmd.color(purine, selection)\n\n\ncmd.extend",
            "    os.system('rm -rf /')\n    cmd.color(purine, selection)\n\n\ncmd.extend",
        )
        result = CandidateValidator.static_check(source, "colorBP")
        self.assertFalse(result.ok)
        self.assertIn("os.system", result.failure_text())

    def test_eval_is_banned(self):
        source = GOOD_CANDIDATE.replace(
            "    cmd.color(purine, selection)\n\n\ncmd.extend",
            "    eval('1')\n    cmd.color(purine, selection)\n\n\ncmd.extend",
        )
        self.assertFalse(
            CandidateValidator.static_check(source, "colorBP").ok
        )

    def test_the_docstring_round_trips_through_the_parser(self):
        tree = ast.parse(GOOD_CANDIDATE)
        function = [n for n in tree.body if isinstance(n, ast.FunctionDef)][0]
        parsed = ShortcutsParser._parse_docstring(
            function.name, ast.get_docstring(function)
        )
        self.assertIsNotNone(parsed)
        self.assertIn("purine", parsed.description)
        self.assertTrue(parsed.pml_horizontal)

    def test_pytest_tier_reports_a_missing_file(self):
        result = CandidateValidator.run_pytest("/nonexistent/test_x.py")
        self.assertFalse(result.ok)
        self.assertIn("no test file", result.failure_text())

    def test_pytest_tier_passes_a_trivial_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_ok.py")
            with open(path, 'w') as handle:
                handle.write("def test_ok():\n    assert True\n")
            result = CandidateValidator.run_pytest(path, cwd=tmp, timeout=120)
        self.assertTrue(result.ok, result.detail)

    def test_pytest_tier_reports_a_failing_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_bad.py")
            with open(path, 'w') as handle:
                handle.write("def test_bad():\n    assert False\n")
            result = CandidateValidator.run_pytest(path, cwd=tmp, timeout=120)
        self.assertFalse(result.ok)

    def test_live_check_commands_fetch_the_reference_first(self):
        commands = CandidateValidator.live_check_commands("colorBP", "1lw9")
        self.assertEqual(commands[0], "delete all")
        self.assertIn("fetch 1lw9", commands[1])
        self.assertEqual(commands[2], "colorBP")

    def test_live_check_defaults_to_the_module_reference(self):
        commands = CandidateValidator.live_check_commands("x")
        self.assertIn(plugin_mod.AGENTIC_REFERENCE_STRUCTURE, commands[1])

    def test_live_check_reports_a_raising_command(self):
        def runner(command):
            if command.startswith("fetch"):
                raise RuntimeError("no network")
        result = CandidateValidator.live_check(
            "colorBP", GOOD_CANDIDATE, runner=runner
        )
        self.assertFalse(result.ok)
        self.assertIn("no network", result.failure_text())

    def test_live_check_passes_with_a_cooperative_runner(self):
        seen = []
        result = CandidateValidator.live_check(
            "colorBP", GOOD_CANDIDATE, runner=seen.append
        )
        self.assertTrue(result.ok, result.failure_text())
        self.assertEqual(len(seen), 3)


# ===================================================================
# 23. Agentic AI — settings, run log, and integration
# ===================================================================

class TestAgenticSettings(unittest.TestCase):
    """Round trip of the agentic keys."""

    AGENTIC_KEYS = (
        "agentic/harness", "agentic/executable", "agentic/working_dir",
        "agentic/scratch_dir", "agentic/reference_structure",
        "agentic/timeout", "agentic/confirm_live", "agentic/skills_dir",
    )

    def test_harness_config_round_trips_through_a_dictionary(self):
        config = HarnessConfig(harness="pi", executable="/bin/pi",
                               model="m", timeout=99)
        restored = HarnessConfig.from_dict(config.to_dict())
        self.assertEqual(restored.harness, "pi")
        self.assertEqual(restored.executable, "/bin/pi")
        self.assertEqual(restored.timeout, 99)

    def test_harness_config_ignores_unknown_keys(self):
        restored = HarnessConfig.from_dict({"harness": "pi", "bogus": 1})
        self.assertEqual(restored.harness, "pi")

    def test_harness_config_defaults_are_sane(self):
        config = HarnessConfig()
        self.assertEqual(config.harness, "claude-code")
        self.assertEqual(config.mode, "print")
        self.assertEqual(config.timeout, plugin_mod.AGENTIC_DEFAULT_TIMEOUT)

    def test_save_settings_writes_every_agentic_key(self):
        SettingsTab = plugin_mod.SettingsTab
        tab = SettingsTab.__new__(SettingsTab)
        store = MockQSettings()
        store.clear()
        tab.settings = store
        for widget in ("font_size", "theme", "auto_load",
                       "default_shortcuts_path", "remember_provider",
                       "auto_index", "save_api_keys", "enable_history",
                       "max_history", "check_updates", "agentic_harness",
                       "agentic_executable", "agentic_working_dir",
                       "agentic_scratch_dir", "agentic_reference",
                       "agentic_timeout", "agentic_confirm_live",
                       "agentic_skills_dir"):
            setattr(tab, widget, MagicMock())
        tab.agentic_harness.currentData.return_value = "pi"
        tab.apply_appearance = MagicMock()
        plugin_mod.QtWidgets.QMessageBox.information = MagicMock()
        tab.save_settings()
        for key in self.AGENTIC_KEYS:
            self.assertIn(key, MockQSettings._store, key)
        self.assertEqual(MockQSettings._store["agentic/harness"], "pi")

    def test_load_settings_reads_every_agentic_key(self):
        with open(_plugin_path, 'r') as handle:
            src = handle.read()
        load_start = src.index("    def load_settings(self):")
        load_end = src.index("    def save_settings(self):")
        body = src[load_start:load_end]
        for key in self.AGENTIC_KEYS:
            self.assertIn(key, body, key)

    def test_confirm_live_defaults_to_on(self):
        with open(_plugin_path, 'r') as handle:
            src = handle.read()
        self.assertIn('self.settings.value("agentic/confirm_live", True', src)

    def test_the_scratch_root_is_under_the_dot_directory(self):
        self.assertTrue(
            plugin_mod.AGENTIC_SCRATCH_ROOT.endswith(
                os.path.join(".pymolshortcuts", "agent")
            )
        )


class TestAgentRunStore(unittest.TestCase):
    """The JSON record of past runs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "runs.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_absent_file_loads_as_an_empty_list(self):
        self.assertEqual(AgentRunStore(self.path).load(), [])

    def test_add_then_load_returns_the_record(self):
        store = AgentRunStore(self.path)
        store.add({"stage": "generate", "shortcut": "colorBP"})
        records = store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["shortcut"], "colorBP")
        self.assertIn("timestamp", records[0])

    def test_the_limit_trims_the_oldest_records(self):
        store = AgentRunStore(self.path, limit=3)
        for index in range(5):
            store.add({"stage": str(index)})
        stages = [record["stage"] for record in store.load()]
        self.assertEqual(stages, ["2", "3", "4"])

    def test_corrupt_json_loads_as_an_empty_list(self):
        with open(self.path, 'w') as handle:
            handle.write("{not json")
        self.assertEqual(AgentRunStore(self.path).load(), [])

    def test_clear_empties_the_log(self):
        store = AgentRunStore(self.path)
        store.add({"stage": "generate"})
        store.clear()
        self.assertEqual(store.load(), [])

    def test_export_writes_a_copy(self):
        store = AgentRunStore(self.path)
        store.add({"stage": "generate"})
        target = os.path.join(self.tmp, "export.json")
        store.export(target)
        with open(target) as handle:
            self.assertEqual(len(json.load(handle)), 1)


class TestAgenticIntegration(unittest.TestCase):
    """Handing a validated candidate back to the rest of the plugin."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_dir_sanitizes_the_name(self):
        path = agentic_run_dir("bad/name here", root=self.tmp,
                               stamp="20260730-120000")
        self.assertTrue(os.path.isdir(path))
        self.assertIn("bad_name_here-20260730-120000", path)

    def test_append_writes_a_backup_first(self):
        target = os.path.join(self.tmp, "pymolshortcuts.py")
        with open(target, 'w') as handle:
            handle.write("# original\n")
        backup = agentic_append_to_shortcuts(target, "def x():\n    pass\n")
        self.assertTrue(os.path.isfile(backup))
        with open(backup) as handle:
            self.assertEqual(handle.read(), "# original\n")
        with open(target) as handle:
            self.assertIn("def x()", handle.read())

    def test_append_refuses_a_missing_file(self):
        with self.assertRaises(IOError):
            agentic_append_to_shortcuts(
                os.path.join(self.tmp, "absent.py"), "code"
            )

    def test_parse_candidate_returns_shortcut_data(self):
        parsed = AgenticAITab.parse_candidate(GOOD_CANDIDATE)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.name, "colorBP")
        self.assertIn("purine", parsed.description)

    def test_parse_candidate_returns_none_on_a_syntax_error(self):
        self.assertIsNone(AgenticAITab.parse_candidate("def (:"))

    def test_send_to_add_shortcut_fills_the_form(self):
        tab = AgenticAITab.__new__(AgenticAITab)
        tab.candidate_source = GOOD_CANDIDATE
        tab.candidate_path = ""
        tab.add_shortcut_tab = MagicMock()
        tab.log = MagicMock()
        self.assertTrue(tab.send_to_add_shortcut())
        tab.add_shortcut_tab.name_edit.setText.assert_called_once_with("colorBP")
        tab.add_shortcut_tab.python_edit.setPlainText.assert_called_once()

    def test_send_to_add_shortcut_needs_a_candidate(self):
        tab = AgenticAITab.__new__(AgenticAITab)
        tab.candidate_source = ""
        tab.candidate_path = ""
        tab.add_shortcut_tab = MagicMock()
        tab.log = MagicMock()
        self.assertFalse(tab.send_to_add_shortcut())

    def test_validate_inputs_requires_a_name_and_a_goal(self):
        tab = AgenticAITab.__new__(AgenticAITab)
        tab.name_edit = MagicMock()
        tab.name_edit.text.return_value = ""
        tab.goal_edit = MagicMock()
        tab.goal_edit.toPlainText.return_value = ""
        errors = tab.validate_inputs()
        self.assertEqual(len(errors), 2)

    def test_validate_inputs_rejects_a_bad_name(self):
        tab = AgenticAITab.__new__(AgenticAITab)
        tab.name_edit = MagicMock()
        tab.name_edit.text.return_value = "9bad name"
        tab.goal_edit = MagicMock()
        tab.goal_edit.toPlainText.return_value = "do a thing"
        errors = tab.validate_inputs()
        self.assertEqual(len(errors), 1)
        self.assertIn("start with a letter", errors[0])

    def test_validate_inputs_accepts_a_good_name(self):
        tab = AgenticAITab.__new__(AgenticAITab)
        tab.name_edit = MagicMock()
        tab.name_edit.text.return_value = "colorBP"
        tab.goal_edit = MagicMock()
        tab.goal_edit.toPlainText.return_value = "color base pairs"
        self.assertEqual(tab.validate_inputs(), [])

    def test_set_shortcuts_file_seeds_the_working_directory(self):
        tab = AgenticAITab.__new__(AgenticAITab)
        tab.working_dir_edit = MagicMock()
        tab.working_dir_edit.text.return_value = ""
        target = os.path.join(self.tmp, "pymolshortcuts.py")
        with open(target, 'w') as handle:
            handle.write("# x\n")
        tab.set_shortcuts_file(target)
        tab.working_dir_edit.setText.assert_called_once_with(self.tmp)


# ===================================================================
# 24. Agentic AI — the MCP server
# ===================================================================

try:
    import importlib as _importlib
    _mcp_path = os.path.join(os.path.dirname(_plugin_path),
                             "pymolshortcuts_mcp.py")
    _mcp_spec = _importlib.util.spec_from_file_location(
        "pymolshortcuts_mcp_undertest", _mcp_path
    )
    mcp_mod = _importlib.util.module_from_spec(_mcp_spec)
    _mcp_spec.loader.exec_module(mcp_mod)
except Exception:                                     # noqa: BLE001
    mcp_mod = None


@unittest.skipIf(mcp_mod is None, "the MCP server module could not be loaded")
class TestMCPServer(unittest.TestCase):
    """The JSON-RPC surface of the companion MCP server."""

    def _request(self, method, params=None, request_id=1):
        return mcp_mod.handle_request({
            "jsonrpc": "2.0", "id": request_id,
            "method": method, "params": params or {},
        })

    def test_initialize_returns_the_server_info(self):
        response = self._request("initialize",
                                 {"protocolVersion": "2024-11-05"})
        self.assertEqual(response["result"]["serverInfo"]["name"],
                         "pymolshortcuts")

    def test_a_notification_produces_no_response(self):
        self.assertIsNone(mcp_mod.handle_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        ))

    def test_tools_list_hides_the_handlers(self):
        tools = self._request("tools/list")["result"]["tools"]
        self.assertTrue(tools)
        for tool in tools:
            self.assertNotIn("handler", tool)
            self.assertIn("inputSchema", tool)

    def test_every_expected_tool_is_registered(self):
        names = {tool["name"] for tool in mcp_mod.public_tools()}
        for expected in ("list_shortcuts", "get_shortcut",
                         "docstring_contract", "validate_candidate",
                         "write_candidate", "run_candidate_tests",
                         "run_in_pymol", "append_shortcut", "list_skills"):
            self.assertIn(expected, names)

    def test_an_unknown_method_is_an_error(self):
        response = self._request("nope/nope")
        self.assertEqual(response["error"]["code"], -32601)

    def test_an_unknown_tool_is_reported_as_a_tool_error(self):
        result = mcp_mod.call_tool("nope", {})
        self.assertTrue(result["isError"])

    def test_validate_candidate_agrees_with_the_plugin(self):
        result = mcp_mod.tool_validate_candidate(GOOD_CANDIDATE, "colorBP")
        self.assertTrue(result["ok"])

    def test_validate_candidate_rejects_a_broken_module(self):
        result = mcp_mod.tool_validate_candidate("def (:", "x")
        self.assertFalse(result["ok"])

    def test_write_candidate_creates_the_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = mcp_mod.tool_write_candidate(
                "colorBP", GOOD_CANDIDATE, scratch_root=tmp
            )
            self.assertTrue(os.path.isfile(payload["path"]))

    def test_append_shortcut_refuses_an_invalid_candidate(self):
        payload = mcp_mod.tool_append_shortcut("x", "def (:")
        self.assertFalse(payload["ok"])
        self.assertIn("static check", payload["error"])

    def test_run_in_pymol_is_refused_without_the_environment_flag(self):
        with patch.dict(os.environ, {mcp_mod.LIVE_ENV_FLAG: "0"}):
            payload = mcp_mod.tool_run_in_pymol("colorBP", GOOD_CANDIDATE)
        self.assertFalse(payload["ok"])
        self.assertIn("disabled", payload["error"])

    def test_the_docstring_contract_names_the_banned_calls(self):
        contract = mcp_mod.tool_docstring_contract()["contract"]
        self.assertIn("os.system", contract)
        self.assertIn("HORIZONTAL PML SCRIPT:", contract)


# ===================================================================
# Entry point
# ===================================================================

if __name__ == "__main__":
    unittest.main()
    
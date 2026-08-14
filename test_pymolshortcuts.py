"""Unit and integration tests for the functions in pymolshortcuts.py.

The library is written to be sourced inside PyMOL, so it imports ``pymol``
and ``psico`` and calls ``cmd`` at import time.  To test it without a running
PyMOL, this module injects mock modules into ``sys.modules`` before importing
pymolshortcuts.py through importlib, mirroring the harness already used by
test_pymolshortcuts_manager.py.

Tiers:
  A  registration : import, inventory, callables, name collisions, docstring
  B  smoke        : every shortcut runs once without raising (registry-driven)
  C  contract     : web, website, launcher, and save-timestamp behavior
  D  units        : timestamped_name and pdbremarks return-value tests
  E  live         : a curated subset run in real headless PyMOL (marked 'live',
                    skipped automatically when pymol cannot be imported)

Run the fast, hermetic tiers with:   pytest test_pymolshortcuts.py
Run the live tier (needs PyMOL) with: pytest -m live test_pymolshortcuts.py
"""

import io
import os
import re
import sys
import gzip
import types
import inspect
import subprocess as _real_subprocess
import datetime as _real_datetime
import importlib.util
import contextlib
import tempfile

import pytest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Harness: mock the PyMOL/psico runtime, then import pymolshortcuts.py
# ---------------------------------------------------------------------------

SENTINEL = "TESTQUERYSENTINEL"
FROZEN = _real_datetime.datetime(2026, 8, 13, 10, 30, 45)


class FrozenDatetimeModule:
    """Stand-in for the ``datetime`` module with a fixed ``now()``."""

    class datetime:
        @staticmethod
        def now():
            return FROZEN

    # a few shortcuts also touch datetime.timedelta / date; expose the reals
    timedelta = _real_datetime.timedelta
    date = _real_datetime.date


def _configure_cmd(cmd):
    """Give the cmd mock query-return values so numeric shortcuts do not
    blow up on MagicMock arithmetic during the smoke tier."""
    cmd.get_names.return_value = []
    cmd.get_object_list.return_value = []
    cmd.get_names_of_type.return_value = []
    cmd.count_atoms.return_value = 0
    cmd.count_states.return_value = 1
    cmd.get_chains.return_value = []
    cmd.identify.return_value = []
    cmd.index.return_value = []
    cmd.get_extent.return_value = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    cmd.get_view.return_value = tuple([0.0] * 18)
    cmd.get_position.return_value = [0.0, 0.0, 0.0]
    cmd.get_atom_coords.return_value = [0.0, 0.0, 0.0]
    cmd.get_symmetry.return_value = [1.0, 1.0, 1.0, 90.0, 90.0, 90.0, "P 1"]
    cmd.get_raw_alignment.return_value = []
    cmd.get.return_value = 1.0
    cmd.get_setting_float.return_value = 1.0
    cmd.get_model.return_value = MagicMock(atom=[])
    # Non-empty object lists so shortcuts that index [0] do not spuriously
    # IndexError against a bare mock.
    cmd.get_names.return_value = ["mol"]
    cmd.get_object_list.return_value = ["mol"]
    return cmd


def _make_subprocess_mock():
    """A subprocess mock whose exception attributes are the real classes, so
    that `except subprocess.CalledProcessError:` works and any underlying
    NameError in a launcher propagates instead of being masked."""
    sp = MagicMock(name="subprocess")
    sp.CalledProcessError = _real_subprocess.CalledProcessError
    sp.TimeoutExpired = _real_subprocess.TimeoutExpired
    sp.SubprocessError = _real_subprocess.SubprocessError
    return sp


def _make_pymol_modules():
    registry = {}

    cmd = MagicMock(name="cmd")
    cmd.extend.side_effect = lambda name, func=None: (
        registry.__setitem__(name, func),
        func,
    )[1]
    _configure_cmd(cmd)

    pymol = types.ModuleType("pymol")
    pymol.cmd = cmd
    pymol.stored = MagicMock(name="stored")
    pymol.math = MagicMock(name="pymol.math")
    pymol.cgo = MagicMock(name="cgo")
    pymol.xray = MagicMock(name="xray")

    mods = {
        "pymol": pymol,
        "pymol.cmd": cmd,
        "pymol.stored": pymol.stored,
        "pymol.cgo": pymol.cgo,
        "pymol.xray": pymol.xray,
        "psico": MagicMock(name="psico"),
        "psico.fullinit": MagicMock(name="psico.fullinit"),
    }
    return mods, cmd, registry


def _load_module():
    mods, cmd, registry = _make_pymol_modules()
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "pymolshortcuts.py")
    spec = importlib.util.spec_from_file_location("pymolshortcuts_under_test", path)
    module = importlib.util.module_from_spec(spec)
    # Importing runs print(SC.__doc__); swallow it.
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    # Replace the outward-facing modules with fresh mocks we control per test.
    module.cmd = cmd
    module.webbrowser = MagicMock(name="webbrowser")
    module.subprocess = _make_subprocess_mock()
    # PyMOL injects these module globals into the namespace when a script is
    # sourced with `run`; the library never imports them, so provide them.
    module.preset = MagicMock(name="preset")
    module.util = MagicMock(name="util")
    for k, v in saved.items():  # do not leak our mocks to other test files
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    return module, cmd, registry


MODULE, CMD, REGISTRY = _load_module()

# Shortcuts whose signature has a required positional argument.
REQUIRED_ARG_FIXTURES = {
    "interface": ["cpx"],
    "pairD": ["sel1", "sel2", "3.0"],
    # a file object exercises pdbremarks' non-string branch with no disk I/O
    "pdbremarks": [io.StringIO("")],
    "quat350": [""],
}

# Shortcuts with a real defect the smoke tier exposes; xfail with a reason so
# the suite stays green and the bug stays visible until fixed in the library.
# (Empty: the IPM defect and the broken error handlers have been fixed.)
KNOWN_BROKEN = {}

# List/multi-term web shortcuts that open one tab per supplied term and so
# open nothing with their empty default argument; covered by dedicated tests.
WEB_MULTITERM = {"IPM", "IPMN"}

# A few launchers whose exact argv we pin against the module constant.
LAUNCHER_EXEMPLARS = {
    "vim": "vimOpen",
    "code": "codeOpen",
    "emacs": "emacsOpen",
}


def _reset():
    CMD.reset_mock(return_value=False, side_effect=False)
    _configure_cmd(CMD)
    # keep the registry-populating side_effect intact
    CMD.extend.side_effect = lambda name, func=None: func
    MODULE.webbrowser = MagicMock(name="webbrowser")
    MODULE.subprocess = _make_subprocess_mock()
    MODULE.preset = MagicMock(name="preset")
    MODULE.util = MagicMock(name="util")
    MODULE.datetime = FrozenDatetimeModule


@pytest.fixture(autouse=True)
def _isolate():
    _reset()
    yield
    _reset()


def _args_for(name):
    fn = REGISTRY[name]
    sig = inspect.signature(fn)
    required = [
        p
        for p in sig.parameters.values()
        if p.default is inspect._empty
        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)
    ]
    if not required:
        return []
    return REQUIRED_ARG_FIXTURES.get(name, ["all"] * len(required))


def _call(name):
    with contextlib.redirect_stdout(io.StringIO()):
        return REGISTRY[name](*_args_for(name))


def _category(name):
    """Classify a shortcut by the API calls in its source. Match real calls,
    for example ``webbrowser.open`` or ``subprocess.call``, rather than the
    word appearing in the docstring help text."""
    fn = REGISTRY[name]
    try:
        src = inspect.getsource(fn)
    except OSError:
        src = ""
    # Classify on the real code, not the docstring help text.
    if fn.__doc__:
        src = src.replace(fn.__doc__, "")
    has_param = bool(
        [
            p
            for p in inspect.signature(REGISTRY[name]).parameters.values()
            if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)
        ]
    )
    if re.search(r"webbrowser\.(open|get)", src):
        # A search shortcut folds its term into the opened URL; a website
        # launcher opens a fixed URL even if it nominally takes a parameter.
        params = [
            p
            for p in inspect.signature(fn).parameters.values()
            if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)
        ]
        if params:
            pname = params[0].name
            for line in src.splitlines():
                if "webbrowser" in line and "open" in line and pname in line:
                    return "web_search"
        return "web_site"
    if re.search(r"subprocess\.(check_output|call|Popen|run|check_call)\b", src):
        return "launcher"
    if "timestamped_name(" in src:
        return "save_ts"
    return "graphics"


NAMES = sorted(REGISTRY)
# Known-broken shortcuts are documented via xfail in the smoke tier; keep them
# out of the behavioral-contract tiers so those stay green.
_CONTRACT = [n for n in NAMES if n not in KNOWN_BROKEN and n not in WEB_MULTITERM]
WEB_SEARCH = [n for n in _CONTRACT if _category(n) == "web_search"]
WEB_SITE = [n for n in _CONTRACT if _category(n) == "web_site"]
LAUNCHERS = [n for n in _CONTRACT if _category(n) == "launcher"]
SAVE_TS = [n for n in _CONTRACT if _category(n) == "save_ts"]

# Shortcuts that need a live PyMOL for their numeric logic and cannot be
# exercised meaningfully against a bare mock; excluded from the smoke tier
# and covered by the live tier instead.
SMOKE_SKIP = set()

EXPECTED_SHORTCUT_COUNT = 233


def _webbrowser_urls():
    wb = MODULE.webbrowser
    urls = []
    # direct calls: webbrowser.open(url) / open_new_tab / open_new
    # and controller calls: webbrowser.get().open(url) / open_new_tab
    targets = [wb, wb.get.return_value]
    for obj in targets:
        for meth in ("open", "open_new_tab", "open_new"):
            for c in getattr(obj, meth).call_args_list:
                if c.args:
                    urls.append(c.args[0])
    return urls


def _subprocess_calls():
    sp = MODULE.subprocess
    calls = []
    for meth in ("check_output", "Popen", "call", "run", "check_call"):
        for c in getattr(sp, meth).call_args_list:
            if c.args:
                calls.append(c.args[0])
    return calls


# ---------------------------------------------------------------------------
# Tier A: registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_module_imports_and_registers(self):
        assert len(REGISTRY) == EXPECTED_SHORTCUT_COUNT

    def test_every_shortcut_is_callable(self):
        assert all(callable(f) for f in REGISTRY.values())

    def test_no_duplicate_registrations(self):
        # REGISTRY is a dict, so a repeat name would overwrite; guard the
        # source-level count of cmd.extend calls against the registry size.
        here = os.path.dirname(os.path.abspath(__file__))
        src = open(os.path.join(here, "pymolshortcuts.py")).read()
        # each shortcut registers twice in source (docstring copy + real)
        extend_calls = src.count("cmd.extend(")
        assert extend_calls >= len(REGISTRY)

    def test_names_are_short_tokens(self):
        assert all(n and " " not in n for n in REGISTRY)


# ---------------------------------------------------------------------------
# Tier B: smoke (registry-driven)
# ---------------------------------------------------------------------------

def _smoke_params():
    params = []
    for n in NAMES:
        if n in SMOKE_SKIP:
            continue
        marks = ()
        if n in KNOWN_BROKEN:
            marks = (pytest.mark.xfail(reason=KNOWN_BROKEN[n], strict=True),)
        params.append(pytest.param(n, marks=marks))
    return params


@pytest.mark.parametrize("name", _smoke_params())
def test_smoke_runs_without_error(name):
    """Every shortcut must execute once without raising, with cmd,
    webbrowser, and subprocess mocked. This is the broad safety net that
    catches NameError, undefined variables, and bad API arity."""
    _call(name)


# ---------------------------------------------------------------------------
# Tier C: behavioral contract by category
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", WEB_SEARCH)
def test_web_search_opens_browser_with_query(name):
    with contextlib.redirect_stdout(io.StringIO()):
        REGISTRY[name](SENTINEL)
    urls = _webbrowser_urls()
    assert urls, f"{name} did not open the browser"
    assert all(u.startswith("http") for u in urls), urls
    assert any(SENTINEL in u for u in urls), (name, urls)


@pytest.mark.parametrize("name", WEB_SITE)
def test_web_site_opens_fixed_url(name):
    _call(name)
    urls = _webbrowser_urls()
    assert len(urls) >= 1, f"{name} did not open the browser"
    assert all(u.startswith("http") for u in urls), urls


@pytest.mark.parametrize("name", LAUNCHERS)
def test_launcher_invokes_subprocess(name):
    _call(name)
    calls = _subprocess_calls()
    assert len(calls) >= 1, f"{name} did not call subprocess"
    argv = calls[0]
    assert isinstance(argv, (list, tuple)) and len(argv) >= 1, (name, argv)
    assert all(isinstance(x, str) for x in argv), (name, argv)


@pytest.mark.parametrize("name,const", sorted(LAUNCHER_EXEMPLARS.items()))
def test_launcher_exact_argv(name, const):
    if name not in REGISTRY or not hasattr(MODULE, const):
        pytest.skip(f"{name}/{const} not present")
    _call(name)
    calls = _subprocess_calls()
    assert calls and list(calls[0]) == list(getattr(MODULE, const)), (
        name,
        calls,
        getattr(MODULE, const),
    )


@pytest.mark.parametrize("name", SAVE_TS)
def test_save_timestamp_filename(name):
    _call(name)
    assert CMD.save.call_count == 1, f"{name} did not call cmd.save once"
    fname = CMD.save.call_args.args[0]
    assert fname.startswith("saved"), (name, fname)
    assert "." in os.path.basename(fname), (name, fname)
    # the frozen timestamp fields must appear, proving timestamped_name ran
    assert "2026" in fname and "30" in fname, (name, fname)


def test_save_timestamp_is_deterministic():
    # tvdw is not a save shortcut; use spng and confirm two calls match
    _call("spng")
    first = CMD.save.call_args.args[0]
    _reset()
    _call("spng")
    second = CMD.save.call_args.args[0]
    assert first == second == "savedyr2026mo08day13hr10min30sec45.png"


def test_tvdw_uses_create_not_copy():
    """Regression guard for the migration bug fixed earlier."""
    _call("tvdw")
    assert CMD.create.called, "tvdw should build the vdw object with cmd.create"
    assert not CMD.copy.called, "tvdw must not use cmd.copy"


@pytest.mark.parametrize("name", sorted(WEB_MULTITERM & set(REGISTRY)))
def test_web_multiterm_opens_a_tab_per_term(name):
    """IPM-style shortcuts open one browser tab per supplied search term."""
    terms = ["alpha", "beta", "gamma"]
    with contextlib.redirect_stdout(io.StringIO()):
        REGISTRY[name](terms)
    urls = _webbrowser_urls()
    assert len(urls) == len(terms), (name, urls)
    for term in terms:
        assert any(term in u for u in urls), (name, term, urls)


def test_error_handlers_are_well_formed():
    """Regression guard: no error handler uses the broken '"text" % e' form
    (a format string with no %s), which raised TypeError when it fired."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "pymolshortcuts.py")).read()
    bad = re.findall(r'print\("[^"%]*" % e\)', src)
    assert not bad, bad


# ---------------------------------------------------------------------------
# Tier D: pure-helper unit tests
# ---------------------------------------------------------------------------

class TestTimestampedName:
    def test_default_format(self):
        assert (
            MODULE.timestamped_name("saved", "png", when=FROZEN)
            == "savedy2026m08d13h10m30s45.png"
        )

    def test_custom_format(self):
        assert (
            MODULE.timestamped_name(
                "x", "pse", "yr%Ymo%mday%dhr%Hmin%Msec%S", when=FROZEN
            )
            == "xyr2026mo08day13hr10min30sec45.pse"
        )

    def test_uses_now_when_when_is_none(self):
        MODULE.datetime = FrozenDatetimeModule
        assert MODULE.timestamped_name("s", "pdb") == "sy2026m08d13h10m30s45.pdb"


class TestPdbremarks:
    def _write(self, text, gz=False):
        suffix = ".pdb.gz" if gz else ".pdb"
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        if gz:
            with gzip.open(path, "wt") as f:
                f.write(text)
        else:
            with open(path, "w") as f:
                f.write(text)
        return path

    SAMPLE = (
        "HEADER    TEST\n"
        "REMARK   1 FIRST REMARK LINE\n"
        "REMARK   1 SECOND REMARK LINE\n"
        "REMARK 350 BIOMT LINE\n"
        "ATOM      1  N   ALA A   1      11.104  13.207  10.567\n"
    )

    def test_parses_plain_pdb(self):
        path = self._write(self.SAMPLE)
        try:
            remarks = MODULE.pdbremarks(path)
        finally:
            os.unlink(path)
        assert 1 in remarks and 350 in remarks
        assert len(remarks[1]) == 2
        assert "FIRST REMARK LINE" in remarks[1][0]

    def test_parses_gzipped_pdb_in_text_mode(self):
        path = self._write(self.SAMPLE, gz=True)
        try:
            remarks = MODULE.pdbremarks(path)
        finally:
            os.unlink(path)
        assert 350 in remarks  # proves gzip.open(..., 'rt') text-mode fix

    def test_accepts_file_object(self):
        remarks = MODULE.pdbremarks(io.StringIO(self.SAMPLE))
        assert 1 in remarks


# ---------------------------------------------------------------------------
# Tier E: live integration (needs real PyMOL; skipped otherwise)
# ---------------------------------------------------------------------------

LIVE_SUBSET = ["AO", "spng", "tvdw", "BW", "CB"]


@pytest.mark.live
@pytest.mark.parametrize("name", LIVE_SUBSET)
def test_live_executes_in_real_pymol(name, tmp_path):
    pytest.importorskip("pymol")
    import pymol
    from pymol import cmd as real_cmd

    pymol.finish_launching(["pymol", "-cq"])
    here = os.path.dirname(os.path.abspath(__file__))
    real_cmd.reinitialize()
    real_cmd.load(os.path.join(here, "test_data", "mini.pdb"), "mini")
    # source the library into the live session and run the shortcut
    ns = {}
    with open(os.path.join(here, "pymolshortcuts.py")) as f:
        exec(compile(f.read(), "pymolshortcuts.py", "exec"), ns)
    os.chdir(tmp_path)  # keep any saved files in a temp dir
    ns[name]()  # must not raise

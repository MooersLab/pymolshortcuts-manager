# -*- coding: utf-8 -*-
"""
PyMOL Shortcuts MCP Server
==========================

Exposes the shortcut library, the candidate validator, the generated-test
runner, and (optionally) a live PyMOL session as Model Context Protocol
tools over stdio.

The Agentic AI tab drives a coding harness from inside PyMOL. This server
turns the relationship around: an external harness such as Claude Code or
Pi drives the shortcut library through real tools instead of prompt text.
Both directions share the same Qt-free layer in pymolshortcuts_manager.py,
so the docstring contract and the validation tiers cannot drift apart.

Running the server
------------------
Outside PyMOL, for authoring and validation only::

    python pymolshortcuts_mcp.py

Inside PyMOL, which additionally enables the live tier::

    PyMOL> run pymolshortcuts_mcp.py
    PyMOL> pymolshortcuts_mcp_serve()

Registering it with Claude Code::

    claude mcp add pymolshortcuts -- python /path/to/pymolshortcuts_mcp.py

Registering it with Pi, in the MCP section of the Pi configuration::

    {"pymolshortcuts": {"command": "python",
                        "args": ["/path/to/pymolshortcuts_mcp.py"]}}

Safety
------
Two tools change state outside the scratch directory. ``append_shortcut``
writes to the shortcuts file and always writes a timestamped backup first.
``run_in_pymol`` executes model-written code in a live session and is
refused unless the environment variable PYMOLSHORTCUTS_MCP_ALLOW_LIVE is
set to 1, because an agent should not be able to talk the server into it.

Author: Blaine Mooers
License: MIT
"""

from __future__ import print_function

import json
import os
import sys
import traceback

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "pymolshortcuts"
SERVER_VERSION = "0.2.1"

# Set PYMOLSHORTCUTS_MCP_ALLOW_LIVE=1 to enable the live PyMOL tier.
LIVE_ENV_FLAG = "PYMOLSHORTCUTS_MCP_ALLOW_LIVE"


# ---------------------------------------------------------------------------
# Loading the plugin module outside PyMOL
# ---------------------------------------------------------------------------

def _install_stubs():
    """Put minimal pymol and pymol.Qt stand-ins into sys.modules.

    The plugin is one file that imports pymol.Qt at the top, because it
    normally runs inside PyMOL. The server needs the Qt-free half of that
    file, so it injects stubs first, the same way the test suite does.
    Returns True when stubs were installed, False when the real PyMOL was
    already importable.
    """
    try:
        import pymol                                # noqa: F401
        from pymol import cmd                       # noqa: F401
        try:
            from pymol.Qt import QtWidgets          # noqa: F401
            return False
        except Exception:                           # noqa: BLE001
            pass
    except Exception:                               # noqa: BLE001
        pass

    import types

    _stub_cache = {}

    class _StubMeta(type):
        """Metaclass whose classes answer any attribute with another class.

        The plugin subclasses QtWidgets.QWidget and friends at import time,
        so a stub attribute has to be a real class rather than a sentinel
        object. Caching keeps repeated lookups of the same name identical,
        which matters for isinstance checks.
        """

        def __getattr__(cls, item):
            if item.startswith('__') and item.endswith('__'):
                raise AttributeError(item)
            return _make_stub(f"{cls.__name__}.{item}")

    def _make_stub(name):
        if name in _stub_cache:
            return _stub_cache[name]

        def _init(self, *args, **kwargs):
            pass

        def _getattr(self, item):
            if item.startswith('__') and item.endswith('__'):
                raise AttributeError(item)
            return _make_stub(f"{name}.{item}")

        stub = _StubMeta(name, (object,), {
            '__init__': _init,
            '__getattr__': _getattr,
            '__repr__': lambda self: f"<stub {name}>",
        })
        _stub_cache[name] = stub
        return stub

    if 'pymol' not in sys.modules:
        pymol_module = types.ModuleType('pymol')
        pymol_module.cmd = _make_stub('cmd')()
        sys.modules['pymol'] = pymol_module
    if 'pymol.cmd' not in sys.modules:
        sys.modules['pymol.cmd'] = _make_stub('cmd')()

    qt_module = types.ModuleType('pymol.Qt')
    qt_module.QtWidgets = _make_stub('QtWidgets')
    qt_module.QtCore = _make_stub('QtCore')
    qt_module.QtGui = _make_stub('QtGui')
    sys.modules['pymol.Qt'] = qt_module
    setattr(sys.modules['pymol'], 'Qt', qt_module)
    return True


def load_manager():
    """Import pymolshortcuts_manager, stubbing Qt when it is unavailable."""
    stubbed = _install_stubs()
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import importlib
    module = importlib.import_module("pymolshortcuts_manager")
    module._mcp_stubbed_qt = stubbed
    return module


MANAGER = load_manager()
LIVE_AVAILABLE = not getattr(MANAGER, "_mcp_stubbed_qt", True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def default_shortcuts_path():
    """Best guess at the user's pymolshortcuts.py."""
    from_env = os.environ.get("PYMOLSHORTCUTS_PATH", "")
    if from_env and os.path.isfile(from_env):
        return from_env
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "pymolshortcuts.py"),
        os.path.join(home, "Library", "PyMOL", "startup", "pymolshortcuts.py"),
        os.path.join(home, ".pymol", "startup", "pymolshortcuts.py"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "pymolshortcuts.py"),
    ]
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidates.append(
            os.path.join(appdata, "PyMOL", "startup", "pymolshortcuts.py")
        )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ""


def load_shortcuts(path=None):
    """Parse the shortcuts file into ShortcutData objects."""
    path = path or default_shortcuts_path()
    if not path or not os.path.isfile(path):
        return [], ""
    return MANAGER.ShortcutsParser.parse_shortcuts(path), path


def score(query, shortcut):
    """Rank one shortcut against a query by shared word count."""
    words = set(w for w in query.lower().split() if len(w) > 2)
    if not words:
        return 0
    haystack = " ".join([
        shortcut.name or "", shortcut.description or "",
        shortcut.usage or "", shortcut.details or "",
    ]).lower()
    hits = sum(1 for word in words if word in haystack)
    if shortcut.name and shortcut.name.lower() in words:
        hits += 3
    return hits


def shortcut_summary(shortcut):
    return {
        "name": shortcut.name,
        "description": (shortcut.description or "").strip(),
        "usage": (shortcut.usage or "").strip(),
    }


def shortcut_detail(shortcut):
    return {
        "name": shortcut.name,
        "description": shortcut.description,
        "usage": shortcut.usage,
        "arguments": shortcut.arguments,
        "example": shortcut.example,
        "details": shortcut.details,
        "pml_vertical": shortcut.pml_vertical,
        "pml_horizontal": shortcut.pml_horizontal,
        "python_code": shortcut.python_code,
    }


DOCSTRING_CONTRACT = """\
A pymolshortcuts shortcut is one top-level function plus one cmd.extend call.

The function's docstring must carry these eight headers, each alone on its
line, in this order:
  DESCRIPTION:
  USAGE:
  ARGUMENTS:
  EXAMPLE:
  MORE DETAILS:
  VERTICAL PML SCRIPT:
  HORIZONTAL PML SCRIPT:
  PYTHON CODE:

DESCRIPTION, USAGE, EXAMPLE, and PYTHON CODE must be non-empty. Write None
under ARGUMENTS when the function takes no arguments.

The horizontal PML script holds the same commands as the vertical one,
joined with semicolons instead of newlines.

The module must end with cmd.extend('<name>', <name>) where <name> matches
the function name exactly.

These calls are banned because the code runs in a live PyMOL session:
%s
""" % ", ".join(MANAGER.AGENTIC_BANNED_CALLS)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_list_shortcuts(query="", limit=50, shortcuts_path=""):
    shortcuts, path = load_shortcuts(shortcuts_path or None)
    if not shortcuts:
        return {"count": 0, "shortcuts": [], "source": path,
                "note": "No shortcuts file was found. Pass shortcuts_path or "
                        "set PYMOLSHORTCUTS_PATH."}
    if query:
        ranked = sorted(shortcuts, key=lambda s: score(query, s), reverse=True)
        ranked = [s for s in ranked if score(query, s) > 0] or ranked
    else:
        ranked = sorted(shortcuts, key=lambda s: (s.name or "").lower())
    trimmed = ranked[:max(1, int(limit))]
    return {
        "count": len(trimmed),
        "total": len(shortcuts),
        "source": path,
        "shortcuts": [shortcut_summary(s) for s in trimmed],
    }


def tool_get_shortcut(name, shortcuts_path=""):
    shortcuts, path = load_shortcuts(shortcuts_path or None)
    for shortcut in shortcuts:
        if shortcut.name == name:
            detail = shortcut_detail(shortcut)
            detail["source"] = path
            return detail
    return {"error": f"No shortcut named {name} was found in {path or 'any file'}."}


def tool_docstring_contract():
    return {"contract": DOCSTRING_CONTRACT}


def tool_validate_candidate(source, name):
    result = MANAGER.CandidateValidator.static_check(source, name)
    payload = result.to_dict()
    payload["summary"] = ("The candidate passed the static check."
                          if result.ok
                          else "The candidate failed the static check.")
    return payload


def tool_write_candidate(name, source, run_dir="", scratch_root=""):
    directory = run_dir or MANAGER.agentic_run_dir(
        name, scratch_root or MANAGER.AGENTIC_SCRATCH_ROOT
    )
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"candidate_{name}.py")
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(source)
    return {"path": path, "run_dir": directory}


def tool_write_candidate_tests(name, source, run_dir):
    if not run_dir or not os.path.isdir(run_dir):
        return {"error": f"No run directory at {run_dir}."}
    path = os.path.join(run_dir, f"test_candidate_{name}.py")
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(source)
    return {"path": path}


def tool_run_candidate_tests(name, run_dir, timeout=300):
    test_path = os.path.join(run_dir, f"test_candidate_{name}.py")
    result = MANAGER.CandidateValidator.run_pytest(
        test_path, cwd=run_dir, timeout=int(timeout)
    )
    return result.to_dict()


def tool_run_in_pymol(name, source, reference="", arguments=""):
    if os.environ.get(LIVE_ENV_FLAG, "") != "1":
        return {
            "error": "The live tier is disabled. Set "
                     f"{LIVE_ENV_FLAG}=1 in the server's environment to "
                     "allow generated code to run in PyMOL.",
            "ok": False,
        }
    if not LIVE_AVAILABLE:
        return {
            "error": "This server is running outside PyMOL, so there is no "
                     "session to run the candidate in.",
            "ok": False,
        }
    static = MANAGER.CandidateValidator.static_check(source, name)
    if not static.ok:
        return {
            "error": "The static check must pass before the live tier runs.",
            "static": static.to_dict(),
            "ok": False,
        }
    result = MANAGER.CandidateValidator.live_check(
        name, source,
        reference=reference or MANAGER.AGENTIC_REFERENCE_STRUCTURE,
        arguments=arguments,
    )
    return result.to_dict()


def tool_append_shortcut(name, source, shortcuts_path=""):
    static = MANAGER.CandidateValidator.static_check(source, name)
    if not static.ok:
        return {"ok": False,
                "error": "The static check must pass before appending.",
                "static": static.to_dict()}
    path = shortcuts_path or default_shortcuts_path()
    if not path or not os.path.isfile(path):
        return {"ok": False,
                "error": f"No shortcuts file at {path or '(none found)'}."}
    try:
        backup = MANAGER.agentic_append_to_shortcuts(path, source)
    except (IOError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": path, "backup": backup}


def tool_list_skills(working_dir=""):
    registry = MANAGER.SkillRegistry(working_dir=working_dir or None)
    skills = registry.scan()
    return {
        "count": len(skills),
        "search_paths": registry.search_paths(),
        "skills": [skill.to_dict() for skill in skills],
    }


def tool_read_skill(name, working_dir=""):
    registry = MANAGER.SkillRegistry(working_dir=working_dir or None)
    skill = registry.find(name)
    if skill is None:
        return {"error": f"No skill named {name} was found."}
    payload = skill.to_dict()
    payload["body"] = skill.body
    return payload


def tool_agent_runs(limit=20):
    store = MANAGER.AgentRunStore()
    records = store.load()
    return {"count": len(records), "runs": records[-int(limit):]}


TOOLS = [
    {
        "name": "list_shortcuts",
        "description": "List the shortcuts in pymolshortcuts.py, optionally "
                       "ranked against a query. Start here to learn what "
                       "already exists before writing a new shortcut.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Optional words to rank against."},
                "limit": {"type": "integer", "default": 50},
                "shortcuts_path": {"type": "string",
                                   "description": "Path to pymolshortcuts.py."},
            },
        },
        "handler": tool_list_shortcuts,
    },
    {
        "name": "get_shortcut",
        "description": "Return every docstring section, both PML scripts, and "
                       "the Python code for one shortcut. Use two or three of "
                       "these as style examples before authoring a new one.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "shortcuts_path": {"type": "string"},
            },
            "required": ["name"],
        },
        "handler": tool_get_shortcut,
    },
    {
        "name": "docstring_contract",
        "description": "Return the docstring contract every shortcut must "
                       "satisfy, including the banned calls.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_docstring_contract,
    },
    {
        "name": "validate_candidate",
        "description": "Run the static validation tier over a candidate "
                       "module: it parses, defines exactly one function of "
                       "the right name, carries a parseable docstring with "
                       "every required section, registers itself with "
                       "cmd.extend, and contains no banned call.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string",
                           "description": "The full candidate module."},
                "name": {"type": "string",
                         "description": "The expected shortcut name."},
            },
            "required": ["source", "name"],
        },
        "handler": tool_validate_candidate,
    },
    {
        "name": "write_candidate",
        "description": "Write a candidate module into a scratch run "
                       "directory and return its path. Creates the directory "
                       "when run_dir is omitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "source": {"type": "string"},
                "run_dir": {"type": "string"},
                "scratch_root": {"type": "string"},
            },
            "required": ["name", "source"],
        },
        "handler": tool_write_candidate,
    },
    {
        "name": "write_candidate_tests",
        "description": "Write a pytest module for a candidate into the same "
                       "run directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "source": {"type": "string"},
                "run_dir": {"type": "string"},
            },
            "required": ["name", "source", "run_dir"],
        },
        "handler": tool_write_candidate_tests,
    },
    {
        "name": "run_candidate_tests",
        "description": "Run pytest over the generated test module in a run "
                       "directory and return the outcome with the tail of the "
                       "output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "run_dir": {"type": "string"},
                "timeout": {"type": "integer", "default": 300},
            },
            "required": ["name", "run_dir"],
        },
        "handler": tool_run_candidate_tests,
    },
    {
        "name": "run_in_pymol",
        "description": "Execute a candidate in the live PyMOL session against "
                       "a reference structure. Refused unless the server runs "
                       "inside PyMOL and its environment sets "
                       "PYMOLSHORTCUTS_MCP_ALLOW_LIVE=1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "source": {"type": "string"},
                "reference": {"type": "string",
                              "description": "PDB identifier to fetch first."},
                "arguments": {"type": "string"},
            },
            "required": ["name", "source"],
        },
        "handler": tool_run_in_pymol,
    },
    {
        "name": "append_shortcut",
        "description": "Append a validated candidate to the shortcuts file "
                       "after writing a timestamped backup. Refuses any "
                       "candidate that fails the static tier.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "source": {"type": "string"},
                "shortcuts_path": {"type": "string"},
            },
            "required": ["name", "source"],
        },
        "handler": tool_append_shortcut,
    },
    {
        "name": "list_skills",
        "description": "List the SKILL.md files discovered in the bundled, "
                       "project, and user skill directories.",
        "inputSchema": {
            "type": "object",
            "properties": {"working_dir": {"type": "string"}},
        },
        "handler": tool_list_skills,
    },
    {
        "name": "read_skill",
        "description": "Return the full body of one discovered skill.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "working_dir": {"type": "string"},
            },
            "required": ["name"],
        },
        "handler": tool_read_skill,
    },
    {
        "name": "agent_runs",
        "description": "Return the most recent entries from the agent run log "
                       "written by the Agentic AI tab.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        },
        "handler": tool_agent_runs,
    },
]

TOOL_INDEX = {tool["name"]: tool for tool in TOOLS}


def public_tools():
    """The tool list as the protocol wants it, without the handlers."""
    return [{k: v for k, v in tool.items() if k != "handler"}
            for tool in TOOLS]


def call_tool(name, arguments):
    """Dispatch one tool call and wrap the result as MCP content."""
    tool = TOOL_INDEX.get(name)
    if tool is None:
        return {
            "content": [{"type": "text",
                         "text": f"There is no tool named {name}."}],
            "isError": True,
        }
    try:
        payload = tool["handler"](**(arguments or {}))
    except TypeError as exc:
        return {
            "content": [{"type": "text",
                         "text": f"Bad arguments for {name}: {exc}"}],
            "isError": True,
        }
    except Exception as exc:                         # noqa: BLE001
        return {
            "content": [{"type": "text",
                         "text": f"{name} failed: {exc}\n"
                                 f"{traceback.format_exc()}"}],
            "isError": True,
        }
    is_error = bool(isinstance(payload, dict) and payload.get("error"))
    return {
        "content": [{"type": "text",
                     "text": json.dumps(payload, indent=2, default=str)}],
        "isError": is_error,
    }


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------

def handle_request(message):
    """Turn one decoded JSON-RPC message into a response, or None."""
    method = message.get("method", "")
    params = message.get("params") or {}
    request_id = message.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion",
                                          MCP_PROTOCOL_VERSION),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Tools for authoring PyMOL shortcuts. Call docstring_contract "
                "and list_shortcuts before writing anything, validate every "
                "candidate with validate_candidate, and never call "
                "append_shortcut on a candidate that has not passed."
            ),
        }
    elif method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": public_tools()}
    elif method == "tools/call":
        result = call_tool(params.get("name", ""), params.get("arguments"))
    elif method == "resources/list":
        result = {"resources": []}
    elif method == "prompts/list":
        result = {"prompts": []}
    else:
        if request_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }

    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(stdin=None, stdout=None):
    """Read newline-delimited JSON-RPC from stdin until it closes."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        try:
            response = handle_request(message)
        except Exception as exc:                     # noqa: BLE001
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32603, "message": str(exc)},
            }
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


def pymolshortcuts_mcp_serve():
    """Entry point for running the server from inside PyMOL."""
    serve()


try:                                                 # pragma: no cover
    from pymol import cmd as _pymol_cmd
    if LIVE_AVAILABLE and hasattr(_pymol_cmd, "extend"):
        _pymol_cmd.extend('pymolshortcuts_mcp_serve', pymolshortcuts_mcp_serve)
except Exception:                                    # noqa: BLE001
    pass


if __name__ == "__main__":                           # pragma: no cover
    serve()

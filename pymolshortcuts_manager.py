# -*- coding: utf-8 -*-
"""
PyMOL Shortcuts Manager Plugin
================================

A PyQt-based plugin for managing PyMOL shortcuts from pymolshorts.py.

Features:
- Installation tab for shortcuts and psico package dependencies
- Searchable table of all available shortcuts
- Click-to-execute functionality
- Operating system detection
- Automated psico installation via conda

Author: Blaine Mooers
License: MIT
"""

from __future__ import print_function, division
import sys
import os
import re
import ast
import shlex
import shutil
import signal
import platform
import subprocess
import threading
import urllib.request
import urllib.error
import json
import base64
import hashlib
import time
from datetime import datetime
from pymol import cmd
from pymol.Qt import QtWidgets, QtCore, QtGui

# Module-level path set by __init_plugin__ when auto-load is active.
# The GUI reads this on startup so it can populate the Shortcuts tab
# immediately without requiring the user to reinstall the file.
_auto_loaded_shortcuts_path = None

# Optional dark-theme support via pyqtdarktheme (pip install pyqtdarktheme)
try:
    import qdarktheme
    QDARKTHEME_AVAILABLE = True
except ImportError:
    QDARKTHEME_AVAILABLE = False


class ShortcutData:
    """Data class to hold information about a single shortcut."""
    
    def __init__(self, name, description="", usage="", arguments="", 
                 example="", details="", pml_vertical="", pml_horizontal="", 
                 python_code=""):
        self.name = name
        self.description = description
        self.usage = usage
        self.arguments = arguments
        self.example = example
        self.details = details
        self.pml_vertical = pml_vertical
        self.pml_horizontal = pml_horizontal
        self.python_code = python_code
        self.keybinding = name  # The shortcut name IS the keybinding


class ShortcutsParser:
    """Parse the pymolshorts.py file to extract shortcut information."""
    
    @staticmethod
    def parse_shortcuts(filepath):
        """
        Parse the pymolshorts.py file and extract all shortcuts.
        
        Returns a list of ShortcutData objects.
        """
        shortcuts = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            return shortcuts
        
        # Pattern to find function definitions with cmd.extend
        pattern = r"def\s+(\w+)\([^)]*\):\s*'''\s*(.*?)'''\s*(.*?)(?=\ndef\s+\w+\(|$)"
        
        matches = re.finditer(pattern, content, re.DOTALL)
        
        for match in matches:
            func_name = match.group(1)
            docstring = match.group(2)
            
            # Parse the docstring
            shortcut = ShortcutsParser._parse_docstring(func_name, docstring)
            if shortcut:
                shortcuts.append(shortcut)
        
        return shortcuts
    
    @staticmethod
    def _parse_docstring(name, docstring):
        """Parse the docstring to extract structured information."""
        
        sections = {
            'DESCRIPTION:': 'description',
            'USAGE:': 'usage',
            'ARGUMENTS:': 'arguments',
            'EXAMPLE:': 'example',
            'MORE DETAILS:': 'details',
            'VERTICAL PML SCRIPT:': 'pml_vertical',
            'HORIZONTAL PML SCRIPT:': 'pml_horizontal',
            'PYTHON CODE:': 'python_code'
        }
        
        data = {'name': name}
        current_section = None
        current_content = []
        
        lines = docstring.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            
            # Check if this line starts a new section
            section_found = False
            for marker, key in sections.items():
                if marker in line_stripped:
                    # Save previous section
                    if current_section:
                        data[current_section] = '\n'.join(current_content).strip()
                    
                    current_section = key
                    current_content = []
                    section_found = True
                    break
            
            if not section_found and current_section:
                current_content.append(line.strip())
        
        # Save the last section
        if current_section:
            data[current_section] = '\n'.join(current_content).strip()
        
        # Only return if we have at least a description
        if 'description' in data and data['description']:
            return ShortcutData(**data)
        
        return None


# ===================================================================
# Agentic AI support layer
# ===================================================================
#
# Everything between this banner and the InstallationTab class is free
# of Qt so that it can be unit tested without a display server and
# reused by the companion MCP server (pymolshortcuts_mcp.py).
#
# The layer has five parts:
#   1. Module-level configuration and prompt templates.
#   2. HarnessConfig plus the HarnessAdapter family, which turn a
#      configuration into an argument vector for one headless run of a
#      coding agent (Claude Code, Pi, or any other CLI).
#   3. HarnessProcess, which runs that argument vector, streams the
#      output line by line, and enforces a timeout.
#   4. SkillRegistry, which discovers SKILL.md files on disk.
#   5. CandidateValidator and AgentRunStore, which gate and record the
#      generated shortcuts.
# ===================================================================

AGENTIC_SCRATCH_ROOT = os.path.join(
    os.path.expanduser("~"), ".pymolshortcuts", "agent"
)
AGENTIC_RUNS_FILE = os.path.join(AGENTIC_SCRATCH_ROOT, "runs.json")
AGENTIC_REFERENCE_STRUCTURE = "1lw9"
AGENTIC_DEFAULT_TIMEOUT = 600
AGENTIC_MAX_REPAIR_ATTEMPTS = 3
AGENTIC_MAX_RUN_RECORDS = 200

# Calls that must never appear in a candidate shortcut, because the
# candidate is executed inside the user's live PyMOL session.
AGENTIC_BANNED_CALLS = (
    "eval", "exec", "compile", "__import__", "input",
    "os.system", "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "shutil.rmtree", "shutil.move",
    "subprocess.run", "subprocess.call", "subprocess.Popen",
    "subprocess.check_call", "subprocess.check_output",
)

AGENTIC_PROMPT_TEMPLATES = {
    "generate": """\
You are writing one new shortcut for pymolshortcuts.py, the PyMOL shortcut
library maintained by the Mooers Laboratory.

GOAL
{goal}

REQUESTED SHORTCUT
name: {name}
description: {description}
usage: {usage}
arguments: {arguments}
example: {example}
details: {details}

HOUSE STYLE, TAKEN FROM EXISTING SHORTCUTS
{context}

REQUIREMENTS
1. Write exactly one top-level function named {name}.
2. Give it a single-quoted triple-quoted docstring containing these
   sections, each on its own line and in this order:
   DESCRIPTION:, USAGE:, ARGUMENTS:, EXAMPLE:, MORE DETAILS:,
   VERTICAL PML SCRIPT:, HORIZONTAL PML SCRIPT:, PYTHON CODE:
3. The HORIZONTAL PML SCRIPT section must hold the same commands as the
   vertical one, separated by semicolons instead of newlines.
4. End the module with cmd.extend('{name}', {name}).
5. Import nothing except `from pymol import cmd` and the standard library.
6. Do not call eval, exec, os.system, subprocess, or shutil.rmtree.
7. The function must run without error on the structure {reference_structure}.

OUTPUT
Write the finished module to {output_dir}/candidate_{name}.py and nothing else.
""",
    "test": """\
Write a pytest module that tests the shortcut in {output_dir}/candidate_{name}.py.

REQUIREMENTS
1. Mock `pymol` and `pymol.cmd` before importing the candidate, so the test
   runs with no PyMOL installation and no display server.
2. Assert that calling {name} issues the PyMOL commands its docstring
   promises, by inspecting the recorded calls on the mocked cmd object.
3. Assert that the docstring carries every required section.
4. Cover the default arguments and at least one non-default argument.
5. Use only pytest and unittest.mock.

OUTPUT
Write the test module to {output_dir}/test_candidate_{name}.py and nothing else.
""",
    "document": """\
Write the documentation for the shortcut in {output_dir}/candidate_{name}.py.

Produce a single Markdown file containing three clearly separated parts:
1. A README entry in the style of the existing shortcut entries, one short
   paragraph plus a fenced PyMOL example.
2. A reStructuredText block suitable for pasting into index.rst.
3. A tutorial entry as a Python dictionary literal with the keys
   title, summary, steps, and commands, where steps is a list of strings
   and commands is a list of PyMOL command strings.

OUTPUT
Write the file to {output_dir}/docs_{name}.md and nothing else.
""",
    "review": """\
The candidate shortcut {name} in {output_dir}/candidate_{name}.py failed
validation. Repair it.

FAILURES
{failures}

REQUIREMENTS
1. Fix every failure listed above.
2. Do not change the shortcut's name or its stated purpose.
3. Keep every docstring section that is already correct.
4. Rewrite {output_dir}/candidate_{name}.py in place and change nothing else.
""",
}


def agentic_render(template, values):
    """Fill a prompt template, leaving unknown placeholders untouched.

    Using a forgiving mapping keeps a user-edited template from raising
    KeyError when it mentions a placeholder this release does not supply.
    """
    class _Forgiving(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return template.format_map(_Forgiving(values))
    except (ValueError, IndexError):
        # An unbalanced brace in a user-edited template.
        return template


def agentic_run_dir(name, root=None, stamp=None):
    """Return the scratch directory for one run, creating it if needed."""
    root = root or AGENTIC_SCRATCH_ROOT
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(name) or "run")
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(root, f"{safe}-{stamp}")
    os.makedirs(path, exist_ok=True)
    return path


class HarnessConfig:
    """Everything needed to launch one headless run of a coding agent."""

    def __init__(self, harness="claude-code", executable="", working_dir="",
                 model="", provider="", permission_mode="", thinking="",
                 mode="print", output_format="text", extra_flags="",
                 argv_template="", rpc_template="", timeout=AGENTIC_DEFAULT_TIMEOUT,
                 env_overlay=None):
        self.harness = harness
        self.executable = executable
        self.working_dir = working_dir
        self.model = model
        self.provider = provider
        self.permission_mode = permission_mode
        self.thinking = thinking
        self.mode = mode
        self.output_format = output_format
        self.extra_flags = extra_flags
        self.argv_template = argv_template
        self.rpc_template = rpc_template
        self.timeout = int(timeout or AGENTIC_DEFAULT_TIMEOUT)
        self.env_overlay = dict(env_overlay or {})

    def to_dict(self):
        return {
            "harness": self.harness,
            "executable": self.executable,
            "working_dir": self.working_dir,
            "model": self.model,
            "provider": self.provider,
            "permission_mode": self.permission_mode,
            "thinking": self.thinking,
            "mode": self.mode,
            "output_format": self.output_format,
            "extra_flags": self.extra_flags,
            "argv_template": self.argv_template,
            "rpc_template": self.rpc_template,
            "timeout": self.timeout,
            "env_overlay": dict(self.env_overlay),
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: v for k, v in (data or {}).items()
                      if k in cls().to_dict()})

    def extra_flag_list(self):
        """Split the free-text extra flags the way a shell would."""
        if not self.extra_flags:
            return []
        try:
            return shlex.split(self.extra_flags)
        except ValueError:
            return self.extra_flags.split()


class HarnessAdapter:
    """Base class. One subclass per coding agent.

    Every command-line string for a given agent lives inside its
    ``run_argv``.  When a vendor renames a flag, exactly one method
    changes.
    """

    name = "generic"
    display_name = "Generic CLI"
    default_executable = ""
    extra_search_dirs = ()

    def __init__(self, config=None):
        self.config = config or HarnessConfig(harness=self.name)

    # -- discovery ---------------------------------------------------
    @classmethod
    def detect(cls, extra_paths=None):
        """Return the path to the executable, or None when not found."""
        if not cls.default_executable:
            return None
        found = shutil.which(cls.default_executable)
        if found:
            return found
        candidates = list(extra_paths or []) + list(cls.extra_search_dirs)
        for directory in candidates:
            candidate = os.path.join(
                os.path.expanduser(directory), cls.default_executable
            )
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    def executable(self):
        return (self.config.executable
                or self.detect()
                or self.default_executable)

    # -- command construction ----------------------------------------
    def version_argv(self):
        return [self.executable(), "--version"]

    def run_argv(self, prompt, skills=None, output_dir=None):
        raise NotImplementedError

    def stdin_payload(self, prompt, skills=None, output_dir=None):
        """Text to write to the child's stdin, or None."""
        return None

    def environment(self, base=None):
        env = dict(base if base is not None else os.environ)
        env.update(self.config.env_overlay)
        return env

    # -- output ------------------------------------------------------
    def parse_line(self, line):
        """Return (text_to_display, structured_event_or_None)."""
        return line, None

    # -- helpers -----------------------------------------------------
    @staticmethod
    def skill_names(skills):
        names = []
        for skill in skills or []:
            names.append(getattr(skill, "name", skill))
        return [n for n in names if n]

    def skill_preamble(self, skills):
        """Text prepended to the prompt naming the skills to use."""
        names = self.skill_names(skills)
        if not names:
            return ""
        return ("Use these skills for this task: "
                + ", ".join(names) + ".\n\n")

    def inline_skills(self, skills):
        """Full SKILL.md bodies, for harnesses with no skill mechanism."""
        blocks = []
        for skill in skills or []:
            body = getattr(skill, "body", "")
            name = getattr(skill, "name", "")
            if body:
                blocks.append(f"### Skill: {name}\n{body}")
        if not blocks:
            return ""
        return ("Follow the instructions in these skill documents.\n\n"
                + "\n\n".join(blocks) + "\n\n")


class ClaudeCodeAdapter(HarnessAdapter):
    """Anthropic Claude Code, driven through its headless print mode."""

    name = "claude-code"
    display_name = "Claude Code"
    default_executable = "claude"
    extra_search_dirs = ("~/.claude/local", "~/.local/bin", "/usr/local/bin")
    permission_modes = ("", "default", "acceptEdits", "plan",
                        "bypassPermissions")
    output_formats = ("text", "json", "stream-json")

    def run_argv(self, prompt, skills=None, output_dir=None):
        cfg = self.config
        argv = [self.executable(), "-p",
                self.skill_preamble(skills) + prompt]
        if cfg.model:
            argv += ["--model", cfg.model]
        if cfg.permission_mode:
            argv += ["--permission-mode", cfg.permission_mode]
        if cfg.output_format and cfg.output_format != "text":
            argv += ["--output-format", cfg.output_format]
            if cfg.output_format == "stream-json":
                argv += ["--verbose"]
        argv += cfg.extra_flag_list()
        return argv

    def parse_line(self, line):
        if self.config.output_format != "stream-json":
            return line, None
        stripped = line.strip()
        if not stripped.startswith("{"):
            return line, None
        try:
            event = json.loads(stripped)
        except ValueError:
            return line, None
        text = _agentic_event_text(event)
        return (text if text else ""), event


class PIAdapter(HarnessAdapter):
    """The Pi coding agent.

    Pi offers three non-interactive modes.  Print mode is the default
    here because it needs no protocol handshake.  JSON mode streams
    events as JSON lines.  RPC mode speaks JSON-RPC over stdin and
    stdout, so the request body is a user-editable template.
    """

    name = "pi"
    display_name = "Pi"
    default_executable = "pi"
    extra_search_dirs = ("~/.local/bin", "/usr/local/bin", "~/.pi/bin")
    modes = ("print", "json", "rpc")
    thinking_levels = ("", "off", "minimal", "low", "medium", "high",
                       "xhigh", "max")
    default_rpc_template = (
        '{"jsonrpc": "2.0", "id": 1, "method": "prompt", '
        '"params": {"prompt": %PROMPT_JSON%}}'
    )

    def run_argv(self, prompt, skills=None, output_dir=None):
        cfg = self.config
        exe = self.executable()
        mode = (cfg.mode or "print").lower()
        text = self.skill_preamble(skills) + prompt

        if mode == "rpc":
            argv = [exe, "--mode", "rpc"]
        elif mode == "json":
            argv = [exe, "--mode", "json", "-p", text]
        else:
            argv = [exe, "-p", text]

        if cfg.provider:
            argv += ["--provider", cfg.provider]
        if cfg.model:
            argv += ["--model", cfg.model]
        if cfg.thinking:
            argv += ["--thinking", cfg.thinking]
        # Every run is ephemeral, so one failed experiment cannot poison
        # the next one through a resumed session.
        argv += ["--no-session"]
        if cfg.permission_mode == "approve":
            argv += ["--approve"]
        elif cfg.permission_mode == "no-approve":
            argv += ["--no-approve"]
        argv += cfg.extra_flag_list()
        return argv

    def stdin_payload(self, prompt, skills=None, output_dir=None):
        if (self.config.mode or "print").lower() != "rpc":
            return None
        text = self.skill_preamble(skills) + prompt
        template = self.config.rpc_template or self.default_rpc_template
        return template.replace("%PROMPT_JSON%", json.dumps(text)) + "\n"

    def parse_line(self, line):
        mode = (self.config.mode or "print").lower()
        if mode not in ("json", "rpc"):
            return line, None
        stripped = line.strip()
        if not stripped.startswith("{"):
            return line, None
        try:
            event = json.loads(stripped)
        except ValueError:
            return line, None
        text = _agentic_event_text(event)
        return (text if text else ""), event


class GenericCLIAdapter(HarnessAdapter):
    """Any other harness, driven through a user-supplied argv template.

    The template is split the way a shell would split it, then four
    placeholders are substituted:  %PROMPT%, %CWD%, %SKILLS%, %OUTDIR%,
    and %MODEL%.  A harness with no skill mechanism receives the full
    text of each selected SKILL.md inlined into the prompt.
    """

    name = "generic"
    display_name = "Generic CLI"
    default_template = "%EXE% -p %PROMPT%"

    def executable(self):
        return self.config.executable or ""

    def version_argv(self):
        exe = self.executable()
        return [exe, "--version"] if exe else []

    def run_argv(self, prompt, skills=None, output_dir=None):
        template = self.config.argv_template or self.default_template
        text = self.inline_skills(skills) + prompt
        try:
            parts = shlex.split(template)
        except ValueError:
            parts = template.split()
        substitutions = {
            "%EXE%": self.executable(),
            "%PROMPT%": text,
            "%CWD%": self.config.working_dir or os.getcwd(),
            "%SKILLS%": ",".join(self.skill_names(skills)),
            "%OUTDIR%": output_dir or "",
            "%MODEL%": self.config.model or "",
        }
        argv = []
        for part in parts:
            for key, value in substitutions.items():
                if key in part:
                    part = part.replace(key, value)
            argv.append(part)
        return [a for a in argv if a != ""] or [self.executable()]


HARNESS_ADAPTERS = {
    ClaudeCodeAdapter.name: ClaudeCodeAdapter,
    PIAdapter.name: PIAdapter,
    GenericCLIAdapter.name: GenericCLIAdapter,
}


def get_harness_adapter(config):
    """Return the adapter instance for a configuration."""
    cls = HARNESS_ADAPTERS.get(
        getattr(config, "harness", "generic"), GenericCLIAdapter
    )
    return cls(config)


def _agentic_event_text(event):
    """Pull human-readable text out of one streamed JSON event.

    Event shapes differ between harnesses and between releases of the
    same harness, so this walks the common shapes and gives up quietly
    rather than raising.
    """
    if not isinstance(event, dict):
        return ""
    for key in ("text", "content", "message", "delta", "result", "output"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            nested = _agentic_event_text(value)
            if nested:
                return nested
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    nested = _agentic_event_text(item)
                    if nested:
                        parts.append(nested)
            if parts:
                return "".join(parts)
    return ""


class HarnessResult:
    """Outcome of one harness run."""

    def __init__(self, exit_code=None, output="", timed_out=False,
                 error="", argv=None, artifacts=None, duration=0.0):
        self.exit_code = exit_code
        self.output = output
        self.timed_out = timed_out
        self.error = error
        self.argv = list(argv or [])
        self.artifacts = list(artifacts or [])
        self.duration = duration

    @property
    def ok(self):
        return (self.exit_code == 0
                and not self.timed_out
                and not self.error)

    def to_dict(self):
        return {
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "error": self.error,
            "argv": list(self.argv),
            "artifacts": list(self.artifacts),
            "duration": round(self.duration, 2),
        }


class HarnessProcess:
    """Run one harness invocation and stream its output.

    This class holds no Qt, so the test suite drives it directly with a
    scripted fake Popen and the MCP server reuses it unchanged.
    """

    def __init__(self, adapter, prompt, skills=None, output_dir=None,
                 timeout=None):
        self.adapter = adapter
        self.prompt = prompt
        self.skills = list(skills or [])
        self.output_dir = output_dir
        self.timeout = timeout or getattr(adapter.config, "timeout",
                                          AGENTIC_DEFAULT_TIMEOUT)
        self._process = None
        self._stopped = False

    def build(self):
        argv = self.adapter.run_argv(self.prompt, self.skills, self.output_dir)
        payload = self.adapter.stdin_payload(
            self.prompt, self.skills, self.output_dir
        )
        cwd = self.adapter.config.working_dir or None
        if cwd and not os.path.isdir(cwd):
            cwd = None
        return argv, payload, self.adapter.environment(), cwd

    def run(self, on_line=None):
        argv, payload, env, cwd = self.build()
        started = time.time()
        lines = []
        timer = None

        def emit(text):
            if text:
                lines.append(text)
                if on_line:
                    on_line(text)

        try:
            popen_kwargs = dict(
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=env,
                universal_newlines=True,
                bufsize=1,
            )
            if hasattr(os, "setsid"):
                # Own process group, so Stop kills the whole tree rather
                # than orphaning the agent's own child processes.
                popen_kwargs["start_new_session"] = True
            self._process = subprocess.Popen(argv, **popen_kwargs)
        except (OSError, ValueError) as exc:
            return HarnessResult(
                exit_code=None, output="", error=str(exc), argv=argv,
                duration=time.time() - started,
            )

        timed_out = {"value": False}

        def _on_timeout():
            timed_out["value"] = True
            self.stop()

        try:
            timer = threading.Timer(self.timeout, _on_timeout)
            timer.daemon = True
            timer.start()

            if payload is not None and self._process.stdin is not None:
                try:
                    self._process.stdin.write(payload)
                    self._process.stdin.flush()
                except (OSError, ValueError):
                    pass
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                except (OSError, ValueError):
                    pass

            if self._process.stdout is not None:
                for raw in self._process.stdout:
                    text, _event = self.adapter.parse_line(raw.rstrip("\n"))
                    emit(text)
            exit_code = self._process.wait()
        except Exception as exc:                     # noqa: BLE001
            return HarnessResult(
                exit_code=None, output="\n".join(lines), error=str(exc),
                argv=argv, duration=time.time() - started,
            )
        finally:
            if timer is not None:
                timer.cancel()

        return HarnessResult(
            exit_code=exit_code,
            output="\n".join(lines),
            timed_out=timed_out["value"],
            argv=argv,
            artifacts=self.collect_artifacts(),
            duration=time.time() - started,
        )

    def collect_artifacts(self):
        """List the files the harness left in the run directory."""
        if not self.output_dir or not os.path.isdir(self.output_dir):
            return []
        found = []
        for entry in sorted(os.listdir(self.output_dir)):
            full = os.path.join(self.output_dir, entry)
            if os.path.isfile(full):
                found.append(full)
        return found

    def stop(self):
        """Terminate the child and, where possible, its whole group."""
        self._stopped = True
        process = self._process
        if process is None:
            return False
        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
        except Exception:                            # noqa: BLE001
            try:
                process.terminate()
            except Exception:                        # noqa: BLE001
                return False
        return True


class SkillInfo:
    """One skill discovered on disk."""

    def __init__(self, name, description="", path="", source="", body=""):
        self.name = name
        self.description = description
        self.path = path
        self.source = source
        self.body = body

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "source": self.source,
        }

    def __repr__(self):
        return f"SkillInfo({self.name!r}, source={self.source!r})"


class SkillRegistry:
    """Find SKILL.md files in the user, project, and bundled locations.

    The registry deliberately avoids PyYAML.  A SKILL.md frontmatter
    block carries a handful of scalar keys, so a small hand-rolled
    reader keeps the plugin free of a new dependency.
    """

    USER_DIR = os.path.join(os.path.expanduser("~"), ".claude", "skills")

    def __init__(self, working_dir=None, bundled_dir=None, extra_dirs=None):
        self.working_dir = working_dir or ""
        self.bundled_dir = bundled_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "skills"
        )
        self.extra_dirs = list(extra_dirs or [])

    def search_paths(self):
        """Return the directories to scan, most specific last.

        A bundled skill is the fallback and a user skill wins, because
        the user's own copy is the one they have been editing.
        """
        paths = [self.bundled_dir]
        if self.working_dir:
            paths.append(os.path.join(self.working_dir, ".claude", "skills"))
        paths.extend(self.extra_dirs)
        paths.append(self.USER_DIR)
        seen = set()
        ordered = []
        for path in paths:
            expanded = os.path.expanduser(path)
            if expanded and expanded not in seen:
                seen.add(expanded)
                ordered.append(expanded)
        return ordered

    @staticmethod
    def parse_skill_md(path):
        """Read name, description, and body out of one SKILL.md."""
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            return None

        name = ""
        description = ""
        body = text
        lines = text.split('\n')
        if lines and lines[0].strip() == '---':
            end = None
            for index in range(1, len(lines)):
                if lines[index].strip() == '---':
                    end = index
                    break
            if end is not None:
                body = '\n'.join(lines[end + 1:]).strip()
                current_key = None
                buffer = []
                fields = {}

                def flush():
                    if current_key:
                        fields[current_key] = ' '.join(
                            part.strip() for part in buffer
                        ).strip()

                for raw in lines[1:end]:
                    if raw.strip() and not raw.startswith((' ', '\t')) \
                            and ':' in raw:
                        flush()
                        key, _, value = raw.partition(':')
                        current_key = key.strip().lower()
                        buffer = [value]
                    elif current_key is not None:
                        buffer.append(raw)
                flush()
                name = SkillRegistry._unquote(fields.get('name', ''))
                description = SkillRegistry._unquote(
                    fields.get('description', '')
                )

        if not name:
            name = os.path.basename(os.path.dirname(os.path.abspath(path)))
        return SkillInfo(name=name, description=description, path=path,
                         body=body)

    @staticmethod
    def _unquote(value):
        """Strip quotes and YAML block-scalar indicators from a value.

        A description written as a folded block (``description: >``) arrives
        with the indicator still attached, so remove it before the text
        reaches the skills table.
        """
        value = (value or "").strip()
        if value[:1] in ('>', '|'):
            value = value[1:].lstrip('-+0123456789').strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            return value[1:-1]
        return value

    def scan(self):
        """Return every skill found, deduplicated by name."""
        found = {}
        for directory in self.search_paths():
            if not os.path.isdir(directory):
                continue
            source = self._label(directory)
            try:
                entries = sorted(os.listdir(directory))
            except OSError:
                continue
            for entry in entries:
                skill_md = os.path.join(directory, entry, "SKILL.md")
                if not os.path.isfile(skill_md):
                    continue
                info = self.parse_skill_md(skill_md)
                if info is None:
                    continue
                info.source = source
                found[info.name] = info
        return sorted(found.values(), key=lambda s: s.name.lower())

    def _label(self, directory):
        if directory == os.path.expanduser(self.bundled_dir):
            return "bundled"
        if directory == os.path.expanduser(self.USER_DIR):
            return "user"
        return "project"

    def find(self, name):
        for skill in self.scan():
            if skill.name == name:
                return skill
        return None

    @staticmethod
    def install(skill, dest_root=None):
        """Copy a skill directory into the user's skills directory."""
        dest_root = dest_root or SkillRegistry.USER_DIR
        source_dir = os.path.dirname(os.path.abspath(skill.path))
        dest_dir = os.path.join(dest_root, os.path.basename(source_dir))
        os.makedirs(dest_root, exist_ok=True)
        if os.path.abspath(source_dir) == os.path.abspath(dest_dir):
            return dest_dir
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.copytree(source_dir, dest_dir)
        return dest_dir


class ValidationIssue:
    """One line of a validation report."""

    def __init__(self, tier, ok, message):
        self.tier = tier
        self.ok = ok
        self.message = message

    def __str__(self):
        return f"[{'pass' if self.ok else 'FAIL'}] {self.tier}: {self.message}"

    def to_dict(self):
        return {"tier": self.tier, "ok": self.ok, "message": self.message}


class ValidationResult:
    """The outcome of one validation tier."""

    def __init__(self, tier, issues=None, detail=""):
        self.tier = tier
        self.issues = list(issues or [])
        self.detail = detail

    @property
    def ok(self):
        return all(issue.ok for issue in self.issues)

    @property
    def failures(self):
        return [issue for issue in self.issues if not issue.ok]

    def failure_text(self):
        return "\n".join(f"- {issue.message}" for issue in self.failures)

    def add(self, ok, message):
        self.issues.append(ValidationIssue(self.tier, ok, message))
        return self

    def to_dict(self):
        return {
            "tier": self.tier,
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
            "detail": self.detail,
        }


class CandidateValidator:
    """Gate a generated shortcut before it reaches the user's library.

    Three tiers run in increasing order of cost and risk.  The static
    tier needs neither PyMOL nor a subprocess and catches most of what
    goes wrong, so it always runs first.
    """

    REQUIRED_SECTIONS = ("description", "usage", "example", "python_code")

    @staticmethod
    def static_check(source, expected_name):
        """Parse the candidate and confirm it is a well-formed shortcut."""
        result = ValidationResult("static")

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            result.add(False, f"the module does not parse: {exc}")
            return result
        result.add(True, "the module parses")

        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef)]
        if len(functions) == 1:
            result.add(True, "exactly one top-level function is defined")
        else:
            result.add(False,
                       f"expected exactly one top-level function, found "
                       f"{len(functions)}")
        if not functions:
            return result

        function = functions[0]
        if function.name == expected_name:
            result.add(True, f"the function is named {expected_name}")
        else:
            result.add(False,
                       f"the function is named {function.name}, "
                       f"but {expected_name} was requested")

        docstring = ast.get_docstring(function)
        if not docstring:
            result.add(False, "the function has no docstring")
        else:
            result.add(True, "the function has a docstring")
            parsed = ShortcutsParser._parse_docstring(function.name, docstring)
            if parsed is None:
                result.add(False,
                           "the docstring does not parse into shortcut "
                           "sections; a DESCRIPTION: section is required")
            else:
                result.add(True, "the docstring parses into shortcut sections")
                for section in CandidateValidator.REQUIRED_SECTIONS:
                    if getattr(parsed, section, ""):
                        result.add(True, f"the {section} section is filled")
                    else:
                        result.add(False, f"the {section} section is empty")

        if CandidateValidator._has_cmd_extend(tree, function.name):
            result.add(True, f"cmd.extend('{function.name}', ...) is present")
        else:
            result.add(False,
                       f"cmd.extend('{function.name}', {function.name}) "
                       f"is missing")

        for call in CandidateValidator._banned_calls(tree):
            result.add(False, f"the banned call {call} appears in the module")

        return result

    @staticmethod
    def _has_cmd_extend(tree, name):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "extend":
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "cmd":
                continue
            if node.args and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value == name:
                return True
        return False

    @staticmethod
    def _call_name(node):
        parts = []
        func = node.func
        while isinstance(func, ast.Attribute):
            parts.insert(0, func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.insert(0, func.id)
        return ".".join(parts)

    @staticmethod
    def _banned_calls(tree):
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = CandidateValidator._call_name(node)
                if name in AGENTIC_BANNED_CALLS and name not in hits:
                    hits.append(name)
        return hits

    @staticmethod
    def run_pytest(test_path, cwd=None, timeout=300, python=None):
        """Run the generated pytest module in a subprocess."""
        result = ValidationResult("pytest")
        if not test_path or not os.path.isfile(test_path):
            result.add(False, f"no test file at {test_path}")
            return result
        argv = [python or sys.executable, "-m", "pytest", test_path, "-q"]
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd or os.path.dirname(os.path.abspath(test_path)),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            result.add(False, f"pytest did not finish within {timeout} seconds")
            return result
        except OSError as exc:
            result.add(False, f"pytest could not be started: {exc}")
            return result
        result.detail = completed.stdout or ""
        if completed.returncode == 0:
            result.add(True, "every generated test passed")
        else:
            tail = "\n".join(result.detail.strip().split("\n")[-15:])
            result.add(False, f"pytest exited {completed.returncode}\n{tail}")
        return result

    @staticmethod
    def live_check_commands(name, reference=None, arguments=""):
        """PyMOL commands that exercise the candidate in a live session."""
        reference = reference or AGENTIC_REFERENCE_STRUCTURE
        call = f"{name} {arguments}".strip()
        return [
            "delete all",
            f"fetch {reference}, async=0",
            call,
        ]

    @staticmethod
    def live_check(name, source, reference=None, arguments="",
                   runner=None, snapshot_path=None):
        """Execute the candidate inside the running PyMOL session.

        The caller is responsible for obtaining the user's confirmation
        before calling this, because the code came from a model.
        """
        result = ValidationResult("live")
        run = runner or (lambda command: cmd.do(command))
        try:
            exec(compile(source, "<candidate>", "exec"),  # noqa: S102
                 {"cmd": cmd, "__name__": "candidate"})
        except Exception as exc:                     # noqa: BLE001
            result.add(False, f"the module failed to import: {exc}")
            return result
        result.add(True, "the module imports")

        for command in CandidateValidator.live_check_commands(
                name, reference, arguments):
            try:
                run(command)
            except Exception as exc:                 # noqa: BLE001
                result.add(False, f"`{command}` raised {exc}")
                return result
            result.add(True, f"`{command}` ran")

        if snapshot_path:
            try:
                run(f"png {snapshot_path}, dpi=150, ray=0")
                result.detail = snapshot_path
                result.add(True, f"a snapshot was written to {snapshot_path}")
            except Exception as exc:                 # noqa: BLE001
                result.add(False, f"the snapshot failed: {exc}")
        return result


class AgentRunStore:
    """Append-only JSON record of past agent runs."""

    def __init__(self, path=None, limit=AGENTIC_MAX_RUN_RECORDS):
        self.path = path or AGENTIC_RUNS_FILE
        self.limit = limit

    def load(self):
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def save(self, records):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        trimmed = records[-self.limit:]
        try:
            with open(self.path, 'w', encoding='utf-8') as handle:
                json.dump(trimmed, handle, indent=2)
        except OSError as exc:
            print(f"Could not write the agent run log: {exc}")
        return trimmed

    def add(self, record):
        records = self.load()
        entry = dict(record)
        entry.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
        records.append(entry)
        self.save(records)
        return entry

    def clear(self):
        self.save([])

    def export(self, path):
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(self.load(), handle, indent=2)
        return path


def agentic_append_to_shortcuts(shortcuts_path, code, backup=True):
    """Append a validated shortcut to the shortcuts file.

    A timestamped backup is written first, because the shortcuts file is
    the user's working library and an appended mistake is otherwise hard
    to undo.
    """
    if not shortcuts_path or not os.path.isfile(shortcuts_path):
        raise IOError(f"No shortcuts file at {shortcuts_path}")
    backup_path = ""
    if backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{shortcuts_path}.{stamp}.bak"
        shutil.copy2(shortcuts_path, backup_path)
    with open(shortcuts_path, 'a', encoding='utf-8') as handle:
        handle.write("\n\n" + code.rstrip() + "\n")
    return backup_path


class InstallationTab(QtWidgets.QWidget):
    """Tab for installing shortcuts and psico package dependencies."""

    # Emitted with the filepath after a successful install/run of the
    # shortcuts file.  The main dialog connects to this to refresh the
    # Shortcuts tab and persist the path in QSettings.
    shortcuts_installed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super(InstallationTab, self).__init__(parent)
        self.last_installed_path = None  # Track the last installed shortcuts file
        self.init_ui()
        self.detect_system()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()
        
        # System information group
        system_group = QtWidgets.QGroupBox("System Information")
        system_layout = QtWidgets.QFormLayout()
        
        self.os_label = QtWidgets.QLabel("Detecting...")
        self.pymol_path_label = QtWidgets.QLabel("Detecting...")
        self.python_version_label = QtWidgets.QLabel("Detecting...")
        self.darktheme_label = QtWidgets.QLabel("Detecting...")

        system_layout.addRow("Operating System:", self.os_label)
        system_layout.addRow("PyMOL Path:", self.pymol_path_label)
        system_layout.addRow("Python Version:", self.python_version_label)
        system_layout.addRow("Dark Theme Support:", self.darktheme_label)

        system_group.setLayout(system_layout)
        layout.addWidget(system_group)
        
        # Shortcuts installation group
        shortcuts_group = QtWidgets.QGroupBox("PyMOL Shortcuts Installation")
        shortcuts_layout = QtWidgets.QVBoxLayout()
        
        # Source selection
        source_label = QtWidgets.QLabel("Select shortcuts source:")
        shortcuts_layout.addWidget(source_label)
        
        # Radio buttons for source selection
        self.source_button_group = QtWidgets.QButtonGroup()
        
        self.local_file_radio = QtWidgets.QRadioButton("Load from local file")
        self.local_file_radio.setChecked(True)
        self.local_file_radio.toggled.connect(self.update_source_ui)
        self.source_button_group.addButton(self.local_file_radio)
        shortcuts_layout.addWidget(self.local_file_radio)
        
        self.github_radio = QtWidgets.QRadioButton("Download from GitHub")
        self.github_radio.toggled.connect(self.update_source_ui)
        self.source_button_group.addButton(self.github_radio)
        shortcuts_layout.addWidget(self.github_radio)
        
        # Local file selection (default)
        self.local_file_widget = QtWidgets.QWidget()
        local_file_layout = QtWidgets.QHBoxLayout()
        local_file_layout.setContentsMargins(20, 0, 0, 0)
        
        self.shortcuts_path_edit = QtWidgets.QLineEdit()
        self.shortcuts_path_edit.setPlaceholderText("Path to pymolshortcuts.py")
        
        self.browse_button = QtWidgets.QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse_shortcuts)
        
        local_file_layout.addWidget(QtWidgets.QLabel("File path:"))
        local_file_layout.addWidget(self.shortcuts_path_edit)
        local_file_layout.addWidget(self.browse_button)
        self.local_file_widget.setLayout(local_file_layout)
        shortcuts_layout.addWidget(self.local_file_widget)
        
        # GitHub download option
        self.github_widget = QtWidgets.QWidget()
        github_layout = QtWidgets.QVBoxLayout()
        github_layout.setContentsMargins(20, 0, 0, 0)
        
        github_url_layout = QtWidgets.QHBoxLayout()
        self.github_url_edit = QtWidgets.QLineEdit()
        self.github_url_edit.setText("https://raw.githubusercontent.com/MooersLab/pymolshortcuts/master/pymolshortcuts.py")
        self.github_url_edit.setPlaceholderText("GitHub raw URL")
        github_url_layout.addWidget(QtWidgets.QLabel("GitHub URL:"))
        github_url_layout.addWidget(self.github_url_edit)
        github_layout.addLayout(github_url_layout)
        
        # Option to save downloaded file
        self.save_downloaded_check = QtWidgets.QCheckBox("Save downloaded file to:")
        self.save_downloaded_check.setChecked(True)
        github_layout.addWidget(self.save_downloaded_check)
        
        save_path_layout = QtWidgets.QHBoxLayout()
        save_path_layout.setContentsMargins(20, 0, 0, 0)
        self.save_path_edit = QtWidgets.QLineEdit()
        home_dir = os.path.expanduser("~")
        default_save_path = os.path.join(home_dir, "pymolshortcuts.py")
        self.save_path_edit.setText(default_save_path)
        self.save_path_edit.setPlaceholderText("Save location")
        
        self.browse_save_button = QtWidgets.QPushButton("Browse...")
        self.browse_save_button.clicked.connect(self.browse_save_location)
        
        save_path_layout.addWidget(self.save_path_edit)
        save_path_layout.addWidget(self.browse_save_button)
        github_layout.addLayout(save_path_layout)
        
        self.github_widget.setLayout(github_layout)
        self.github_widget.setVisible(False)
        shortcuts_layout.addWidget(self.github_widget)
        
        # Install button
        self.install_shortcuts_btn = QtWidgets.QPushButton("Install Shortcuts")
        self.install_shortcuts_btn.clicked.connect(self.install_shortcuts)
        shortcuts_layout.addWidget(self.install_shortcuts_btn)
        
        # Status text
        self.shortcuts_status = QtWidgets.QTextEdit()
        self.shortcuts_status.setReadOnly(True)
        self.shortcuts_status.setMaximumHeight(100)
        shortcuts_layout.addWidget(self.shortcuts_status)
        
        shortcuts_group.setLayout(shortcuts_layout)
        layout.addWidget(shortcuts_group)
        
        # Psico package installation group
        psico_group = QtWidgets.QGroupBox("Psico Package Installation")
        psico_layout = QtWidgets.QVBoxLayout()
        
        info_label = QtWidgets.QLabel(
            "The psico package (including biomolecule.py and supercell.py) is required\n"
            "for some shortcuts. This plugin will check if psico is already installed\n"
            "by importing psico.fullinit and install it using conda if necessary."
        )
        info_label.setWordWrap(True)
        psico_layout.addWidget(info_label)
        
        # Permission fix for macOS
        self.mac_permission_check = QtWidgets.QCheckBox(
            "Fix write permissions (macOS only - requires sudo password)"
        )
        psico_layout.addWidget(self.mac_permission_check)
        
        # Check and Install buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.check_psico_btn = QtWidgets.QPushButton("Check Psico Installation")
        self.check_psico_btn.clicked.connect(self.check_psico)
        button_layout.addWidget(self.check_psico_btn)
        
        self.install_psico_btn = QtWidgets.QPushButton("Install Psico")
        self.install_psico_btn.clicked.connect(self.install_psico)
        button_layout.addWidget(self.install_psico_btn)
        
        psico_layout.addLayout(button_layout)
        
        self.psico_status = QtWidgets.QTextEdit()
        self.psico_status.setReadOnly(True)
        self.psico_status.setMaximumHeight(150)
        psico_layout.addWidget(self.psico_status)
        
        psico_group.setLayout(psico_layout)
        layout.addWidget(psico_group)

        # pyqtdarktheme installation group
        darktheme_group = QtWidgets.QGroupBox("Dark Theme Support (pyqtdarktheme)")
        darktheme_layout = QtWidgets.QVBoxLayout()

        darktheme_info = QtWidgets.QLabel(
            "The pyqtdarktheme package provides professional-quality Dark and Light\n"
            "themes for the plugin dialog.  Without it the Settings tab falls back to\n"
            "a basic built-in stylesheet.  Install it with pip into PyMOL's Python."
        )
        darktheme_info.setWordWrap(True)
        darktheme_layout.addWidget(darktheme_info)

        darktheme_btn_layout = QtWidgets.QHBoxLayout()

        self.check_darktheme_btn = QtWidgets.QPushButton("Check Installation")
        self.check_darktheme_btn.clicked.connect(self.check_darktheme)
        darktheme_btn_layout.addWidget(self.check_darktheme_btn)

        self.install_darktheme_btn = QtWidgets.QPushButton("Install pyqtdarktheme")
        self.install_darktheme_btn.clicked.connect(self.install_darktheme)
        darktheme_btn_layout.addWidget(self.install_darktheme_btn)

        darktheme_layout.addLayout(darktheme_btn_layout)

        self.darktheme_status = QtWidgets.QTextEdit()
        self.darktheme_status.setReadOnly(True)
        self.darktheme_status.setMaximumHeight(150)
        darktheme_layout.addWidget(self.darktheme_status)

        darktheme_group.setLayout(darktheme_layout)
        layout.addWidget(darktheme_group)

        layout.addStretch()
        self.setLayout(layout)
    
    def detect_system(self):
        """Detect operating system and relevant paths."""
        # Operating system
        system = platform.system()
        self.os_label.setText(f"{system} ({platform.release()})")

        # PyMOL path
        pymol_path = sys.executable
        self.pymol_path_label.setText(pymol_path)

        # Python version
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        self.python_version_label.setText(python_version)

        # Dark theme package
        if QDARKTHEME_AVAILABLE:
            try:
                version = qdarktheme.__version__
            except AttributeError:
                version = "unknown"
            self.darktheme_label.setText(
                f"pyqtdarktheme {version} — installed"
            )
        else:
            self.darktheme_label.setText(
                "Not installed  (pip install pyqtdarktheme)"
            )

        # Set appropriate permissions command based on OS
        if system == "Darwin":  # macOS
            self.mac_permission_check.setVisible(True)
        else:
            self.mac_permission_check.setVisible(False)
    
    def browse_shortcuts(self):
        """Open file browser to select pymolshorts.py."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select pymolshorts.py",
            "",
            "Python Files (*.py);;All Files (*)"
        )
        if filename:
            self.shortcuts_path_edit.setText(filename)
    
    def browse_save_location(self):
        """Open file browser to select save location for downloaded file."""
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save downloaded shortcuts file as",
            os.path.expanduser("~/pymolshortcuts.py"),
            "Python Files (*.py);;All Files (*)"
        )
        if filename:
            self.save_path_edit.setText(filename)
    
    def update_source_ui(self):
        """Update UI visibility based on selected source."""
        if self.local_file_radio.isChecked():
            self.local_file_widget.setVisible(True)
            self.github_widget.setVisible(False)
        else:
            self.local_file_widget.setVisible(False)
            self.github_widget.setVisible(True)
    
    def download_from_github(self, url, save_path=None):
        """Download pymolshortcuts.py from GitHub.
        
        Args:
            url: GitHub raw URL to download from
            save_path: Optional path to save the file
            
        Returns:
            Path to downloaded file (either saved location or temp file)
        """
        import tempfile
        
        self.shortcuts_status.append(f"Downloading from GitHub...")
        self.shortcuts_status.append(f"URL: {url}")
        QtWidgets.QApplication.processEvents()
        
        try:
            # Download the file
            response = urllib.request.urlopen(url, timeout=30)
            content = response.read()
            
            # Determine save location
            if save_path and save_path.strip():
                filepath = save_path
                # Create directory if it does not exist
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
            else:
                # Use temporary file
                fd, filepath = tempfile.mkstemp(suffix='.py', prefix='pymolshortcuts_')
                os.close(fd)
            
            # Write content to file
            with open(filepath, 'wb') as f:
                f.write(content)
            
            self.shortcuts_status.append(f"✓ Downloaded successfully!")
            if save_path and save_path.strip():
                self.shortcuts_status.append(f"✓ Saved to: {filepath}")
            else:
                self.shortcuts_status.append(f"✓ Using temporary file: {filepath}")
            
            return filepath
            
        except urllib.error.URLError as e:
            self.shortcuts_status.append(f"✗ Network error: {e.reason}")
            return None
        except urllib.error.HTTPError as e:
            self.shortcuts_status.append(f"✗ HTTP error {e.code}: {e.reason}")
            return None
        except Exception as e:
            self.shortcuts_status.append(f"✗ Error downloading file: {e}")
            return None
    
    def install_shortcuts(self):
        """Install the shortcuts by running the file."""
        self.shortcuts_status.clear()
        
        # Determine source
        if self.local_file_radio.isChecked():
            # Local file
            filepath = self.shortcuts_path_edit.text()
            
            if not filepath or not os.path.exists(filepath):
                self.shortcuts_status.append("Error: Please specify a valid shortcuts file.")
                return
            
            self.shortcuts_status.append(f"Installing shortcuts from local file: {filepath}")
        else:
            # GitHub download
            url = self.github_url_edit.text()
            
            if not url:
                self.shortcuts_status.append("Error: Please specify a GitHub URL.")
                return
            
            # Determine if we should save the file
            save_path = None
            if self.save_downloaded_check.isChecked():
                save_path = self.save_path_edit.text()
                if not save_path:
                    self.shortcuts_status.append("Error: Please specify a save location.")
                    return
            
            # Download the file
            filepath = self.download_from_github(url, save_path)
            
            if not filepath:
                self.shortcuts_status.append("✗ Failed to download shortcuts file.")
                return
        
        # Install the shortcuts
        try:
            # Run the shortcuts file
            cmd.do(f"run {filepath}")
            self.last_installed_path = filepath  # Store for later reference
            self.shortcuts_status.append("✓ Shortcuts installed successfully!")
            self.shortcuts_status.append("You can now use the shortcuts from the Shortcuts tab.")
            # Notify the main dialog so it can refresh tabs and persist the path
            self.shortcuts_installed.emit(filepath)
        except Exception as e:
            self.shortcuts_status.append(f"✗ Error installing shortcuts: {e}")
    
    def check_psico(self):
        """Check if psico package is already installed."""
        self.psico_status.clear()
        self.psico_status.append("Checking for psico package installation...")
        
        try:
            # Try to import psico.fullinit
            import psico.fullinit
            
            self.psico_status.append("✓ Psico package is already installed!")
            self.psico_status.append("✓ psico.fullinit imported successfully")
            
            # Verify specific modules that shortcuts depend on
            try:
                import psico.biomolecule
                self.psico_status.append("✓ biomolecule.py found")
            except ImportError:
                self.psico_status.append("⚠ biomolecule.py not found (may not be needed)")
            
            try:
                import psico.supercell
                self.psico_status.append("✓ supercell.py found")
            except ImportError:
                self.psico_status.append("⚠ supercell.py not found (may not be needed)")
            
            self.psico_status.append("\nYou do not need to install psico.")
            
        except ImportError as e:
            self.psico_status.append("✗ Psico package is NOT installed.")
            self.psico_status.append(f"Import error: {e}")
            self.psico_status.append("\nClick 'Install Psico' to install it.")
    
    def install_psico(self):
        """Install psico package using conda."""
        self.psico_status.clear()
        
        # Fix permissions on macOS if requested
        if self.mac_permission_check.isVisible() and self.mac_permission_check.isChecked():
            self.psico_status.append("Fixing write permissions on macOS...")
            self.fix_mac_permissions()
        
        self.psico_status.append("Installing psico package...")
        self.psico_status.append("This may take several minutes...")
        QtWidgets.QApplication.processEvents()
        
        try:
            # Find conda executable
            conda_path = self.find_conda()
            
            if not conda_path:
                self.psico_status.append("✗ Could not find conda in PyMOL installation.")
                self.psico_status.append("Conda is required for installing psico.")
                self.psico_status.append("\nPlease ensure you have PyMOL with conda installed.")
                return
            
            self.psico_status.append(f"Using conda at: {conda_path}")
            
            # Install command - use -c for channel specification
            install_cmd = [conda_path, "install", "-c", "speleo3", "pymol-psico", "-y"]
            self.psico_status.append(f"Running: {' '.join(install_cmd)}")
            QtWidgets.QApplication.processEvents()
            
            process = subprocess.Popen(
                install_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Show progress
            for line in process.stdout:
                if line.strip():
                    self.psico_status.append(line.strip())
                    QtWidgets.QApplication.processEvents()
            
            process.wait()
            
            if process.returncode == 0:
                self.psico_status.append("\n✓ Psico package installed successfully!")
                self.psico_status.append("✓ psico.fullinit is now available")
                
                # Verify installation
                self.psico_status.append("\nVerifying installation...")
                self.check_psico()
            else:
                stderr = process.stderr.read()
                self.psico_status.append(f"\n✗ Error during installation:")
                self.psico_status.append(stderr)
        
        except Exception as e:
            self.psico_status.append(f"\n✗ Error installing psico: {e}")
    
    def fix_mac_permissions(self):
        """Fix write permissions on macOS."""
        try:
            cmd_str = ["sudo", "chmod", "a+x", "/Applications/PyMOL.app/Contents"]
            self.psico_status.append(f"Running: {' '.join(cmd_str)}")
            self.psico_status.append("You will be prompted for your password...")
            QtWidgets.QApplication.processEvents()
            
            # Create a simple shell script to prompt for password
            # This will show the password prompt in terminal
            result = subprocess.run(
                cmd_str,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                self.psico_status.append("✓ Permissions fixed successfully.")
            else:
                self.psico_status.append(f"✗ Error: {result.stderr}")
        except subprocess.TimeoutExpired:
            self.psico_status.append("✗ Operation timed out. Please run the command manually in Terminal.")
        except Exception as e:
            self.psico_status.append(f"✗ Error fixing permissions: {e}")

    def check_darktheme(self):
        """Check whether the pyqtdarktheme package is installed."""
        global QDARKTHEME_AVAILABLE
        self.darktheme_status.clear()
        self.darktheme_status.append("Checking for pyqtdarktheme package...")

        try:
            import qdarktheme as _qdt
            QDARKTHEME_AVAILABLE = True
            try:
                version = _qdt.__version__
            except AttributeError:
                version = "unknown"
            self.darktheme_status.append(
                f"✓ pyqtdarktheme {version} is installed."
            )
            themes = ", ".join(getattr(_qdt, "get_themes", lambda: ["dark", "light"])())
            self.darktheme_status.append(f"  Available themes: {themes}")
            self.darktheme_status.append(
                "\nYou can select Dark or Light in the Settings tab."
            )
            # Update the system-info row
            self.darktheme_label.setText(
                f"pyqtdarktheme {version} — installed"
            )
        except ImportError as exc:
            QDARKTHEME_AVAILABLE = False
            self.darktheme_status.append("✗ pyqtdarktheme is NOT installed.")
            self.darktheme_status.append(f"  Import error: {exc}")
            self.darktheme_status.append(
                "\nClick 'Install pyqtdarktheme' to install it."
            )
            self.darktheme_label.setText(
                "Not installed  (pip install pyqtdarktheme)"
            )

    def install_darktheme(self):
        """Install pyqtdarktheme using pip."""
        global QDARKTHEME_AVAILABLE
        self.darktheme_status.clear()
        self.darktheme_status.append("Installing pyqtdarktheme...")
        self.darktheme_status.append("This may take a moment...")
        QtWidgets.QApplication.processEvents()

        try:
            install_cmd = [
                sys.executable, "-m", "pip", "install",
                "pyqtdarktheme", "--quiet",
            ]
            self.darktheme_status.append(f"Running: {' '.join(install_cmd)}")
            QtWidgets.QApplication.processEvents()

            process = subprocess.Popen(
                install_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            for line in process.stdout:
                if line.strip():
                    self.darktheme_status.append(line.strip())
                    QtWidgets.QApplication.processEvents()

            process.wait()

            if process.returncode == 0:
                self.darktheme_status.append(
                    "\n✓ pyqtdarktheme installed successfully!"
                )
                # Re-check so the flag and UI update
                self.check_darktheme()
            else:
                stderr = process.stderr.read()
                self.darktheme_status.append("\n✗ Error during installation:")
                self.darktheme_status.append(stderr)
        except Exception as exc:
            self.darktheme_status.append(
                f"\n✗ Error installing pyqtdarktheme: {exc}"
            )

    def find_conda(self):
        """Locate conda executable within PyMOL installation."""
        possible_paths = []
        
        if platform.system() == "Darwin":  # macOS
            possible_paths = [
                "/Applications/PyMOL.app/Contents/bin/conda",
                "/Applications/PyMOL.app/Contents/conda/bin/conda",
                "/Applications/PyMOL.app/Contents/libexec/conda",
                os.path.join(os.path.dirname(sys.executable), "conda"),
                os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "bin", "conda")
            ]
        elif platform.system() == "Linux":
            possible_paths = [
                os.path.join(os.path.dirname(sys.executable), "conda"),
                os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "bin", "conda"),
                "/usr/local/bin/conda",
                "/opt/pymol/bin/conda"
            ]
        elif platform.system() == "Windows":
            possible_paths = [
                os.path.join(os.path.dirname(sys.executable), "conda.exe"),
                os.path.join(os.path.dirname(sys.executable), "Library", "bin", "conda.exe"),
                os.path.join(os.path.dirname(sys.executable), "Scripts", "conda.exe")
            ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # Try to find it in PATH
        try:
            if platform.system() == "Windows":
                result = subprocess.run(["where", "conda"], 
                                       capture_output=True, text=True)
            else:
                result = subprocess.run(["which", "conda"], 
                                       capture_output=True, text=True)
            
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except:
            pass
        
        return None


class AddShortcutTab(QtWidgets.QWidget):
    """Tab for creating and submitting new shortcuts."""
    
    def __init__(self, parent=None):
        super(AddShortcutTab, self).__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()
        
        # Scroll area for the form
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QVBoxLayout()
        
        # Instructions
        instructions = QtWidgets.QLabel(
            "<h3>Create a New Shortcut</h3>"
            "<p>Fill in the form below to create a new PyMOL shortcut. "
            "When complete, you can preview the code and submit it as a "
            "pull request to the pymolshortcuts repository.</p>"
        )
        instructions.setWordWrap(True)
        form_layout.addWidget(instructions)
        
        # Function name
        name_group = QtWidgets.QGroupBox("Function Name *")
        name_layout = QtWidgets.QVBoxLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("e.g., myShortcut (letters and numbers only, must start with letter)")
        name_help = QtWidgets.QLabel(
            "<i>The function name will also be the command you type in PyMOL. "
            "Use camelCase or under_scores. Must start with a letter.</i>"
        )
        name_help.setWordWrap(True)
        name_layout.addWidget(self.name_edit)
        name_layout.addWidget(name_help)
        name_group.setLayout(name_layout)
        form_layout.addWidget(name_group)
        
        # Description
        desc_group = QtWidgets.QGroupBox("Description *")
        desc_layout = QtWidgets.QVBoxLayout()
        self.desc_edit = QtWidgets.QTextEdit()
        self.desc_edit.setPlaceholderText("Brief description of what this shortcut does...")
        self.desc_edit.setMaximumHeight(80)
        desc_layout.addWidget(self.desc_edit)
        desc_group.setLayout(desc_layout)
        form_layout.addWidget(desc_group)
        
        # Usage
        usage_group = QtWidgets.QGroupBox("Usage *")
        usage_layout = QtWidgets.QVBoxLayout()
        self.usage_edit = QtWidgets.QTextEdit()
        self.usage_edit.setPlaceholderText("How to use: functionName [arguments]")
        self.usage_edit.setMaximumHeight(60)
        usage_help = QtWidgets.QLabel("<i>Example: myShortcut or myShortcut selection, color</i>")
        usage_layout.addWidget(self.usage_edit)
        usage_layout.addWidget(usage_help)
        usage_group.setLayout(usage_layout)
        form_layout.addWidget(usage_group)
        
        # Arguments
        args_group = QtWidgets.QGroupBox("Arguments")
        args_layout = QtWidgets.QVBoxLayout()
        self.args_edit = QtWidgets.QTextEdit()
        self.args_edit.setPlaceholderText("Describe each argument, one per line...")
        self.args_edit.setMaximumHeight(100)
        args_help = QtWidgets.QLabel("<i>Leave blank if no arguments. Example:\nselection: PyMOL selection (default: all)\ncolor: Color name (default: red)</i>")
        args_layout.addWidget(self.args_edit)
        args_layout.addWidget(args_help)
        args_group.setLayout(args_layout)
        form_layout.addWidget(args_group)
        
        # Example
        example_group = QtWidgets.QGroupBox("Example *")
        example_layout = QtWidgets.QVBoxLayout()
        self.example_edit = QtWidgets.QTextEdit()
        self.example_edit.setPlaceholderText("Example usage of the shortcut...")
        self.example_edit.setMaximumHeight(100)
        example_help = QtWidgets.QLabel("<i>Show how to use the shortcut with actual examples</i>")
        example_layout.addWidget(self.example_edit)
        example_layout.addWidget(example_help)
        example_group.setLayout(example_layout)
        form_layout.addWidget(example_group)
        
        # More Details
        details_group = QtWidgets.QGroupBox("More Details")
        details_layout = QtWidgets.QVBoxLayout()
        self.details_edit = QtWidgets.QTextEdit()
        self.details_edit.setPlaceholderText("Additional information, tips, or notes...")
        self.details_edit.setMaximumHeight(100)
        details_layout.addWidget(self.details_edit)
        details_group.setLayout(details_layout)
        form_layout.addWidget(details_group)
        
        # PML Code (Vertical)
        pml_v_group = QtWidgets.QGroupBox("PML Code (Vertical - multi-line)")
        pml_v_layout = QtWidgets.QVBoxLayout()
        self.pml_v_edit = QtWidgets.QTextEdit()
        self.pml_v_edit.setPlaceholderText("PyMOL commands, one per line...")
        self.pml_v_edit.setMaximumHeight(120)
        self.pml_v_edit.setStyleSheet("font-family: monospace;")
        pml_v_layout.addWidget(self.pml_v_edit)
        pml_v_group.setLayout(pml_v_layout)
        form_layout.addWidget(pml_v_group)
        
        # PML Code (Horizontal)
        pml_h_group = QtWidgets.QGroupBox("PML Code (Horizontal - single line)")
        pml_h_layout = QtWidgets.QVBoxLayout()
        self.pml_h_edit = QtWidgets.QTextEdit()
        self.pml_h_edit.setPlaceholderText("Same commands separated by semicolons...")
        self.pml_h_edit.setMaximumHeight(80)
        self.pml_h_edit.setStyleSheet("font-family: monospace;")
        pml_h_help = QtWidgets.QLabel("<i>Usually the same as vertical but with semicolons instead of newlines</i>")
        pml_h_layout.addWidget(self.pml_h_edit)
        pml_h_layout.addWidget(pml_h_help)
        pml_h_group.setLayout(pml_h_layout)
        form_layout.addWidget(pml_h_group)
        
        # Python Code
        python_group = QtWidgets.QGroupBox("Python Code *")
        python_layout = QtWidgets.QVBoxLayout()
        self.python_edit = QtWidgets.QTextEdit()
        self.python_edit.setPlaceholderText("def functionName(args):\n    # Your Python code here\n    pass\n\ncmd.extend('functionName', functionName)")
        self.python_edit.setMinimumHeight(200)
        self.python_edit.setStyleSheet("font-family: monospace;")
        python_help = QtWidgets.QLabel(
            "<i>Complete Python function implementation. Include the cmd.extend() call.</i>"
        )
        python_layout.addWidget(self.python_edit)
        python_layout.addWidget(python_help)
        python_group.setLayout(python_layout)
        form_layout.addWidget(python_group)
        
        scroll_widget.setLayout(form_layout)
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.preview_btn = QtWidgets.QPushButton("Preview Code")
        self.preview_btn.clicked.connect(self.preview_code)
        button_layout.addWidget(self.preview_btn)
        
        self.clear_btn = QtWidgets.QPushButton("Clear Form")
        self.clear_btn.clicked.connect(self.clear_form)
        button_layout.addWidget(self.clear_btn)
        
        self.submit_btn = QtWidgets.QPushButton("Submit Pull Request")
        self.submit_btn.clicked.connect(self.submit_pull_request)
        button_layout.addWidget(self.submit_btn)
        
        layout.addLayout(button_layout)
        
        # Status
        self.status_text = QtWidgets.QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        layout.addWidget(self.status_text)
        
        self.setLayout(layout)
    
    def generate_shortcut_code(self):
        """Generate the complete shortcut code from form inputs."""
        name = self.name_edit.text().strip()
        description = self.desc_edit.toPlainText().strip()
        usage = self.usage_edit.toPlainText().strip()
        arguments = self.args_edit.toPlainText().strip()
        example = self.example_edit.toPlainText().strip()
        details = self.details_edit.toPlainText().strip()
        pml_vertical = self.pml_v_edit.toPlainText().strip()
        pml_horizontal = self.pml_h_edit.toPlainText().strip()
        python_code = self.python_edit.toPlainText().strip()
        
        # Build docstring
        docstring_parts = []
        
        if description:
            docstring_parts.append(f"DESCRIPTION:\n{description}\n")
        
        if usage:
            docstring_parts.append(f"USAGE:\n{usage}\n")
        
        if arguments:
            docstring_parts.append(f"ARGUMENTS:\n{arguments}\n")
        
        if example:
            docstring_parts.append(f"EXAMPLE:\n{example}\n")
        
        if details:
            docstring_parts.append(f"MORE DETAILS:\n{details}\n")
        
        if pml_vertical:
            docstring_parts.append(f"VERTICAL PML SCRIPT:\n{pml_vertical}\n")
        
        if pml_horizontal:
            docstring_parts.append(f"HORIZONTAL PML SCRIPT:\n{pml_horizontal}\n")
        
        if python_code:
            docstring_parts.append(f"PYTHON CODE:\n{python_code}\n")
        
        docstring = "\n".join(docstring_parts)
        
        # Generate complete code
        # Note: We assume the python_code includes the function definition and cmd.extend
        # We'll wrap it with the docstring
        if not python_code:
            return None
        
        # Insert docstring into the function
        lines = python_code.split('\n')
        function_start = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('def '):
                function_start = i
                break
        
        if function_start == -1:
            return None
        
        # Find the end of the function signature (might span multiple lines)
        paren_count = 0
        sig_end = function_start
        for i in range(function_start, len(lines)):
            paren_count += lines[i].count('(') - lines[i].count(')')
            if paren_count == 0 and '(' in lines[i]:
                sig_end = i
                break
        
        # Insert docstring after function signature
        result_lines = lines[:sig_end+1]
        result_lines.append("    '''")
        for line in docstring.split('\n'):
            if line:
                result_lines.append(f"    {line}")
            else:
                result_lines.append("")
        result_lines.append("    '''")
        result_lines.extend(lines[sig_end+1:])
        
        return '\n'.join(result_lines)
    
    def validate_form(self):
        """Validate required fields."""
        errors = []
        
        name = self.name_edit.text().strip()
        if not name:
            errors.append("Function name is required")
        elif not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', name):
            errors.append("Function name must start with a letter and contain only letters, numbers, and underscores")
        
        if not self.desc_edit.toPlainText().strip():
            errors.append("Description is required")
        
        if not self.usage_edit.toPlainText().strip():
            errors.append("Usage is required")
        
        if not self.example_edit.toPlainText().strip():
            errors.append("Example is required")
        
        if not self.python_edit.toPlainText().strip():
            errors.append("Python code is required")
        
        return errors
    
    def preview_code(self):
        """Preview the generated shortcut code."""
        errors = self.validate_form()
        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                "Validation Errors",
                "Please fix the following errors:\n\n" + "\n".join(f"• {e}" for e in errors)
            )
            return
        
        code = self.generate_shortcut_code()
        if not code:
            QtWidgets.QMessageBox.warning(
                self,
                "Code Generation Error",
                "Could not generate code. Make sure your Python code includes a function definition."
            )
            return
        
        # Show preview dialog
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Preview Generated Code")
        dialog.setMinimumSize(700, 500)
        
        layout = QtWidgets.QVBoxLayout()
        
        label = QtWidgets.QLabel("<h3>Generated Shortcut Code</h3>")
        layout.addWidget(label)
        
        code_display = QtWidgets.QTextEdit()
        code_display.setPlainText(code)
        code_display.setReadOnly(True)
        code_display.setStyleSheet("font-family: monospace; background-color: #f5f5f5;")
        layout.addWidget(code_display)
        
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        dialog.exec_()
    
    def clear_form(self):
        """Clear all form fields."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Clear Form",
            "Are you sure you want to clear all fields?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.name_edit.clear()
            self.desc_edit.clear()
            self.usage_edit.clear()
            self.args_edit.clear()
            self.example_edit.clear()
            self.details_edit.clear()
            self.pml_v_edit.clear()
            self.pml_h_edit.clear()
            self.python_edit.clear()
            self.status_text.clear()
    
    def submit_pull_request(self):
        """Submit the new shortcut as a pull request to GitHub."""
        errors = self.validate_form()
        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                "Validation Errors",
                "Please fix the following errors:\n\n" + "\n".join(f"• {e}" for e in errors)
            )
            return
        
        code = self.generate_shortcut_code()
        if not code:
            QtWidgets.QMessageBox.warning(
                self,
                "Code Generation Error",
                "Could not generate code. Make sure your Python code includes a function definition."
            )
            return
        
        # Get GitHub token
        token, ok = QtWidgets.QInputDialog.getText(
            self,
            "GitHub Authentication",
            "Enter your GitHub Personal Access Token:\n\n"
            "You can create one at:\n"
            "https://github.com/settings/tokens\n\n"
            "Required permissions: repo (for creating PRs)",
            QtWidgets.QLineEdit.Password
        )
        
        if not ok or not token:
            return
        
        self.status_text.clear()
        self.status_text.append("Starting pull request submission...")
        QtWidgets.QApplication.processEvents()
        
        try:
            # Create the pull request
            pr_url = self.create_github_pr(token, code)
            
            if pr_url:
                self.status_text.append(f"\n✓ Pull request created successfully!")
                self.status_text.append(f"✓ URL: {pr_url}")
                self.status_text.append("\nYour shortcut will be reviewed by the maintainers.")
                
                QtWidgets.QMessageBox.information(
                    self,
                    "Success",
                    f"Pull request created successfully!\n\n{pr_url}\n\n"
                    "Your shortcut will be reviewed by the maintainers."
                )
            else:
                self.status_text.append("\n✗ Failed to create pull request.")
        
        except Exception as e:
            self.status_text.append(f"\n✗ Error: {e}")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to create pull request:\n\n{e}"
            )
    
    def create_github_pr(self, token, code):
        """Create a GitHub pull request with the new shortcut.
        
        Args:
            token: GitHub personal access token
            code: Generated shortcut code
            
        Returns:
            URL of created pull request, or None if failed
        """
        # Repository details
        owner = "MooersLab"
        repo = "pymolshortcuts"
        base_branch = "master"
        
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
        
        function_name = self.name_edit.text().strip()
        branch_name = f"add-shortcut-{function_name}"
        
        try:
            # Step 1: Get authenticated user
            self.status_text.append("Authenticating with GitHub...")
            QtWidgets.QApplication.processEvents()
            
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers=headers
            )
            response = urllib.request.urlopen(req)
            user_data = json.loads(response.read().decode())
            username = user_data['login']
            self.status_text.append(f"✓ Authenticated as: {username}")
            QtWidgets.QApplication.processEvents()
            
            # Step 2: Fork the repository (if not already forked)
            self.status_text.append("Checking for fork...")
            QtWidgets.QApplication.processEvents()
            
            fork_url = f"https://api.github.com/repos/{owner}/{repo}/forks"
            fork_data = json.dumps({}).encode('utf-8')
            req = urllib.request.Request(
                fork_url,
                data=fork_data,
                headers=headers,
                method='POST'
            )
            
            try:
                response = urllib.request.urlopen(req)
                fork_data = json.loads(response.read().decode())
                self.status_text.append(f"✓ Fork created/verified")
            except urllib.error.HTTPError as e:
                if e.code == 422:  # Fork already exists
                    self.status_text.append(f"✓ Fork already exists")
                else:
                    raise
            
            QtWidgets.QApplication.processEvents()
            import time
            time.sleep(2)  # Wait for fork to be ready
            
            # Step 3: Get the default branch SHA
            self.status_text.append(f"Getting {base_branch} branch reference...")
            QtWidgets.QApplication.processEvents()
            
            ref_url = f"https://api.github.com/repos/{username}/{repo}/git/refs/heads/{base_branch}"
            req = urllib.request.Request(ref_url, headers=headers)
            response = urllib.request.urlopen(req)
            ref_data = json.loads(response.read().decode())
            base_sha = ref_data['object']['sha']
            self.status_text.append(f"✓ Base SHA: {base_sha[:7]}")
            QtWidgets.QApplication.processEvents()
            
            # Step 4: Create new branch
            self.status_text.append(f"Creating branch: {branch_name}...")
            QtWidgets.QApplication.processEvents()
            
            branch_url = f"https://api.github.com/repos/{username}/{repo}/git/refs"
            branch_data = json.dumps({
                "ref": f"refs/heads/{branch_name}",
                "sha": base_sha
            }).encode('utf-8')
            req = urllib.request.Request(
                branch_url,
                data=branch_data,
                headers=headers,
                method='POST'
            )
            
            try:
                response = urllib.request.urlopen(req)
                self.status_text.append(f"✓ Branch created")
            except urllib.error.HTTPError as e:
                if e.code == 422:  # Branch already exists
                    self.status_text.append(f"✓ Branch already exists, will update")
                    # Update existing branch reference
                    update_url = f"https://api.github.com/repos/{username}/{repo}/git/refs/heads/{branch_name}"
                    update_data = json.dumps({"sha": base_sha, "force": True}).encode('utf-8')
                    req = urllib.request.Request(
                        update_url,
                        data=update_data,
                        headers=headers,
                        method='PATCH'
                    )
                    urllib.request.urlopen(req)
                else:
                    raise
            
            QtWidgets.QApplication.processEvents()
            
            # Step 5: Get current file content to append to
            self.status_text.append("Getting current pymolshortcuts.py...")
            QtWidgets.QApplication.processEvents()
            
            file_url = f"https://api.github.com/repos/{username}/{repo}/contents/pymolshortcuts.py"
            req = urllib.request.Request(
                f"{file_url}?ref={branch_name}",
                headers=headers
            )
            response = urllib.request.urlopen(req)
            file_data = json.loads(response.read().decode())
            current_content = base64.b64decode(file_data['content']).decode('utf-8')
            file_sha = file_data['sha']
            self.status_text.append(f"✓ Current file retrieved")
            QtWidgets.QApplication.processEvents()
            
            # Step 6: Append new shortcut to file
            self.status_text.append("Adding new shortcut to file...")
            QtWidgets.QApplication.processEvents()
            
            new_content = current_content.rstrip() + "\n\n\n" + code + "\n"
            new_content_b64 = base64.b64encode(new_content.encode('utf-8')).decode('utf-8')
            
            commit_data = json.dumps({
                "message": f"Add new shortcut: {function_name}",
                "content": new_content_b64,
                "branch": branch_name,
                "sha": file_sha
            }).encode('utf-8')
            
            req = urllib.request.Request(
                file_url,
                data=commit_data,
                headers=headers,
                method='PUT'
            )
            response = urllib.request.urlopen(req)
            self.status_text.append(f"✓ File updated in branch")
            QtWidgets.QApplication.processEvents()
            
            # Step 7: Create pull request
            self.status_text.append("Creating pull request...")
            QtWidgets.QApplication.processEvents()
            
            pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
            pr_description = f"""## New Shortcut: {function_name}

**Description:**
{self.desc_edit.toPlainText().strip()}

**Usage:**
```
{self.usage_edit.toPlainText().strip()}
```

**Example:**
```
{self.example_edit.toPlainText().strip()}
```

---
*This pull request was created using the PyMOL Shortcuts Manager Plugin.*
"""
            
            pr_data = json.dumps({
                "title": f"Add new shortcut: {function_name}",
                "body": pr_description,
                "head": f"{username}:{branch_name}",
                "base": base_branch
            }).encode('utf-8')
            
            req = urllib.request.Request(
                pr_url,
                data=pr_data,
                headers=headers,
                method='POST'
            )
            response = urllib.request.urlopen(req)
            pr_result = json.loads(response.read().decode())
            pr_html_url = pr_result['html_url']
            
            return pr_html_url
            
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            error_data = json.loads(error_body) if error_body else {}
            error_message = error_data.get('message', str(e))
            self.status_text.append(f"✗ HTTP Error {e.code}: {error_message}")
            raise Exception(f"HTTP Error {e.code}: {error_message}")
        
        except Exception as e:
            self.status_text.append(f"✗ Error: {e}")
            raise


class AIIntegrationTab(QtWidgets.QWidget):
    """Tab for AI integration with Claude, OpenAI, and local models."""
    
    def __init__(self, parent=None):
        super(AIIntegrationTab, self).__init__(parent)
        self.shortcuts_content = ""
        self.shortcuts_chunks = []
        self.chunk_embeddings = []
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()
        
        # Instructions
        instructions = QtWidgets.QLabel(
            "<h3>AI-Powered Shortcut Assistant</h3>"
            "<p>Ask questions about PyMOL shortcuts using AI models. "
            "The assistant uses RAG (Retrieval-Augmented Generation) to provide "
            "accurate answers based on the shortcuts documentation.</p>"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Tabs for different AI providers
        self.provider_tabs = QtWidgets.QTabWidget()
        
        # Claude API tab
        self.claude_widget = self.create_claude_widget()
        self.provider_tabs.addTab(self.claude_widget, "Claude API")
        
        # OpenAI API tab
        self.openai_widget = self.create_openai_widget()
        self.provider_tabs.addTab(self.openai_widget, "OpenAI API")
        
        # Ollama (Local) tab
        self.ollama_widget = self.create_ollama_widget()
        self.provider_tabs.addTab(self.ollama_widget, "Ollama (Local)")

        # Gemini API tab
        self.gemini_widget = self.create_gemini_widget()
        self.provider_tabs.addTab(self.gemini_widget, "Gemini API")

        # Custom API tab
        self.custom_widget = self.create_custom_api_widget()
        self.provider_tabs.addTab(self.custom_widget, "Custom API")

        layout.addWidget(self.provider_tabs)
        
        # Common query interface
        query_group = QtWidgets.QGroupBox("Ask a Question")
        query_layout = QtWidgets.QVBoxLayout()
        
        self.query_edit = QtWidgets.QTextEdit()
        self.query_edit.setPlaceholderText(
            "Ask about PyMOL shortcuts...\n\n"
            "Examples:\n"
            "- How do I color by B-factor?\n"
            "- Show me shortcuts for making figures\n"
            "- What shortcuts work with selections?\n"
            "- Explain the AO shortcut"
        )
        self.query_edit.setMaximumHeight(120)
        query_layout.addWidget(self.query_edit)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.ask_button = QtWidgets.QPushButton("Ask AI")
        self.ask_button.clicked.connect(self.process_query)
        button_layout.addWidget(self.ask_button)
        
        self.clear_query_button = QtWidgets.QPushButton("Clear Query")
        self.clear_query_button.clicked.connect(lambda: self.query_edit.clear())
        button_layout.addWidget(self.clear_query_button)
        
        self.index_button = QtWidgets.QPushButton("Index Shortcuts")
        self.index_button.setToolTip("Process shortcuts file for RAG")
        self.index_button.clicked.connect(self.index_shortcuts)
        button_layout.addWidget(self.index_button)
        
        query_layout.addLayout(button_layout)
        query_group.setLayout(query_layout)
        layout.addWidget(query_group)
        
        # Response display
        response_group = QtWidgets.QGroupBox("AI Response")
        response_layout = QtWidgets.QVBoxLayout()
        
        self.response_display = QtWidgets.QTextEdit()
        self.response_display.setReadOnly(True)
        self.response_display.setMinimumHeight(250)
        response_layout.addWidget(self.response_display)
        
        # Copy response button
        copy_response_button = QtWidgets.QPushButton("Copy Response")
        copy_response_button.clicked.connect(self.copy_response)
        response_layout.addWidget(copy_response_button)
        
        response_group.setLayout(response_layout)
        layout.addWidget(response_group)
        
        self.setLayout(layout)
    
    def create_claude_widget(self):
        """Create Claude API configuration widget."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()
        
        # API Key
        self.claude_api_key = QtWidgets.QLineEdit()
        self.claude_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.claude_api_key.setPlaceholderText("sk-ant-...")
        layout.addRow("API Key:", self.claude_api_key)
        
        # Model selection
        self.claude_model = QtWidgets.QComboBox()
        self.claude_model.addItems([
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022"
        ])
        layout.addRow("Model:", self.claude_model)
        
        # Max tokens
        self.claude_max_tokens = QtWidgets.QSpinBox()
        self.claude_max_tokens.setRange(100, 8000)
        self.claude_max_tokens.setValue(2000)
        layout.addRow("Max Tokens:", self.claude_max_tokens)
        
        # Test button
        test_button = QtWidgets.QPushButton("Test Connection")
        test_button.clicked.connect(lambda: self.test_api_connection("claude"))
        layout.addRow("", test_button)
        
        # Info
        info = QtWidgets.QLabel(
            "<small><i>Get your API key at: https://console.anthropic.com/</i></small>"
        )
        info.setWordWrap(True)
        layout.addRow("", info)
        
        widget.setLayout(layout)
        return widget
    
    def create_openai_widget(self):
        """Create OpenAI API configuration widget."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()
        
        # API Key
        self.openai_api_key = QtWidgets.QLineEdit()
        self.openai_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.openai_api_key.setPlaceholderText("sk-...")
        layout.addRow("API Key:", self.openai_api_key)
        
        # Model selection
        self.openai_model = QtWidgets.QComboBox()
        self.openai_model.addItems([
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo"
        ])
        layout.addRow("Model:", self.openai_model)
        
        # Max tokens
        self.openai_max_tokens = QtWidgets.QSpinBox()
        self.openai_max_tokens.setRange(100, 8000)
        self.openai_max_tokens.setValue(2000)
        layout.addRow("Max Tokens:", self.openai_max_tokens)
        
        # Test button
        test_button = QtWidgets.QPushButton("Test Connection")
        test_button.clicked.connect(lambda: self.test_api_connection("openai"))
        layout.addRow("", test_button)
        
        # Info
        info = QtWidgets.QLabel(
            "<small><i>Get your API key at: https://platform.openai.com/api-keys</i></small>"
        )
        info.setWordWrap(True)
        layout.addRow("", info)
        
        widget.setLayout(layout)
        return widget
    
    def create_ollama_widget(self):
        """Create Ollama (local) configuration widget."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()
        
        # Endpoint
        self.ollama_endpoint = QtWidgets.QLineEdit()
        self.ollama_endpoint.setText("http://localhost:11434")
        layout.addRow("Endpoint:", self.ollama_endpoint)
        
        # Model name
        self.ollama_model = QtWidgets.QLineEdit()
        self.ollama_model.setText("qwen2.5:7b")
        self.ollama_model.setPlaceholderText("e.g., qwen2.5:7b, llama3, mistral")
        layout.addRow("Model:", self.ollama_model)
        
        # Max tokens
        self.ollama_max_tokens = QtWidgets.QSpinBox()
        self.ollama_max_tokens.setRange(100, 8000)
        self.ollama_max_tokens.setValue(2000)
        layout.addRow("Max Tokens:", self.ollama_max_tokens)
        
        # Test button
        test_button = QtWidgets.QPushButton("Test Connection")
        test_button.clicked.connect(lambda: self.test_api_connection("ollama"))
        layout.addRow("", test_button)
        
        # List models button
        list_button = QtWidgets.QPushButton("List Available Models")
        list_button.clicked.connect(self.list_ollama_models)
        layout.addRow("", list_button)
        
        # Info
        info = QtWidgets.QLabel(
            "<small><i>Install Ollama from: https://ollama.ai/<br>"
            "Run: ollama pull qwen2.5:7b</i></small>"
        )
        info.setWordWrap(True)
        layout.addRow("", info)
        
        widget.setLayout(layout)
        return widget
    
    def create_gemini_widget(self):
        """Create Google Gemini API configuration widget."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()

        # API Key
        self.gemini_api_key = QtWidgets.QLineEdit()
        self.gemini_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.gemini_api_key.setPlaceholderText("AIza...")
        layout.addRow("API Key:", self.gemini_api_key)

        # Model selection
        self.gemini_model = QtWidgets.QComboBox()
        self.gemini_model.addItems([
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ])
        layout.addRow("Model:", self.gemini_model)

        # Max tokens
        self.gemini_max_tokens = QtWidgets.QSpinBox()
        self.gemini_max_tokens.setRange(100, 8000)
        self.gemini_max_tokens.setValue(2000)
        layout.addRow("Max Tokens:", self.gemini_max_tokens)

        # Test button
        test_button = QtWidgets.QPushButton("Test Connection")
        test_button.clicked.connect(lambda: self.test_api_connection("gemini"))
        layout.addRow("", test_button)

        # Info
        info = QtWidgets.QLabel(
            "<small><i>Get your API key at: https://aistudio.google.com/apikey</i></small>"
        )
        info.setWordWrap(True)
        layout.addRow("", info)

        widget.setLayout(layout)
        return widget

    def create_custom_api_widget(self):
        """Create custom OpenAI-compatible API configuration widget."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()

        # Endpoint URL
        self.custom_endpoint = QtWidgets.QLineEdit()
        self.custom_endpoint.setPlaceholderText("https://api.example.com/v1/chat/completions")
        layout.addRow("API Endpoint:", self.custom_endpoint)

        # API Key
        self.custom_api_key = QtWidgets.QLineEdit()
        self.custom_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.custom_api_key.setPlaceholderText("Your API key (leave blank if not required)")
        layout.addRow("API Key:", self.custom_api_key)

        # Model name
        self.custom_model = QtWidgets.QLineEdit()
        self.custom_model.setPlaceholderText("e.g., deepseek-chat, mixtral-8x7b, etc.")
        layout.addRow("Model:", self.custom_model)

        # Auth header name
        self.custom_auth_header = QtWidgets.QLineEdit()
        self.custom_auth_header.setText("Authorization")
        self.custom_auth_header.setPlaceholderText("Header name for authentication")
        layout.addRow("Auth Header:", self.custom_auth_header)

        # Auth prefix
        self.custom_auth_prefix = QtWidgets.QLineEdit()
        self.custom_auth_prefix.setText("Bearer ")
        self.custom_auth_prefix.setPlaceholderText("e.g., Bearer , Token , etc.")
        layout.addRow("Auth Prefix:", self.custom_auth_prefix)

        # Max tokens
        self.custom_max_tokens = QtWidgets.QSpinBox()
        self.custom_max_tokens.setRange(100, 8000)
        self.custom_max_tokens.setValue(2000)
        layout.addRow("Max Tokens:", self.custom_max_tokens)

        # Test button
        test_button = QtWidgets.QPushButton("Test Connection")
        test_button.clicked.connect(lambda: self.test_api_connection("custom"))
        layout.addRow("", test_button)

        # Info
        info = QtWidgets.QLabel(
            "<small><i>Connect to any OpenAI-compatible API endpoint.<br>"
            "Examples: DeepSeek, Together AI, Groq, Fireworks, vLLM, etc.<br>"
            "The endpoint must accept the OpenAI chat completions format.</i></small>"
        )
        info.setWordWrap(True)
        layout.addRow("", info)

        widget.setLayout(layout)
        return widget

    def load_shortcuts_file(self, filepath):
        """Load shortcuts file for RAG."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.shortcuts_content = f.read()
            return True
        except Exception as e:
            self.response_display.append(f"Error loading shortcuts: {e}")
            return False
    
    def chunk_text(self, text, chunk_size=500, overlap=100):
        """Split text into overlapping chunks for RAG.
        
        Args:
            text: Text to chunk
            chunk_size: Target size in characters
            overlap: Overlap between chunks
        """
        chunks = []
        lines = text.split('\n')
        current_chunk = []
        current_size = 0
        
        for line in lines:
            line_size = len(line)
            
            if current_size + line_size > chunk_size and current_chunk:
                # Save current chunk
                chunks.append('\n'.join(current_chunk))
                
                # Start new chunk with overlap
                overlap_lines = []
                overlap_size = 0
                for prev_line in reversed(current_chunk):
                    if overlap_size + len(prev_line) < overlap:
                        overlap_lines.insert(0, prev_line)
                        overlap_size += len(prev_line)
                    else:
                        break
                
                current_chunk = overlap_lines
                current_size = overlap_size
            
            current_chunk.append(line)
            current_size += line_size
        
        # Add final chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        return chunks
    
    def simple_embedding(self, text):
        """Create simple embedding using word frequency.
        
        For production, would use sentence-transformers or API embeddings.
        This is a lightweight alternative for MVP.
        """
        # Normalize and tokenize
        text = text.lower()
        words = re.findall(r'\w+', text)
        
        # Count word frequencies
        word_freq = {}
        for word in words:
            if len(word) > 2:  # Skip very short words
                word_freq[word] = word_freq.get(word, 0) + 1
        
        return word_freq
    
    def cosine_similarity(self, vec1, vec2):
        """Calculate cosine similarity between two frequency vectors."""
        # Get all unique words
        all_words = set(list(vec1.keys()) + list(vec2.keys()))
        
        # Calculate dot product and magnitudes
        dot_product = 0
        mag1 = 0
        mag2 = 0
        
        for word in all_words:
            v1 = vec1.get(word, 0)
            v2 = vec2.get(word, 0)
            dot_product += v1 * v2
            mag1 += v1 * v1
            mag2 += v2 * v2
        
        if mag1 == 0 or mag2 == 0:
            return 0.0
        
        return dot_product / (mag1 ** 0.5 * mag2 ** 0.5)
    
    def search_chunks(self, query, top_k=3):
        """Search for most relevant chunks using semantic similarity.
        
        Args:
            query: Query string
            top_k: Number of top chunks to return
        """
        if not self.shortcuts_chunks:
            return []
        
        # Get query embedding
        query_embedding = self.simple_embedding(query)
        
        # Calculate similarities
        similarities = []
        for i, chunk_emb in enumerate(self.chunk_embeddings):
            sim = self.cosine_similarity(query_embedding, chunk_emb)
            similarities.append((sim, i))
        
        # Sort by similarity and get top k
        similarities.sort(reverse=True)
        top_chunks = [self.shortcuts_chunks[i] for _, i in similarities[:top_k]]
        
        return top_chunks
    
    def index_shortcuts(self):
        """Index shortcuts for RAG with timing statistics."""
        self.response_display.clear()
        self.response_display.append("Indexing shortcuts...")
        self.response_display.append("")
        QtWidgets.QApplication.processEvents()

        total_start = time.time()

        # Try to get shortcuts from parent
        try:
            parent_window = self.window()
            if hasattr(parent_window, 'install_tab'):
                filepath = parent_window.install_tab.last_installed_path
                if filepath and os.path.exists(filepath):
                    load_start = time.time()
                    if not self.load_shortcuts_file(filepath):
                        return
                    load_elapsed = time.time() - load_start
                    file_size_kb = os.path.getsize(filepath) / 1024.0
                    self.response_display.append(
                        f"  File loading:    {load_elapsed:.3f}s  ({file_size_kb:.1f} KB)"
                    )
                    QtWidgets.QApplication.processEvents()
                else:
                    self.response_display.append("No shortcuts file loaded. Please install shortcuts first.")
                    return
            else:
                self.response_display.append("Cannot access shortcuts file.")
                return
        except Exception as e:
            self.response_display.append(f"Error accessing shortcuts: {e}")
            return

        # Chunk the content
        chunk_start = time.time()
        self.response_display.append("Chunking text...")
        QtWidgets.QApplication.processEvents()
        self.shortcuts_chunks = self.chunk_text(self.shortcuts_content, chunk_size=800, overlap=150)
        chunk_elapsed = time.time() - chunk_start
        total_chars = sum(len(c) for c in self.shortcuts_chunks)
        self.response_display.append(
            f"  Chunking:        {chunk_elapsed:.3f}s  "
            f"({len(self.shortcuts_chunks)} chunks, {total_chars:,} chars total)"
        )
        QtWidgets.QApplication.processEvents()

        # Create embeddings
        embed_start = time.time()
        self.response_display.append("Creating embeddings...")
        QtWidgets.QApplication.processEvents()
        self.chunk_embeddings = []
        for chunk in self.shortcuts_chunks:
            embedding = self.simple_embedding(chunk)
            self.chunk_embeddings.append(embedding)
        embed_elapsed = time.time() - embed_start
        total_vocab = sum(len(e) for e in self.chunk_embeddings)
        self.response_display.append(
            f"  Embedding:       {embed_elapsed:.3f}s  "
            f"({total_vocab:,} unique terms across all chunks)"
        )

        total_elapsed = time.time() - total_start
        self.response_display.append("")
        self.response_display.append("=" * 50)
        self.response_display.append(f"  RAG Indexing Statistics")
        self.response_display.append("=" * 50)
        self.response_display.append(f"  Total time:      {total_elapsed:.3f}s")
        self.response_display.append(f"  Chunks created:  {len(self.shortcuts_chunks)}")
        self.response_display.append(f"  Avg chunk size:  {total_chars // max(len(self.shortcuts_chunks), 1)} chars")
        self.response_display.append(f"  Vocabulary size: {total_vocab:,} terms")
        self.response_display.append("=" * 50)
        self.response_display.append("")
        self.response_display.append("✓ Ready to answer questions!")
    
    def process_query(self):
        """Process user query with selected AI provider."""
        query = self.query_edit.toPlainText().strip()
        if not query:
            QtWidgets.QMessageBox.warning(self, "No Query", "Please enter a question.")
            return
        
        # Check if shortcuts are indexed
        if not self.shortcuts_chunks:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Index Required",
                "Shortcuts need to be indexed for RAG. Index now?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self.index_shortcuts()
                if not self.shortcuts_chunks:
                    return
            else:
                return
        
        # Get current provider
        current_tab = self.provider_tabs.currentIndex()
        
        self.response_display.clear()
        self.response_display.append(f"Query: {query}\n")
        self.response_display.append("Searching shortcuts...\n")
        QtWidgets.QApplication.processEvents()
        
        # Search for relevant chunks
        relevant_chunks = self.search_chunks(query, top_k=3)
        context = "\n\n---\n\n".join(relevant_chunks)
        
        self.response_display.append(f"Found {len(relevant_chunks)} relevant sections\n")
        self.response_display.append("Generating response...\n")
        QtWidgets.QApplication.processEvents()
        
        # Call appropriate API
        try:
            api_start = time.time()
            if current_tab == 0:  # Claude
                response = self.call_claude_api(query, context)
            elif current_tab == 1:  # OpenAI
                response = self.call_openai_api(query, context)
            elif current_tab == 2:  # Ollama
                response = self.call_ollama_api(query, context)
            elif current_tab == 3:  # Gemini
                response = self.call_gemini_api(query, context)
            elif current_tab == 4:  # Custom API
                response = self.call_custom_api(query, context)
            else:
                response = "Unknown provider"
            api_elapsed = time.time() - api_start

            self.response_display.append("=" * 60)
            self.response_display.append(response)
            self.response_display.append("")
            self.response_display.append(f"[API response time: {api_elapsed:.2f}s]")

        except Exception as e:
            self.response_display.append(f"Error: {e}")
    
    def call_claude_api(self, query, context):
        """Call Claude API with RAG context."""
        api_key = self.claude_api_key.text().strip()
        if not api_key:
            raise Exception("Please enter Claude API key")
        
        model = self.claude_model.currentText()
        max_tokens = self.claude_max_tokens.value()
        
        # Construct prompt
        system_prompt = (
            "You are a helpful assistant that answers questions about PyMOL shortcuts. "
            "Use the provided context from the pymolshortcuts.py file to answer questions accurately. "
            "If the answer is not in the context, say so. "
            "Provide code examples when relevant."
        )
        
        user_message = f"""Context from pymolshortcuts.py:

{context}

Question: {query}

Please provide a helpful answer based on the context above."""
        
        # API request
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        data = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_message}
            ]
        }
        
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        response = urllib.request.urlopen(req, timeout=60)
        result = json.loads(response.read().decode('utf-8'))
        
        return result['content'][0]['text']
    
    def call_openai_api(self, query, context):
        """Call OpenAI API with RAG context."""
        api_key = self.openai_api_key.text().strip()
        if not api_key:
            raise Exception("Please enter OpenAI API key")
        
        model = self.openai_model.currentText()
        max_tokens = self.openai_max_tokens.value()
        
        # Construct messages
        system_message = (
            "You are a helpful assistant that answers questions about PyMOL shortcuts. "
            "Use the provided context from the pymolshortcuts.py file to answer questions accurately. "
            "If the answer is not in the context, say so. "
            "Provide code examples when relevant."
        )
        
        user_message = f"""Context from pymolshortcuts.py:

{context}

Question: {query}

Please provide a helpful answer based on the context above."""
        
        # API request
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ]
        }
        
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        response = urllib.request.urlopen(req, timeout=60)
        result = json.loads(response.read().decode('utf-8'))
        
        return result['choices'][0]['message']['content']
    
    def call_ollama_api(self, query, context):
        """Call Ollama API with RAG context."""
        endpoint = self.ollama_endpoint.text().strip()
        model = self.ollama_model.text().strip()
        
        if not endpoint or not model:
            raise Exception("Please configure Ollama endpoint and model")
        
        # Construct prompt
        system_prompt = (
            "You are a helpful assistant that answers questions about PyMOL shortcuts. "
            "Use the provided context from the pymolshortcuts.py file to answer questions accurately. "
            "If the answer is not in the context, say so. "
            "Provide code examples when relevant."
        )
        
        full_prompt = f"""{system_prompt}

Context from pymolshortcuts.py:

{context}

Question: {query}

Please provide a helpful answer based on the context above."""
        
        # API request
        headers = {
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "num_predict": self.ollama_max_tokens.value()
            }
        }
        
        req = urllib.request.Request(
            f"{endpoint}/api/generate",
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        response = urllib.request.urlopen(req, timeout=120)
        result = json.loads(response.read().decode('utf-8'))
        
        return result['response']
    
    def test_api_connection(self, provider):
        """Test API connection."""
        self.response_display.clear()
        self.response_display.append(f"Testing {provider.upper()} connection...")
        QtWidgets.QApplication.processEvents()
        
        try:
            if provider == "claude":
                response = self.test_claude()
            elif provider == "openai":
                response = self.test_openai()
            elif provider == "ollama":
                response = self.test_ollama()
            elif provider == "gemini":
                response = self.test_gemini()
            elif provider == "custom":
                response = self.test_custom()
            else:
                response = "Unknown provider"
            
            self.response_display.append("✓ Connection successful!")
            self.response_display.append(f"\nResponse: {response}")
            
        except Exception as e:
            self.response_display.append(f"✗ Connection failed: {e}")
    
    def test_claude(self):
        """Test Claude API connection."""
        api_key = self.claude_api_key.text().strip()
        if not api_key:
            raise Exception("Please enter API key")
        
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        data = {
            "model": self.claude_model.currentText(),
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": "Say 'Connection successful!' if you can read this."}
            ]
        }
        
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode('utf-8'))
        return result['content'][0]['text']
    
    def test_openai(self):
        """Test OpenAI API connection."""
        api_key = self.openai_api_key.text().strip()
        if not api_key:
            raise Exception("Please enter API key")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.openai_model.currentText(),
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": "Say 'Connection successful!' if you can read this."}
            ]
        }
        
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode('utf-8'))
        return result['choices'][0]['message']['content']
    
    def test_ollama(self):
        """Test Ollama connection."""
        endpoint = self.ollama_endpoint.text().strip()
        model = self.ollama_model.text().strip()
        
        if not endpoint or not model:
            raise Exception("Please configure endpoint and model")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "prompt": "Say 'Connection successful!' if you can read this.",
            "stream": False,
            "options": {
                "num_predict": 50
            }
        }
        
        req = urllib.request.Request(
            f"{endpoint}/api/generate",
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode('utf-8'))
        return result['response']
    
    def list_ollama_models(self):
        """List available Ollama models."""
        endpoint = self.ollama_endpoint.text().strip()
        if not endpoint:
            QtWidgets.QMessageBox.warning(self, "Configuration", "Please set Ollama endpoint")
            return
        
        try:
            req = urllib.request.Request(f"{endpoint}/api/tags")
            response = urllib.request.urlopen(req, timeout=10)
            result = json.loads(response.read().decode('utf-8'))
            
            models = result.get('models', [])
            if models:
                model_names = [m['name'] for m in models]
                QtWidgets.QMessageBox.information(
                    self,
                    "Available Models",
                    "Installed models:\n\n" + "\n".join(f"• {name}" for name in model_names)
                )
            else:
                QtWidgets.QMessageBox.information(
                    self,
                    "No Models",
                    "No models installed. Run:\nollama pull qwen2.5:7b"
                )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to list models:\n{e}\n\nMake sure Ollama is running."
            )
    
    def call_gemini_api(self, query, context):
        """Call Google Gemini API with RAG context."""
        api_key = self.gemini_api_key.text().strip()
        if not api_key:
            raise Exception("Please enter Gemini API key")

        model = self.gemini_model.currentText()
        max_tokens = self.gemini_max_tokens.value()

        system_instruction = (
            "You are a helpful assistant that answers questions about PyMOL shortcuts. "
            "Use the provided context from the pymolshortcuts.py file to answer questions accurately. "
            "If the answer is not in the context, say so. "
            "Provide code examples when relevant."
        )

        user_message = f"""Context from pymolshortcuts.py:

{context}

Question: {query}

Please provide a helpful answer based on the context above."""

        headers = {
            "Content-Type": "application/json"
        }

        data = {
            "contents": [
                {"role": "user", "parts": [{"text": user_message}]}
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "maxOutputTokens": max_tokens
            }
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )

        response = urllib.request.urlopen(req, timeout=60)
        result = json.loads(response.read().decode('utf-8'))

        return result['candidates'][0]['content']['parts'][0]['text']

    def call_custom_api(self, query, context):
        """Call a custom OpenAI-compatible API with RAG context."""
        endpoint = self.custom_endpoint.text().strip()
        api_key = self.custom_api_key.text().strip()
        model = self.custom_model.text().strip()
        auth_header = self.custom_auth_header.text().strip()
        auth_prefix = self.custom_auth_prefix.text()

        if not endpoint:
            raise Exception("Please enter the API endpoint URL")
        if not model:
            raise Exception("Please enter the model name")

        system_message = (
            "You are a helpful assistant that answers questions about PyMOL shortcuts. "
            "Use the provided context from the pymolshortcuts.py file to answer questions accurately. "
            "If the answer is not in the context, say so. "
            "Provide code examples when relevant."
        )

        user_message = f"""Context from pymolshortcuts.py:

{context}

Question: {query}

Please provide a helpful answer based on the context above."""

        headers = {
            "Content-Type": "application/json"
        }

        if api_key:
            headers[auth_header] = f"{auth_prefix}{api_key}"

        data = {
            "model": model,
            "max_tokens": self.custom_max_tokens.value(),
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ]
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )

        response = urllib.request.urlopen(req, timeout=120)
        result = json.loads(response.read().decode('utf-8'))

        return result['choices'][0]['message']['content']

    def test_gemini(self):
        """Test Gemini API connection."""
        api_key = self.gemini_api_key.text().strip()
        if not api_key:
            raise Exception("Please enter API key")

        model = self.gemini_model.currentText()

        headers = {"Content-Type": "application/json"}

        data = {
            "contents": [
                {"role": "user", "parts": [{"text": "Say 'Connection successful!' if you can read this."}]}
            ],
            "generationConfig": {"maxOutputTokens": 50}
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )

        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode('utf-8'))
        return result['candidates'][0]['content']['parts'][0]['text']

    def test_custom(self):
        """Test custom API connection."""
        endpoint = self.custom_endpoint.text().strip()
        api_key = self.custom_api_key.text().strip()
        model = self.custom_model.text().strip()
        auth_header = self.custom_auth_header.text().strip()
        auth_prefix = self.custom_auth_prefix.text()

        if not endpoint or not model:
            raise Exception("Please configure endpoint and model")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers[auth_header] = f"{auth_prefix}{api_key}"

        data = {
            "model": model,
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": "Say 'Connection successful!' if you can read this."}
            ]
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )

        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode('utf-8'))
        return result['choices'][0]['message']['content']

    def copy_response(self):
        """Copy response to clipboard."""
        response_text = self.response_display.toPlainText()
        # Extract just the response part (after the separator)
        if "=" * 60 in response_text:
            response_text = response_text.split("=" * 60, 1)[1].strip()
        
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(response_text)
        print("Response copied to clipboard")


class HarnessRunner(QtCore.QObject):
    """Qt wrapper that runs a HarnessProcess on a worker thread.

    Every other long operation in this plugin runs on the GUI thread and
    calls processEvents to keep the window painting.  That is adequate
    for a ten-second install and useless for an agent run that lasts
    minutes, because PyMOL would appear frozen for the whole run.  So
    this one class moves to a QThread.  All of the real work lives in
    HarnessProcess, which carries no Qt, so the logic stays testable.
    """

    line_received = QtCore.Signal(str)
    finished = QtCore.Signal(int, dict)
    failed = QtCore.Signal(str)

    def __init__(self, process, parent=None):
        super(HarnessRunner, self).__init__(parent)
        self.process = process
        self.result = None

    def run(self):
        """Slot connected to the worker thread's started signal."""
        try:
            result = self.process.run(on_line=self._emit_line)
        except Exception as exc:                     # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.result = result
        if result.error:
            self.failed.emit(result.error)
        elif result.timed_out:
            self.failed.emit(
                f"The harness was stopped after {self.process.timeout} seconds."
            )
        else:
            code = result.exit_code if result.exit_code is not None else -1
            self.finished.emit(int(code), result.to_dict())

    def _emit_line(self, text):
        self.line_received.emit(text)

    def stop(self):
        return self.process.stop()


class AgenticAITab(QtWidgets.QWidget):
    """Drive a coding harness to generate, test, and document shortcuts.

    The AI Assistant tab answers questions about shortcuts that already
    exist.  This tab builds shortcuts that do not exist yet.  Think of
    the pair as a reference librarian beside a machine shop.
    """

    def __init__(self, ai_tab=None, add_shortcut_tab=None, shortcuts_tab=None,
                 parent=None):
        super(AgenticAITab, self).__init__(parent)
        self.ai_tab = ai_tab
        self.add_shortcut_tab = add_shortcut_tab
        self.shortcuts_tab = shortcuts_tab
        self.settings = QtCore.QSettings("MooersLab", "PyMOLShortcutsPlugin")
        self.config = HarnessConfig()
        self.run_store = AgentRunStore()
        self.registry = SkillRegistry()
        self.shortcuts_file = ""
        self.current_run_dir = ""
        self.current_stage = ""
        self.candidate_path = ""
        self.candidate_source = ""
        self.repair_attempts = 0
        self.skill_rows = []
        self._thread = None
        self._runner = None
        self.init_ui()
        self.load_config()
        self.refresh_skills()
        self.refresh_runs()

    # ---------------------------------------------------------------
    # User interface
    # ---------------------------------------------------------------
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()

        instructions = QtWidgets.QLabel(
            "<h3>Agentic AI</h3>"
            "<p>Wire a coding harness such as Claude Code or Pi to this "
            "plugin, then generate, test, and document a new shortcut "
            "without leaving PyMOL. Generated code is written to a scratch "
            "directory and never touches your shortcuts file until you "
            "click one of the integration buttons.</p>"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.panes = QtWidgets.QTabWidget()
        self.panes.addTab(self.create_harness_pane(), "Harness")
        self.panes.addTab(self.create_workbench_pane(), "Workbench")
        self.panes.addTab(self.create_skills_pane(), "Skills")
        self.panes.addTab(self.create_runs_pane(), "Runs")
        layout.addWidget(self.panes)

        transcript_group = QtWidgets.QGroupBox("Transcript")
        transcript_layout = QtWidgets.QVBoxLayout()
        self.transcript = QtWidgets.QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMinimumHeight(160)
        self.transcript.setStyleSheet("font-family: monospace;")
        transcript_layout.addWidget(self.transcript)

        transcript_buttons = QtWidgets.QHBoxLayout()
        self.stop_button = QtWidgets.QPushButton("Stop Run")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_run)
        transcript_buttons.addWidget(self.stop_button)

        self.clear_transcript_button = QtWidgets.QPushButton("Clear Transcript")
        self.clear_transcript_button.clicked.connect(self.transcript.clear)
        transcript_buttons.addWidget(self.clear_transcript_button)

        self.copy_transcript_button = QtWidgets.QPushButton("Copy Transcript")
        self.copy_transcript_button.clicked.connect(self.copy_transcript)
        transcript_buttons.addWidget(self.copy_transcript_button)
        transcript_buttons.addStretch()

        transcript_layout.addLayout(transcript_buttons)
        transcript_group.setLayout(transcript_layout)
        layout.addWidget(transcript_group)

        self.setLayout(layout)

    def create_harness_pane(self):
        """Pane 1: choose the coding agent and prove that it runs."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()

        self.harness_combo = QtWidgets.QComboBox()
        for key, adapter in HARNESS_ADAPTERS.items():
            self.harness_combo.addItem(adapter.display_name, key)
        self.harness_combo.currentIndexChanged.connect(self.on_harness_changed)
        layout.addRow("Harness:", self.harness_combo)

        exe_row = QtWidgets.QHBoxLayout()
        self.executable_edit = QtWidgets.QLineEdit()
        self.executable_edit.setPlaceholderText(
            "Leave blank to search PATH for the harness"
        )
        exe_row.addWidget(self.executable_edit)
        detect_button = QtWidgets.QPushButton("Auto-detect")
        detect_button.clicked.connect(self.detect_executable)
        exe_row.addWidget(detect_button)
        browse_exe = QtWidgets.QPushButton("Browse...")
        browse_exe.clicked.connect(self.browse_executable)
        exe_row.addWidget(browse_exe)
        layout.addRow("Executable:", exe_row)

        cwd_row = QtWidgets.QHBoxLayout()
        self.working_dir_edit = QtWidgets.QLineEdit()
        self.working_dir_edit.setPlaceholderText(
            "The pymolshortcuts checkout, or any directory the agent may read"
        )
        cwd_row.addWidget(self.working_dir_edit)
        browse_cwd = QtWidgets.QPushButton("Browse...")
        browse_cwd.clicked.connect(self.browse_working_dir)
        cwd_row.addWidget(browse_cwd)
        layout.addRow("Working directory:", cwd_row)

        self.model_edit = QtWidgets.QLineEdit()
        self.model_edit.setPlaceholderText(
            "Optional. For Pi use provider/model:variant"
        )
        layout.addRow("Model:", self.model_edit)

        self.provider_edit = QtWidgets.QLineEdit()
        self.provider_edit.setPlaceholderText(
            "Pi only: anthropic, openai, google, and so on"
        )
        layout.addRow("Provider:", self.provider_edit)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(list(PIAdapter.modes))
        self.mode_combo.setToolTip(
            "Pi only. Print mode runs one prompt and exits. JSON mode streams "
            "events as JSON lines. RPC mode speaks JSON-RPC over stdin."
        )
        layout.addRow("Pi mode:", self.mode_combo)

        self.thinking_combo = QtWidgets.QComboBox()
        self.thinking_combo.addItems(list(PIAdapter.thinking_levels))
        layout.addRow("Pi thinking level:", self.thinking_combo)

        self.permission_combo = QtWidgets.QComboBox()
        self.permission_combo.addItems(list(ClaudeCodeAdapter.permission_modes))
        layout.addRow("Permission mode:", self.permission_combo)

        self.output_format_combo = QtWidgets.QComboBox()
        self.output_format_combo.addItems(list(ClaudeCodeAdapter.output_formats))
        layout.addRow("Claude output format:", self.output_format_combo)

        self.argv_template_edit = QtWidgets.QLineEdit()
        self.argv_template_edit.setPlaceholderText(GenericCLIAdapter.default_template)
        self.argv_template_edit.setToolTip(
            "Generic harness only. Placeholders: %EXE% %PROMPT% %CWD% "
            "%SKILLS% %OUTDIR% %MODEL%"
        )
        layout.addRow("Generic argv template:", self.argv_template_edit)

        self.rpc_template_edit = QtWidgets.QLineEdit()
        self.rpc_template_edit.setPlaceholderText(PIAdapter.default_rpc_template)
        self.rpc_template_edit.setToolTip(
            "Pi RPC mode only. %PROMPT_JSON% is replaced by the JSON-encoded "
            "prompt string."
        )
        layout.addRow("Pi RPC request:", self.rpc_template_edit)

        self.extra_flags_edit = QtWidgets.QLineEdit()
        self.extra_flags_edit.setPlaceholderText(
            "Any additional flags, split the way a shell would split them"
        )
        layout.addRow("Extra flags:", self.extra_flags_edit)

        self.timeout_spin = QtWidgets.QSpinBox()
        self.timeout_spin.setRange(30, 7200)
        self.timeout_spin.setValue(AGENTIC_DEFAULT_TIMEOUT)
        self.timeout_spin.setSuffix(" s")
        layout.addRow("Run timeout:", self.timeout_spin)

        scratch_row = QtWidgets.QHBoxLayout()
        self.scratch_edit = QtWidgets.QLineEdit()
        self.scratch_edit.setText(AGENTIC_SCRATCH_ROOT)
        scratch_row.addWidget(self.scratch_edit)
        browse_scratch = QtWidgets.QPushButton("Browse...")
        browse_scratch.clicked.connect(self.browse_scratch_dir)
        scratch_row.addWidget(browse_scratch)
        layout.addRow("Scratch directory:", scratch_row)

        self.reference_edit = QtWidgets.QLineEdit()
        self.reference_edit.setText(AGENTIC_REFERENCE_STRUCTURE)
        self.reference_edit.setToolTip(
            "PDB identifier fetched before the live validation tier runs."
        )
        layout.addRow("Reference structure:", self.reference_edit)

        self.confirm_live_check = QtWidgets.QCheckBox(
            "Show the code and ask before executing it in PyMOL"
        )
        self.confirm_live_check.setChecked(True)
        layout.addRow("", self.confirm_live_check)

        button_row = QtWidgets.QHBoxLayout()
        test_button = QtWidgets.QPushButton("Test Harness")
        test_button.clicked.connect(self.test_harness)
        button_row.addWidget(test_button)
        save_button = QtWidgets.QPushButton("Save Harness Settings")
        save_button.clicked.connect(self.save_config)
        button_row.addWidget(save_button)
        button_row.addStretch()
        layout.addRow("", button_row)

        widget.setLayout(layout)
        return widget

    def create_workbench_pane(self):
        """Pane 2: the generate, test, and document loop."""
        widget = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout()

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()

        goal_group = QtWidgets.QGroupBox("Goal *")
        goal_layout = QtWidgets.QVBoxLayout()
        self.goal_edit = QtWidgets.QTextEdit()
        self.goal_edit.setPlaceholderText(
            "Describe the shortcut you want in plain language.\n\n"
            "Example: a shortcut that colors an RNA duplex by base pair type "
            "and orients the view down the helical axis."
        )
        self.goal_edit.setMaximumHeight(90)
        goal_layout.addWidget(self.goal_edit)
        goal_group.setLayout(goal_layout)
        layout.addWidget(goal_group)

        form_group = QtWidgets.QGroupBox("Shortcut fields")
        form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("e.g. colorBP")
        form.addRow("Name *:", self.name_edit)
        self.description_edit = QtWidgets.QLineEdit()
        form.addRow("Description:", self.description_edit)
        self.usage_edit = QtWidgets.QLineEdit()
        form.addRow("Usage:", self.usage_edit)
        self.arguments_edit = QtWidgets.QLineEdit()
        form.addRow("Arguments:", self.arguments_edit)
        self.example_edit = QtWidgets.QLineEdit()
        form.addRow("Example:", self.example_edit)
        self.details_edit = QtWidgets.QLineEdit()
        form.addRow("Details:", self.details_edit)
        self.live_arguments_edit = QtWidgets.QLineEdit()
        self.live_arguments_edit.setPlaceholderText(
            "Arguments passed during the live validation tier"
        )
        form.addRow("Live test arguments:", self.live_arguments_edit)
        form_group.setLayout(form)
        layout.addWidget(form_group)

        template_group = QtWidgets.QGroupBox("Prompt template")
        template_layout = QtWidgets.QVBoxLayout()
        template_row = QtWidgets.QHBoxLayout()
        self.template_combo = QtWidgets.QComboBox()
        self.template_combo.addItems(sorted(AGENTIC_PROMPT_TEMPLATES.keys()))
        self.template_combo.currentIndexChanged.connect(self.on_template_changed)
        template_row.addWidget(self.template_combo)
        reset_template = QtWidgets.QPushButton("Reset to Default")
        reset_template.clicked.connect(self.reset_template)
        template_row.addWidget(reset_template)
        save_template = QtWidgets.QPushButton("Save Template")
        save_template.clicked.connect(self.save_template)
        template_row.addWidget(save_template)
        template_row.addStretch()
        template_layout.addLayout(template_row)
        self.template_edit = QtWidgets.QTextEdit()
        self.template_edit.setStyleSheet("font-family: monospace;")
        self.template_edit.setMinimumHeight(140)
        template_layout.addWidget(self.template_edit)
        self.use_context_check = QtWidgets.QCheckBox(
            "Include the three most similar existing shortcuts as style examples"
        )
        self.use_context_check.setChecked(True)
        template_layout.addWidget(self.use_context_check)
        template_group.setLayout(template_layout)
        layout.addWidget(template_group)

        stage_group = QtWidgets.QGroupBox("Stages")
        stage_layout = QtWidgets.QHBoxLayout()
        self.generate_button = QtWidgets.QPushButton("1. Generate")
        self.generate_button.clicked.connect(lambda: self.start_stage("generate"))
        stage_layout.addWidget(self.generate_button)
        self.write_tests_button = QtWidgets.QPushButton("2. Write Tests")
        self.write_tests_button.clicked.connect(lambda: self.start_stage("test"))
        stage_layout.addWidget(self.write_tests_button)
        self.document_button = QtWidgets.QPushButton("3. Document")
        self.document_button.clicked.connect(lambda: self.start_stage("document"))
        stage_layout.addWidget(self.document_button)
        self.repair_button = QtWidgets.QPushButton("Fix and Retry")
        self.repair_button.clicked.connect(self.repair_candidate)
        stage_layout.addWidget(self.repair_button)
        stage_group.setLayout(stage_layout)
        layout.addWidget(stage_group)

        validate_group = QtWidgets.QGroupBox("Validation")
        validate_layout = QtWidgets.QHBoxLayout()
        self.static_button = QtWidgets.QPushButton("Static Check")
        self.static_button.clicked.connect(self.run_static_check)
        validate_layout.addWidget(self.static_button)
        self.pytest_button = QtWidgets.QPushButton("Run Generated Tests")
        self.pytest_button.clicked.connect(self.run_generated_tests)
        validate_layout.addWidget(self.pytest_button)
        self.live_button = QtWidgets.QPushButton("Run in PyMOL")
        self.live_button.setToolTip(
            "Executes model-written code in your live session. "
            "A confirmation dialog appears first."
        )
        self.live_button.clicked.connect(self.run_live_check)
        validate_layout.addWidget(self.live_button)
        validate_group.setLayout(validate_layout)
        layout.addWidget(validate_group)

        self.validation_display = QtWidgets.QTextEdit()
        self.validation_display.setReadOnly(True)
        self.validation_display.setMinimumHeight(120)
        self.validation_display.setStyleSheet("font-family: monospace;")
        layout.addWidget(self.validation_display)

        candidate_group = QtWidgets.QGroupBox("Candidate")
        candidate_layout = QtWidgets.QVBoxLayout()
        self.candidate_display = QtWidgets.QTextEdit()
        self.candidate_display.setReadOnly(True)
        self.candidate_display.setMinimumHeight(160)
        self.candidate_display.setStyleSheet("font-family: monospace;")
        candidate_layout.addWidget(self.candidate_display)
        candidate_group.setLayout(candidate_layout)
        layout.addWidget(candidate_group)

        integrate_group = QtWidgets.QGroupBox("Integrate")
        integrate_layout = QtWidgets.QHBoxLayout()
        self.to_add_button = QtWidgets.QPushButton("Send to Add Shortcut Tab")
        self.to_add_button.clicked.connect(self.send_to_add_shortcut)
        integrate_layout.addWidget(self.to_add_button)
        self.append_button = QtWidgets.QPushButton("Append to Shortcuts File")
        self.append_button.clicked.connect(self.append_to_shortcuts)
        integrate_layout.addWidget(self.append_button)
        self.open_dir_button = QtWidgets.QPushButton("Open Run Directory")
        self.open_dir_button.clicked.connect(self.open_run_directory)
        integrate_layout.addWidget(self.open_dir_button)
        integrate_group.setLayout(integrate_layout)
        layout.addWidget(integrate_group)

        inner.setLayout(layout)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        widget.setLayout(outer)
        return widget

    def create_skills_pane(self):
        """Pane 3: discover, install, and select skills."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()

        note = QtWidgets.QLabel(
            "<p>Skills found in the bundled <code>skills/</code> directory, "
            "in the working directory's <code>.claude/skills</code>, and in "
            "<code>~/.claude/skills</code>. Check the skills a run may use. "
            "A harness with no skill mechanism receives the full text of each "
            "checked skill inlined into the prompt.</p>"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.skills_table = QtWidgets.QTableWidget()
        self.skills_table.setColumnCount(4)
        self.skills_table.setHorizontalHeaderLabels(
            ["Use", "Name", "Source", "Description"]
        )
        layout.addWidget(self.skills_table)

        button_row = QtWidgets.QHBoxLayout()
        refresh_button = QtWidgets.QPushButton("Rescan")
        refresh_button.clicked.connect(self.refresh_skills)
        button_row.addWidget(refresh_button)
        install_button = QtWidgets.QPushButton("Install Selected Skill")
        install_button.clicked.connect(self.install_selected_skill)
        button_row.addWidget(install_button)
        visualization_button = QtWidgets.QPushButton("Check for pymol-visualization")
        visualization_button.clicked.connect(self.check_visualization_skill)
        button_row.addWidget(visualization_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.skills_status = QtWidgets.QLabel("")
        self.skills_status.setWordWrap(True)
        layout.addWidget(self.skills_status)

        widget.setLayout(layout)
        return widget

    def create_runs_pane(self):
        """Pane 4: the record of past runs."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()

        self.runs_table = QtWidgets.QTableWidget()
        self.runs_table.setColumnCount(6)
        self.runs_table.setHorizontalHeaderLabels(
            ["When", "Stage", "Shortcut", "Harness", "Exit", "Directory"]
        )
        layout.addWidget(self.runs_table)

        button_row = QtWidgets.QHBoxLayout()
        refresh_button = QtWidgets.QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_runs)
        button_row.addWidget(refresh_button)
        open_button = QtWidgets.QPushButton("Open Selected Directory")
        open_button.clicked.connect(self.open_selected_run)
        button_row.addWidget(open_button)
        export_button = QtWidgets.QPushButton("Export Run Log")
        export_button.clicked.connect(self.export_runs)
        button_row.addWidget(export_button)
        clear_button = QtWidgets.QPushButton("Clear Run Log")
        clear_button.clicked.connect(self.clear_runs)
        button_row.addWidget(clear_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        widget.setLayout(layout)
        return widget

    # ---------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------
    def load_config(self):
        """Read the harness configuration out of QSettings."""
        settings = self.settings
        harness = settings.value("agentic/harness", "claude-code")
        index = self.harness_combo.findData(harness)
        if index is not None and index >= 0:
            self.harness_combo.setCurrentIndex(index)
        self.executable_edit.setText(settings.value("agentic/executable", ""))
        self.working_dir_edit.setText(settings.value("agentic/working_dir", ""))
        self.model_edit.setText(settings.value("agentic/model", ""))
        self.provider_edit.setText(settings.value("agentic/provider", ""))
        self._set_combo(self.mode_combo, settings.value("agentic/mode", "print"))
        self._set_combo(self.thinking_combo, settings.value("agentic/thinking", ""))
        self._set_combo(self.permission_combo,
                        settings.value("agentic/permission_mode", ""))
        self._set_combo(self.output_format_combo,
                        settings.value("agentic/output_format", "text"))
        self.argv_template_edit.setText(settings.value("agentic/argv_template", ""))
        self.rpc_template_edit.setText(settings.value("agentic/rpc_template", ""))
        self.extra_flags_edit.setText(settings.value("agentic/extra_flags", ""))
        self.timeout_spin.setValue(
            settings.value("agentic/timeout", AGENTIC_DEFAULT_TIMEOUT, type=int)
        )
        self.scratch_edit.setText(
            settings.value("agentic/scratch_dir", AGENTIC_SCRATCH_ROOT)
        )
        self.reference_edit.setText(
            settings.value("agentic/reference_structure",
                           AGENTIC_REFERENCE_STRUCTURE)
        )
        self.confirm_live_check.setChecked(
            settings.value("agentic/confirm_live", True, type=bool)
        )
        self.on_template_changed()
        return self.current_config()

    def save_config(self):
        """Write the harness configuration back to QSettings."""
        settings = self.settings
        settings.setValue("agentic/harness", self.harness_combo.currentData())
        settings.setValue("agentic/executable", self.executable_edit.text())
        settings.setValue("agentic/working_dir", self.working_dir_edit.text())
        settings.setValue("agentic/model", self.model_edit.text())
        settings.setValue("agentic/provider", self.provider_edit.text())
        settings.setValue("agentic/mode", self.mode_combo.currentText())
        settings.setValue("agentic/thinking", self.thinking_combo.currentText())
        settings.setValue("agentic/permission_mode",
                          self.permission_combo.currentText())
        settings.setValue("agentic/output_format",
                          self.output_format_combo.currentText())
        settings.setValue("agentic/argv_template", self.argv_template_edit.text())
        settings.setValue("agentic/rpc_template", self.rpc_template_edit.text())
        settings.setValue("agentic/extra_flags", self.extra_flags_edit.text())
        settings.setValue("agentic/timeout", self.timeout_spin.value())
        settings.setValue("agentic/scratch_dir", self.scratch_edit.text())
        settings.setValue("agentic/reference_structure",
                          self.reference_edit.text())
        settings.setValue("agentic/confirm_live",
                          self.confirm_live_check.isChecked())
        settings.sync()
        self.log("Harness settings saved.")
        return self.current_config()

    @staticmethod
    def _set_combo(combo, value):
        index = combo.findText(value or "")
        if index is not None and index >= 0:
            combo.setCurrentIndex(index)

    def current_config(self):
        """Build a HarnessConfig from the widgets."""
        self.config = HarnessConfig(
            harness=self.harness_combo.currentData() or "generic",
            executable=self.executable_edit.text().strip(),
            working_dir=os.path.expanduser(
                self.working_dir_edit.text().strip()
            ),
            model=self.model_edit.text().strip(),
            provider=self.provider_edit.text().strip(),
            permission_mode=self.permission_combo.currentText().strip(),
            thinking=self.thinking_combo.currentText().strip(),
            mode=self.mode_combo.currentText().strip() or "print",
            output_format=self.output_format_combo.currentText().strip() or "text",
            extra_flags=self.extra_flags_edit.text().strip(),
            argv_template=self.argv_template_edit.text().strip(),
            rpc_template=self.rpc_template_edit.text().strip(),
            timeout=self.timeout_spin.value(),
        )
        return self.config

    def adapter(self):
        return get_harness_adapter(self.current_config())

    def scratch_root(self):
        return os.path.expanduser(
            self.scratch_edit.text().strip() or AGENTIC_SCRATCH_ROOT
        )

    def on_harness_changed(self):
        """Prefill the executable field when the harness changes."""
        self.current_config()
        if not self.executable_edit.text().strip():
            found = self.adapter().detect()
            if found:
                self.executable_edit.setText(found)

    def detect_executable(self):
        found = self.adapter().detect()
        if found:
            self.executable_edit.setText(found)
            self.log(f"Found the harness at {found}")
        else:
            self.log("The harness was not found on PATH. Enter the path by hand.")

    def browse_executable(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select the harness executable", os.path.expanduser("~")
        )
        if path:
            self.executable_edit.setText(path)

    def browse_working_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select the working directory", os.path.expanduser("~")
        )
        if path:
            self.working_dir_edit.setText(path)

    def browse_scratch_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select the scratch directory", os.path.expanduser("~")
        )
        if path:
            self.scratch_edit.setText(path)

    def test_harness(self):
        """Run the harness version command and report the result."""
        adapter = self.adapter()
        argv = adapter.version_argv()
        if not argv or not argv[0]:
            self.log("No executable is configured for this harness.")
            return False
        self.log(f"Running: {' '.join(argv)}")
        try:
            completed = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            self.log("The harness did not answer within 30 seconds.")
            return False
        except OSError as exc:
            self.log(f"The harness could not be started: {exc}")
            return False
        self.log((completed.stdout or "").strip() or "(no output)")
        ok = completed.returncode == 0
        self.log("Harness responded." if ok
                 else f"The harness exited {completed.returncode}.")
        return ok

    # ---------------------------------------------------------------
    # Prompt templates
    # ---------------------------------------------------------------
    def template_text(self, stage):
        stored = self.settings.value(f"agentic/template/{stage}", "")
        return stored or AGENTIC_PROMPT_TEMPLATES.get(stage, "")

    def on_template_changed(self):
        stage = self.template_combo.currentText()
        self.template_edit.setPlainText(self.template_text(stage))

    def save_template(self):
        stage = self.template_combo.currentText()
        self.settings.setValue(f"agentic/template/{stage}",
                               self.template_edit.toPlainText())
        self.settings.sync()
        self.log(f"Saved the {stage} template.")

    def reset_template(self):
        stage = self.template_combo.currentText()
        self.settings.setValue(f"agentic/template/{stage}", "")
        self.settings.sync()
        self.template_edit.setPlainText(AGENTIC_PROMPT_TEMPLATES.get(stage, ""))
        self.log(f"Reset the {stage} template to its default.")

    def build_context(self, goal, top_k=3):
        """Pull the most similar existing shortcuts in as style examples.

        This reuses the retrieval engine that already backs the AI
        Assistant tab, so three real shortcuts teach house style far
        better than a paragraph of instructions would.
        """
        if not self.use_context_check.isChecked():
            return "(no examples requested)"
        if self.ai_tab is None:
            return "(no examples available)"
        try:
            if not getattr(self.ai_tab, "shortcuts_chunks", None):
                path = self.shortcuts_file
                if path and os.path.isfile(path):
                    self.ai_tab.load_shortcuts_file(path)
                    self.ai_tab.index_shortcuts()
            chunks = self.ai_tab.search_chunks(goal, top_k=top_k)
        except Exception as exc:                     # noqa: BLE001
            return f"(examples unavailable: {exc})"
        if not chunks:
            return "(no examples available)"
        texts = []
        for chunk in chunks:
            texts.append(chunk[0] if isinstance(chunk, (tuple, list)) else chunk)
        return "\n\n".join(str(text) for text in texts)

    def prompt_values(self, extra=None):
        name = self.name_edit.text().strip()
        values = {
            "goal": self.goal_edit.toPlainText().strip(),
            "name": name,
            "description": self.description_edit.text().strip(),
            "usage": self.usage_edit.text().strip() or name,
            "arguments": self.arguments_edit.text().strip() or "None",
            "example": self.example_edit.text().strip() or name,
            "details": self.details_edit.text().strip(),
            "output_dir": self.current_run_dir,
            "reference_structure": self.reference_edit.text().strip()
            or AGENTIC_REFERENCE_STRUCTURE,
            "context": "",
            "failures": "",
        }
        values.update(extra or {})
        return values

    def build_prompt(self, stage, extra=None):
        template = (self.template_edit.toPlainText()
                    if self.template_combo.currentText() == stage
                    else self.template_text(stage))
        values = self.prompt_values(extra)
        if stage == "generate" and not values["context"]:
            values["context"] = self.build_context(
                values["goal"] or values["name"]
            )
        return agentic_render(template, values)

    # ---------------------------------------------------------------
    # Running a stage
    # ---------------------------------------------------------------
    def validate_inputs(self):
        errors = []
        name = self.name_edit.text().strip()
        if not name:
            errors.append("A shortcut name is required.")
        elif not re.match(r'^[A-Za-z][A-Za-z0-9_]*$', name):
            errors.append(
                "The name must start with a letter and hold only letters, "
                "digits, and underscores."
            )
        if not self.goal_edit.toPlainText().strip():
            errors.append("A goal is required.")
        return errors

    def start_stage(self, stage):
        """Build the prompt for one stage and hand it to the harness."""
        if self.is_running():
            self.log("A run is already in progress. Stop it first.")
            return False
        errors = self.validate_inputs()
        if errors:
            QtWidgets.QMessageBox.warning(
                self, "Missing Information",
                "Please fix the following:\n\n"
                + "\n".join(f"- {error}" for error in errors)
            )
            return False

        name = self.name_edit.text().strip()
        if stage == "generate" or not self.current_run_dir:
            self.current_run_dir = agentic_run_dir(name, self.scratch_root())
            self.repair_attempts = 0
        self.candidate_path = os.path.join(
            self.current_run_dir, f"candidate_{name}.py"
        )
        self.current_stage = stage
        prompt = self.build_prompt(stage)
        self.log(f"--- {stage} stage in {self.current_run_dir} ---")
        return self._launch(prompt)

    def repair_candidate(self):
        """Feed the last validation failures back to the harness."""
        if self.repair_attempts >= AGENTIC_MAX_REPAIR_ATTEMPTS:
            self.log(
                f"Stopping after {AGENTIC_MAX_REPAIR_ATTEMPTS} repair attempts. "
                "Restate the goal and generate again."
            )
            return False
        failures = self.validation_display.toPlainText().strip()
        if not failures:
            self.log("There is nothing to repair. Run a validation tier first.")
            return False
        self.repair_attempts += 1
        self.current_stage = "review"
        prompt = self.build_prompt("review", {"failures": failures})
        self.log(f"--- repair attempt {self.repair_attempts} ---")
        return self._launch(prompt)

    def _launch(self, prompt):
        adapter = self.adapter()
        if not adapter.executable():
            QtWidgets.QMessageBox.warning(
                self, "No Harness",
                "Configure the harness executable on the Harness pane first."
            )
            return False
        os.makedirs(self.current_run_dir, exist_ok=True)
        process = HarnessProcess(
            adapter, prompt,
            skills=self.selected_skills(),
            output_dir=self.current_run_dir,
            timeout=self.timeout_spin.value(),
        )
        self.log("Command: " + " ".join(process.build()[0][:4]) + " ...")
        self._runner = HarnessRunner(process)
        self._thread = QtCore.QThread()
        self._runner.moveToThread(self._thread)
        self._thread.started.connect(self._runner.run)
        self._runner.line_received.connect(self.log)
        self._runner.finished.connect(self.on_run_finished)
        self._runner.failed.connect(self.on_run_failed)
        self.stop_button.setEnabled(True)
        self.set_stage_buttons_enabled(False)
        self._thread.start()
        return True

    def is_running(self):
        return self._thread is not None

    def set_stage_buttons_enabled(self, enabled):
        for button in (self.generate_button, self.write_tests_button,
                       self.document_button, self.repair_button):
            button.setEnabled(enabled)

    def stop_run(self):
        if self._runner is not None:
            self._runner.stop()
            self.log("Stop requested.")
            return True
        return False

    def _teardown_thread(self):
        if self._thread is not None:
            try:
                self._thread.quit()
                self._thread.wait(2000)
            except Exception:                        # noqa: BLE001
                pass
        self._thread = None
        self._runner = None
        self.stop_button.setEnabled(False)
        self.set_stage_buttons_enabled(True)

    def on_run_finished(self, exit_code, summary):
        self.log(f"--- {self.current_stage} finished with exit code {exit_code} ---")
        artifacts = (summary or {}).get("artifacts", [])
        for artifact in artifacts:
            self.log(f"artifact: {artifact}")
        self.record_run(exit_code, summary)
        self._teardown_thread()
        self.load_candidate()
        if self.current_stage in ("generate", "review") and self.candidate_source:
            self.run_static_check()
        self.refresh_runs()

    def on_run_failed(self, message):
        self.log(f"--- the run failed: {message} ---")
        self.record_run(-1, {"error": message})
        self._teardown_thread()
        self.refresh_runs()

    def record_run(self, exit_code, summary):
        self.run_store.add({
            "stage": self.current_stage,
            "shortcut": self.name_edit.text().strip(),
            "harness": self.harness_combo.currentData(),
            "model": self.model_edit.text().strip(),
            "skills": [skill.name for skill in self.selected_skills()],
            "goal": self.goal_edit.toPlainText().strip(),
            "exit_code": exit_code,
            "run_dir": self.current_run_dir,
            "summary": summary or {},
        })

    # ---------------------------------------------------------------
    # Candidate handling and validation
    # ---------------------------------------------------------------
    def load_candidate(self):
        """Read the generated module off disk into the display."""
        if not self.candidate_path or not os.path.isfile(self.candidate_path):
            return ""
        try:
            with open(self.candidate_path, 'r', encoding='utf-8') as handle:
                self.candidate_source = handle.read()
        except OSError as exc:
            self.log(f"Could not read the candidate: {exc}")
            return ""
        self.candidate_display.setPlainText(self.candidate_source)
        return self.candidate_source

    def show_validation(self, result):
        lines = [f"=== {result.tier} tier ==="]
        lines.extend(str(issue) for issue in result.issues)
        if result.detail:
            lines.append("")
            lines.append(result.detail.strip())
        self.validation_display.setPlainText("\n".join(lines))
        return result

    def run_static_check(self):
        source = self.candidate_source or self.load_candidate()
        if not source:
            self.log("There is no candidate to check yet.")
            return None
        result = CandidateValidator.static_check(
            source, self.name_edit.text().strip()
        )
        self.show_validation(result)
        self.log(f"Static check: {'passed' if result.ok else 'failed'}")
        return result

    def run_generated_tests(self):
        name = self.name_edit.text().strip()
        if not self.current_run_dir:
            self.log("There is no run directory yet.")
            return None
        test_path = os.path.join(
            self.current_run_dir, f"test_candidate_{name}.py"
        )
        result = CandidateValidator.run_pytest(
            test_path, cwd=self.current_run_dir
        )
        self.show_validation(result)
        return result

    def run_live_check(self):
        """Execute the candidate in the live PyMOL session.

        This is the one action in the plugin that runs model-written code
        in the user's own session, so it is gated behind a dialog that
        shows the code.
        """
        source = self.candidate_source or self.load_candidate()
        if not source:
            self.log("There is no candidate to run yet.")
            return None
        static = CandidateValidator.static_check(
            source, self.name_edit.text().strip()
        )
        if not static.ok:
            self.show_validation(static)
            self.log("The static check must pass before the live tier runs.")
            return static
        if self.confirm_live_check.isChecked() and not self.confirm_live(source):
            self.log("The live check was cancelled.")
            return None
        snapshot = os.path.join(self.current_run_dir, "snapshot.png") \
            if self.current_run_dir else ""
        result = CandidateValidator.live_check(
            self.name_edit.text().strip(),
            source,
            reference=self.reference_edit.text().strip(),
            arguments=self.live_arguments_edit.text().strip(),
            snapshot_path=snapshot,
        )
        self.show_validation(result)
        return result

    def confirm_live(self, source):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Run generated code in PyMOL?")
        dialog.setMinimumWidth(650)
        layout = QtWidgets.QVBoxLayout()
        warning = QtWidgets.QLabel(
            "<h3>Review before running</h3>"
            "<p>The code below was written by a language model and is about "
            "to run inside your live PyMOL session. Read it, then choose.</p>"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        display = QtWidgets.QTextEdit()
        display.setPlainText(source)
        display.setReadOnly(True)
        display.setStyleSheet("font-family: monospace;")
        display.setMinimumHeight(320)
        layout.addWidget(display)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setLayout(layout)
        return bool(dialog.exec_())

    # ---------------------------------------------------------------
    # Integration
    # ---------------------------------------------------------------
    def send_to_add_shortcut(self):
        """Prefill the Add Shortcut form so the existing PR path applies."""
        source = self.candidate_source or self.load_candidate()
        if not source:
            self.log("There is no candidate to send yet.")
            return False
        if self.add_shortcut_tab is None:
            self.log("The Add Shortcut tab is not available.")
            return False
        parsed = self.parse_candidate(source)
        if parsed is None:
            self.log("The candidate docstring could not be parsed.")
            return False
        tab = self.add_shortcut_tab
        tab.name_edit.setText(parsed.name)
        tab.desc_edit.setPlainText(parsed.description)
        tab.usage_edit.setPlainText(parsed.usage)
        tab.args_edit.setPlainText(parsed.arguments)
        tab.example_edit.setPlainText(parsed.example)
        tab.details_edit.setPlainText(parsed.details)
        tab.pml_v_edit.setPlainText(parsed.pml_vertical)
        tab.pml_h_edit.setPlainText(parsed.pml_horizontal)
        tab.python_edit.setPlainText(source)
        self.log("The Add Shortcut form was filled from the candidate.")
        return True

    @staticmethod
    def parse_candidate(source):
        """Turn a candidate module into a ShortcutData object."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                docstring = ast.get_docstring(node) or ""
                return ShortcutsParser._parse_docstring(node.name, docstring)
        return None

    def append_to_shortcuts(self):
        """Append the candidate to the shortcuts file after a backup."""
        source = self.candidate_source or self.load_candidate()
        if not source:
            self.log("There is no candidate to append yet.")
            return False
        static = CandidateValidator.static_check(
            source, self.name_edit.text().strip()
        )
        if not static.ok:
            self.show_validation(static)
            QtWidgets.QMessageBox.warning(
                self, "Static Check Failed",
                "The candidate must pass the static check before it can be "
                "appended to your shortcuts file."
            )
            return False
        path = self.shortcuts_file
        if not path or not os.path.isfile(path):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select pymolshortcuts.py",
                os.path.expanduser("~"), "Python Files (*.py)"
            )
        if not path:
            return False
        reply = QtWidgets.QMessageBox.question(
            self, "Append Shortcut",
            f"Append {self.name_edit.text().strip()} to\n{path}?\n\n"
            "A timestamped backup is written first.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return False
        try:
            backup = agentic_append_to_shortcuts(path, source)
        except (IOError, OSError) as exc:
            QtWidgets.QMessageBox.critical(
                self, "Append Failed", f"Could not append the shortcut:\n\n{exc}"
            )
            return False
        self.log(f"Appended to {path}. Backup written to {backup}.")
        if self.shortcuts_tab is not None:
            try:
                self.shortcuts_tab.set_shortcuts_file(path)
            except Exception:                        # noqa: BLE001
                pass
        return True

    def open_run_directory(self):
        return self._open_directory(self.current_run_dir)

    def _open_directory(self, path):
        if not path or not os.path.isdir(path):
            self.log("There is no run directory to open.")
            return False
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", path])
            elif system == "Windows":
                os.startfile(path)               # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:                     # noqa: BLE001
            self.log(f"Could not open {path}: {exc}")
            return False
        return True

    # ---------------------------------------------------------------
    # Skills
    # ---------------------------------------------------------------
    def refresh_skills(self):
        """Rescan the skill directories and repopulate the table."""
        self.registry = SkillRegistry(
            working_dir=self.working_dir_edit.text().strip()
        )
        skills = self.registry.scan()
        self.skill_rows = []
        self.skills_table.setRowCount(len(skills))
        for row, skill in enumerate(skills):
            checkbox = QtWidgets.QTableWidgetItem()
            checkbox.setFlags(QtCore.Qt.ItemIsUserCheckable
                              | QtCore.Qt.ItemIsEnabled)
            checkbox.setCheckState(QtCore.Qt.Unchecked)
            self.skills_table.setItem(row, 0, checkbox)
            self.skills_table.setItem(
                row, 1, QtWidgets.QTableWidgetItem(skill.name))
            self.skills_table.setItem(
                row, 2, QtWidgets.QTableWidgetItem(skill.source))
            self.skills_table.setItem(
                row, 3, QtWidgets.QTableWidgetItem(skill.description))
            self.skill_rows.append(skill)
        self.skills_status.setText(
            f"Found {len(skills)} skills in: "
            + ", ".join(self.registry.search_paths())
        )
        return skills

    def selected_skills(self):
        """Return the skills whose checkbox is ticked."""
        chosen = []
        for row, skill in enumerate(self.skill_rows):
            item = self.skills_table.item(row, 0)
            try:
                if item is not None and item.checkState() == QtCore.Qt.Checked:
                    chosen.append(skill)
            except Exception:                        # noqa: BLE001
                continue
        return chosen

    def install_selected_skill(self):
        skills = self.selected_skills()
        if not skills:
            self.skills_status.setText(
                "Tick the skills you want installed, then click again."
            )
            return []
        installed = []
        for skill in skills:
            try:
                installed.append(SkillRegistry.install(skill))
            except (OSError, shutil.Error) as exc:
                self.log(f"Could not install {skill.name}: {exc}")
        if installed:
            self.log("Installed: " + ", ".join(installed))
            self.refresh_skills()
        return installed

    def check_visualization_skill(self):
        """Report whether the ChatMol pymol-visualization skill is present."""
        for candidate in ("pymol-visualization", "pymol_skill", "pymol"):
            skill = self.registry.find(candidate)
            if skill is not None:
                self.skills_status.setText(
                    f"Found {skill.name} at {skill.path}."
                )
                return skill
        self.skills_status.setText(
            "The pymol-visualization skill was not found. Install it from "
            "https://github.com/ChatMol/ChatMol/tree/main/pymol_skill into "
            "~/.claude/skills, then click Rescan."
        )
        return None

    # ---------------------------------------------------------------
    # Runs
    # ---------------------------------------------------------------
    def refresh_runs(self):
        records = self.run_store.load()
        self.runs_table.setRowCount(len(records))
        for row, record in enumerate(reversed(records)):
            values = [
                record.get("timestamp", ""),
                record.get("stage", ""),
                record.get("shortcut", ""),
                record.get("harness", ""),
                str(record.get("exit_code", "")),
                record.get("run_dir", ""),
            ]
            for column, value in enumerate(values):
                self.runs_table.setItem(
                    row, column, QtWidgets.QTableWidgetItem(value)
                )
        return records

    def open_selected_run(self):
        row = self.runs_table.currentRow()
        if row is None or row < 0:
            self.log("Select a run first.")
            return False
        item = self.runs_table.item(row, 5)
        return self._open_directory(item.text() if item else "")

    def export_runs(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export the run log",
            os.path.join(os.path.expanduser("~"), "agent_runs.json"),
            "JSON Files (*.json)"
        )
        if not path:
            return ""
        self.run_store.export(path)
        self.log(f"Exported the run log to {path}")
        return path

    def clear_runs(self):
        reply = QtWidgets.QMessageBox.question(
            self, "Clear Run Log",
            "Delete every record in the agent run log?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.run_store.clear()
            self.refresh_runs()
            return True
        return False

    # ---------------------------------------------------------------
    # Misc
    # ---------------------------------------------------------------
    def set_shortcuts_file(self, filepath):
        """Keep the tab in step with the rest of the plugin."""
        self.shortcuts_file = filepath or ""
        if self.shortcuts_file and not self.working_dir_edit.text().strip():
            self.working_dir_edit.setText(
                os.path.dirname(os.path.abspath(self.shortcuts_file))
            )
        return self.shortcuts_file

    def log(self, text):
        """Append one line to the transcript."""
        if text is None:
            return
        self.transcript.append(str(text))
        try:
            QtWidgets.QApplication.processEvents()
        except Exception:                            # noqa: BLE001
            pass

    def copy_transcript(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.transcript.toPlainText())
        self.log("The transcript was copied to the clipboard.")


class HistoryTab(QtWidgets.QWidget):
    """Tab for tracking shortcut execution history."""
    
    def __init__(self, parent=None):
        super(HistoryTab, self).__init__(parent)
        self.history_file = os.path.expanduser("~/.pymolshortcuts/history.json")
        self.history_data = []
        self.load_history()
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()
        
        # Title
        title = QtWidgets.QLabel("<h3>Shortcut Execution History</h3>")
        layout.addWidget(title)
        
        # Info
        info = QtWidgets.QLabel(
            "Track recently used shortcuts. Double-click to re-execute."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # History table
        self.history_table = QtWidgets.QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["Shortcut", "Last Used", "Times Used", "Arguments"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.history_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.history_table.doubleClicked.connect(self.re_execute_shortcut)
        
        layout.addWidget(self.history_table)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_display)
        button_layout.addWidget(refresh_btn)
        
        clear_btn = QtWidgets.QPushButton("Clear History")
        clear_btn.clicked.connect(self.clear_history)
        button_layout.addWidget(clear_btn)
        
        export_btn = QtWidgets.QPushButton("Export to CSV")
        export_btn.clicked.connect(self.export_history)
        button_layout.addWidget(export_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        self.refresh_display()
    
    def load_history(self):
        """Load history from JSON file."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    self.history_data = data.get('history', [])
        except Exception as e:
            print(f"Error loading history: {e}")
            self.history_data = []
    
    def save_history(self):
        """Save history to JSON file."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w') as f:
                json.dump({'history': self.history_data}, f, indent=2)
        except Exception as e:
            print(f"Error saving history: {e}")
    
    def add_to_history(self, shortcut_name, arguments=""):
        """Add shortcut execution to history."""
        timestamp = datetime.now().isoformat()
        
        # Check if shortcut already exists in history
        existing = None
        for item in self.history_data:
            if item['shortcut'] == shortcut_name:
                existing = item
                break
        
        if existing:
            existing['count'] += 1
            existing['last_used'] = timestamp
            existing['arguments'] = arguments
        else:
            self.history_data.append({
                'shortcut': shortcut_name,
                'last_used': timestamp,
                'count': 1,
                'arguments': arguments
            })
        
        self.save_history()
        self.refresh_display()
    
    def refresh_display(self):
        """Refresh the history table display."""
        self.history_table.setRowCount(0)
        
        # Sort by last used (most recent first)
        sorted_history = sorted(self.history_data, key=lambda x: x['last_used'], reverse=True)
        
        for item in sorted_history:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            
            # Shortcut name
            self.history_table.setItem(row, 0, QtWidgets.QTableWidgetItem(item['shortcut']))
            
            # Format timestamp
            try:
                dt = datetime.fromisoformat(item['last_used'])
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            except:
                time_str = item['last_used']
            self.history_table.setItem(row, 1, QtWidgets.QTableWidgetItem(time_str))
            
            # Count
            self.history_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(item['count'])))
            
            # Arguments
            args = item.get('arguments', '')
            self.history_table.setItem(row, 3, QtWidgets.QTableWidgetItem(args))
        
        # Resize columns
        self.history_table.resizeColumnsToContents()
    
    def re_execute_shortcut(self):
        """Re-execute the selected shortcut."""
        row = self.history_table.currentRow()
        if row < 0:
            return
        
        shortcut_name = self.history_table.item(row, 0).text()
        
        reply = QtWidgets.QMessageBox.question(
            self,
            "Re-execute Shortcut",
            f"Execute shortcut: {shortcut_name}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                # Execute the shortcut
                cmd.do(shortcut_name)
                print(f"Executed: {shortcut_name}")
                self.add_to_history(shortcut_name)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Execution Error",
                    f"Failed to execute {shortcut_name}:\n{e}"
                )
    
    def clear_history(self):
        """Clear all history."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to clear all history?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.history_data = []
            self.save_history()
            self.refresh_display()
            print("History cleared")
    
    def export_history(self):
        """Export history to CSV file."""
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export History",
            "pymol_shortcuts_history.csv",
            "CSV Files (*.csv)"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write("Shortcut,Last Used,Times Used,Arguments\n")
                    for item in self.history_data:
                        f.write(f"{item['shortcut']},{item['last_used']},{item['count']},{item.get('arguments', '')}\n")
                QtWidgets.QMessageBox.information(
                    self,
                    "Export Complete",
                    f"History exported to:\n{filename}"
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Export Error",
                    f"Failed to export history:\n{e}"
                )


class FavoritesTab(QtWidgets.QWidget):
    """Tab for managing favorite shortcuts."""
    
    favorite_changed = QtCore.Signal(str, bool)  # shortcut_name, is_favorite
    
    def __init__(self, parent=None):
        super(FavoritesTab, self).__init__(parent)
        self.favorites_file = os.path.expanduser("~/.pymolshortcuts/favorites.json")
        self.favorites_data = []
        self.load_favorites()
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()
        
        # Title
        title = QtWidgets.QLabel("<h3>Favorite Shortcuts</h3>")
        layout.addWidget(title)
        
        # Info
        info = QtWidgets.QLabel(
            "Bookmark frequently used shortcuts for quick access. "
            "Use the star button in the Shortcuts tab to add favorites."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # Category filter
        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(QtWidgets.QLabel("Category:"))
        
        self.category_filter = QtWidgets.QComboBox()
        self.category_filter.addItem("All Categories")
        self.category_filter.currentTextChanged.connect(self.refresh_display)
        filter_layout.addWidget(self.category_filter)
        filter_layout.addStretch()
        
        layout.addLayout(filter_layout)
        
        # Favorites list
        self.favorites_list = QtWidgets.QListWidget()
        self.favorites_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.favorites_list.doubleClicked.connect(self.execute_favorite)
        
        layout.addWidget(self.favorites_list)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        execute_btn = QtWidgets.QPushButton("Execute")
        execute_btn.clicked.connect(self.execute_favorite)
        button_layout.addWidget(execute_btn)
        
        remove_btn = QtWidgets.QPushButton("Remove from Favorites")
        remove_btn.clicked.connect(self.remove_favorite)
        button_layout.addWidget(remove_btn)
        
        category_btn = QtWidgets.QPushButton("Set Category")
        category_btn.clicked.connect(self.set_category)
        button_layout.addWidget(category_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        self.update_categories()
        self.refresh_display()
    
    def load_favorites(self):
        """Load favorites from JSON file."""
        try:
            os.makedirs(os.path.dirname(self.favorites_file), exist_ok=True)
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r') as f:
                    data = json.load(f)
                    self.favorites_data = data.get('favorites', [])
        except Exception as e:
            print(f"Error loading favorites: {e}")
            self.favorites_data = []
    
    def save_favorites(self):
        """Save favorites to JSON file."""
        try:
            os.makedirs(os.path.dirname(self.favorites_file), exist_ok=True)
            with open(self.favorites_file, 'w') as f:
                json.dump({'favorites': self.favorites_data}, f, indent=2)
        except Exception as e:
            print(f"Error saving favorites: {e}")
    
    def is_favorite(self, shortcut_name):
        """Check if a shortcut is in favorites."""
        return any(fav['shortcut'] == shortcut_name for fav in self.favorites_data)
    
    def add_favorite(self, shortcut_name, category="Uncategorized"):
        """Add a shortcut to favorites."""
        if not self.is_favorite(shortcut_name):
            self.favorites_data.append({
                'shortcut': shortcut_name,
                'category': category,
                'added': datetime.now().isoformat()
            })
            self.save_favorites()
            self.update_categories()
            self.refresh_display()
            self.favorite_changed.emit(shortcut_name, True)
            return True
        return False
    
    def remove_favorite(self):
        """Remove selected shortcut from favorites."""
        current_item = self.favorites_list.currentItem()
        if not current_item:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select a favorite to remove.")
            return
        
        shortcut_name = current_item.text().split(" (")[0].strip("★ ")
        
        self.favorites_data = [fav for fav in self.favorites_data if fav['shortcut'] != shortcut_name]
        self.save_favorites()
        self.update_categories()
        self.refresh_display()
        self.favorite_changed.emit(shortcut_name, False)
        print(f"Removed {shortcut_name} from favorites")
    
    def remove_favorite_by_name(self, shortcut_name):
        """Remove a shortcut from favorites by name."""
        self.favorites_data = [fav for fav in self.favorites_data if fav['shortcut'] != shortcut_name]
        self.save_favorites()
        self.update_categories()
        self.refresh_display()
        self.favorite_changed.emit(shortcut_name, False)
    
    def update_categories(self):
        """Update the category filter dropdown."""
        current_text = self.category_filter.currentText()
        self.category_filter.clear()
        self.category_filter.addItem("All Categories")
        
        categories = set(fav['category'] for fav in self.favorites_data)
        for category in sorted(categories):
            self.category_filter.addItem(category)
        
        # Restore previous selection if possible
        index = self.category_filter.findText(current_text)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
    
    def refresh_display(self):
        """Refresh the favorites list display."""
        self.favorites_list.clear()
        
        selected_category = self.category_filter.currentText()
        
        for fav in self.favorites_data:
            if selected_category == "All Categories" or fav['category'] == selected_category:
                item_text = f"★ {fav['shortcut']} ({fav['category']})"
                self.favorites_list.addItem(item_text)
    
    def execute_favorite(self):
        """Execute the selected favorite shortcut."""
        current_item = self.favorites_list.currentItem()
        if not current_item:
            return
        
        shortcut_name = current_item.text().split(" (")[0].strip("★ ")
        
        try:
            cmd.do(shortcut_name)
            print(f"Executed favorite: {shortcut_name}")
            
            # Add to history if history tab exists
            main_window = self.window()
            if hasattr(main_window, 'history_tab'):
                main_window.history_tab.add_to_history(shortcut_name)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Execution Error",
                f"Failed to execute {shortcut_name}:\n{e}"
            )
    
    def set_category(self):
        """Set category for selected favorite."""
        current_item = self.favorites_list.currentItem()
        if not current_item:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select a favorite.")
            return
        
        shortcut_name = current_item.text().split(" (")[0].strip("★ ")
        
        # Get current category
        current_category = "Uncategorized"
        for fav in self.favorites_data:
            if fav['shortcut'] == shortcut_name:
                current_category = fav['category']
                break
        
        # Ask for new category
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            "Set Category",
            f"Category for {shortcut_name}:",
            QtWidgets.QLineEdit.Normal,
            current_category
        )
        
        if ok and text:
            for fav in self.favorites_data:
                if fav['shortcut'] == shortcut_name:
                    fav['category'] = text
                    break
            
            self.save_favorites()
            self.update_categories()
            self.refresh_display()


class SettingsTab(QtWidgets.QWidget):
    """Tab for plugin settings and preferences."""
    
    def __init__(self, parent=None):
        super(SettingsTab, self).__init__(parent)
        self.settings = QtCore.QSettings("MooersLab", "PyMOLShortcutsPlugin")
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()
        
        # Title
        title = QtWidgets.QLabel("<h3>Plugin Settings</h3>")
        layout.addWidget(title)
        
        # Scroll area for settings
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_widget)
        
        # AI Integration Settings
        ai_group = QtWidgets.QGroupBox("AI Integration")
        ai_layout = QtWidgets.QFormLayout()
        
        self.remember_provider = QtWidgets.QCheckBox("Remember last used AI provider")
        self.remember_provider.setChecked(True)
        ai_layout.addRow("", self.remember_provider)
        
        self.auto_index = QtWidgets.QCheckBox("Auto-index shortcuts on plugin start")
        ai_layout.addRow("", self.auto_index)
        
        self.save_api_keys = QtWidgets.QCheckBox("Save API keys (encrypted)")
        self.save_api_keys.setToolTip("WARNING: API keys will be saved encrypted but may still pose security risk")
        ai_layout.addRow("", self.save_api_keys)
        
        ai_group.setLayout(ai_layout)
        scroll_layout.addWidget(ai_group)

        # Agentic AI Settings
        agentic_group = QtWidgets.QGroupBox("Agentic AI")
        agentic_layout = QtWidgets.QFormLayout()

        self.agentic_harness = QtWidgets.QComboBox()
        for key, adapter_cls in HARNESS_ADAPTERS.items():
            self.agentic_harness.addItem(adapter_cls.display_name, key)
        agentic_layout.addRow("Default harness:", self.agentic_harness)

        self.agentic_executable = QtWidgets.QLineEdit()
        self.agentic_executable.setPlaceholderText(
            "Leave blank to search PATH for the harness"
        )
        agentic_layout.addRow("Harness executable:", self.agentic_executable)

        self.agentic_working_dir = QtWidgets.QLineEdit()
        self.agentic_working_dir.setPlaceholderText(
            "Default: the directory holding pymolshortcuts.py"
        )
        agentic_layout.addRow("Working directory:", self.agentic_working_dir)

        self.agentic_scratch_dir = QtWidgets.QLineEdit()
        self.agentic_scratch_dir.setPlaceholderText(AGENTIC_SCRATCH_ROOT)
        agentic_layout.addRow("Scratch directory:", self.agentic_scratch_dir)

        self.agentic_reference = QtWidgets.QLineEdit()
        self.agentic_reference.setPlaceholderText(AGENTIC_REFERENCE_STRUCTURE)
        agentic_layout.addRow("Reference structure:", self.agentic_reference)

        self.agentic_timeout = QtWidgets.QSpinBox()
        self.agentic_timeout.setRange(30, 7200)
        self.agentic_timeout.setValue(AGENTIC_DEFAULT_TIMEOUT)
        self.agentic_timeout.setSuffix(" s")
        agentic_layout.addRow("Run timeout:", self.agentic_timeout)

        self.agentic_confirm_live = QtWidgets.QCheckBox(
            "Confirm before executing generated code in PyMOL"
        )
        self.agentic_confirm_live.setChecked(True)
        self.agentic_confirm_live.setToolTip(
            "Leave this on. Generated code runs in your live session."
        )
        agentic_layout.addRow("", self.agentic_confirm_live)

        self.agentic_skills_dir = QtWidgets.QLineEdit()
        self.agentic_skills_dir.setPlaceholderText(SkillRegistry.USER_DIR)
        agentic_layout.addRow("Skills directory:", self.agentic_skills_dir)

        agentic_group.setLayout(agentic_layout)
        scroll_layout.addWidget(agentic_group)

        # History Settings
        history_group = QtWidgets.QGroupBox("History")
        history_layout = QtWidgets.QFormLayout()
        
        self.enable_history = QtWidgets.QCheckBox("Track shortcut execution history")
        self.enable_history.setChecked(True)
        history_layout.addRow("", self.enable_history)
        
        self.max_history = QtWidgets.QSpinBox()
        self.max_history.setRange(10, 1000)
        self.max_history.setValue(100)
        history_layout.addRow("Max history items:", self.max_history)
        
        history_group.setLayout(history_layout)
        scroll_layout.addWidget(history_group)
        
        # Appearance Settings
        appearance_group = QtWidgets.QGroupBox("Appearance")
        appearance_layout = QtWidgets.QFormLayout()
        
        self.font_size = QtWidgets.QSpinBox()
        self.font_size.setRange(8, 24)
        self.font_size.setValue(10)
        self.font_size.setSuffix(" pt")
        appearance_layout.addRow("Font size:", self.font_size)
        
        self.theme = QtWidgets.QComboBox()
        self.theme.addItems(["System Default", "Light", "Dark"])
        appearance_layout.addRow("Theme:", self.theme)
        
        appearance_group.setLayout(appearance_layout)
        scroll_layout.addWidget(appearance_group)
        
        # Shortcuts File Settings
        file_group = QtWidgets.QGroupBox("Shortcuts File")
        file_layout = QtWidgets.QFormLayout()
        
        self.default_shortcuts_path = QtWidgets.QLineEdit()
        self.default_shortcuts_path.setPlaceholderText("Default: ~/pymolshortcuts.py")
        file_layout.addRow("Default path:", self.default_shortcuts_path)
        
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_shortcuts_path)
        file_layout.addRow("", browse_btn)
        
        self.auto_load = QtWidgets.QCheckBox("Auto-load shortcuts on PyMOL start")
        file_layout.addRow("", self.auto_load)
        
        file_group.setLayout(file_layout)
        scroll_layout.addWidget(file_group)
        
        # Updates Settings
        updates_group = QtWidgets.QGroupBox("Updates")
        updates_layout = QtWidgets.QFormLayout()
        
        self.check_updates = QtWidgets.QCheckBox("Check for plugin updates on start")
        updates_layout.addRow("", self.check_updates)
        
        updates_group.setLayout(updates_layout)
        scroll_layout.addWidget(updates_group)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        save_btn = QtWidgets.QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(save_btn)
        
        reset_btn = QtWidgets.QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_settings)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def load_settings(self):
        """Load settings from QSettings."""
        # AI Integration
        self.remember_provider.setChecked(
            self.settings.value("ai/remember_provider", True, type=bool)
        )
        self.auto_index.setChecked(
            self.settings.value("ai/auto_index", False, type=bool)
        )
        self.save_api_keys.setChecked(
            self.settings.value("ai/save_api_keys", False, type=bool)
        )
        
        # Agentic AI
        harness = self.settings.value("agentic/harness", "claude-code")
        harness_index = self.agentic_harness.findData(harness)
        if harness_index is not None and harness_index >= 0:
            self.agentic_harness.setCurrentIndex(harness_index)
        self.agentic_executable.setText(
            self.settings.value("agentic/executable", "")
        )
        self.agentic_working_dir.setText(
            self.settings.value("agentic/working_dir", "")
        )
        self.agentic_scratch_dir.setText(
            self.settings.value("agentic/scratch_dir", AGENTIC_SCRATCH_ROOT)
        )
        self.agentic_reference.setText(
            self.settings.value("agentic/reference_structure",
                                AGENTIC_REFERENCE_STRUCTURE)
        )
        self.agentic_timeout.setValue(
            self.settings.value("agentic/timeout", AGENTIC_DEFAULT_TIMEOUT,
                                type=int)
        )
        self.agentic_confirm_live.setChecked(
            self.settings.value("agentic/confirm_live", True, type=bool)
        )
        self.agentic_skills_dir.setText(
            self.settings.value("agentic/skills_dir", SkillRegistry.USER_DIR)
        )

        # History
        self.enable_history.setChecked(
            self.settings.value("history/enabled", True, type=bool)
        )
        self.max_history.setValue(
            self.settings.value("history/max_items", 100, type=int)
        )
        
        # Appearance
        self.font_size.setValue(
            self.settings.value("appearance/font_size", 10, type=int)
        )
        theme = self.settings.value("appearance/theme", "System Default")
        index = self.theme.findText(theme)
        if index >= 0:
            self.theme.setCurrentIndex(index)
        
        # Shortcuts File
        self.default_shortcuts_path.setText(
            self.settings.value("shortcuts/default_path", "")
        )
        self.auto_load.setChecked(
            self.settings.value("shortcuts/auto_load", False, type=bool)
        )
        
        # Updates
        self.check_updates.setChecked(
            self.settings.value("updates/check_on_start", False, type=bool)
        )
    
    def save_settings(self):
        """Save settings to QSettings."""
        # AI Integration
        self.settings.setValue("ai/remember_provider", self.remember_provider.isChecked())
        self.settings.setValue("ai/auto_index", self.auto_index.isChecked())
        self.settings.setValue("ai/save_api_keys", self.save_api_keys.isChecked())
        
        # Agentic AI
        self.settings.setValue("agentic/harness",
                               self.agentic_harness.currentData())
        self.settings.setValue("agentic/executable",
                               self.agentic_executable.text())
        self.settings.setValue("agentic/working_dir",
                               self.agentic_working_dir.text())
        self.settings.setValue("agentic/scratch_dir",
                               self.agentic_scratch_dir.text())
        self.settings.setValue("agentic/reference_structure",
                               self.agentic_reference.text())
        self.settings.setValue("agentic/timeout", self.agentic_timeout.value())
        self.settings.setValue("agentic/confirm_live",
                               self.agentic_confirm_live.isChecked())
        self.settings.setValue("agentic/skills_dir",
                               self.agentic_skills_dir.text())

        # History
        self.settings.setValue("history/enabled", self.enable_history.isChecked())
        self.settings.setValue("history/max_items", self.max_history.value())
        
        # Appearance
        self.settings.setValue("appearance/font_size", self.font_size.value())
        self.settings.setValue("appearance/theme", self.theme.currentText())
        
        # Shortcuts File
        self.settings.setValue("shortcuts/default_path", self.default_shortcuts_path.text())
        self.settings.setValue("shortcuts/auto_load", self.auto_load.isChecked())
        
        # Updates
        self.settings.setValue("updates/check_on_start", self.check_updates.isChecked())
        
        self.settings.sync()

        # Apply appearance changes immediately
        self.apply_appearance()

        QtWidgets.QMessageBox.information(
            self,
            "Settings Saved",
            "Settings have been saved successfully."
        )
        print("Settings saved")
    
    def reset_settings(self):
        """Reset all settings to defaults."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.settings.clear()
            self.load_settings()
            self.apply_appearance()
            QtWidgets.QMessageBox.information(
                self,
                "Settings Reset",
                "All settings have been reset to defaults."
            )
    
    def browse_shortcuts_path(self):
        """Browse for shortcuts file path."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Shortcuts File",
            os.path.expanduser("~"),
            "Python Files (*.py)"
        )
        
        if filename:
            self.default_shortcuts_path.setText(filename)
    
    def get_setting(self, key, default=None):
        """Get a setting value."""
        return self.settings.value(key, default)

    def apply_appearance(self, target=None):
        """Apply the current font-size and theme to the plugin dialog.

        When the ``pyqtdarktheme`` package (``qdarktheme``) is installed the
        Dark and Light themes are generated by ``qdarktheme.load_stylesheet``
        which produces a comprehensive, professional-quality Qt stylesheet.
        A font-size override is appended so the user's size preference is
        respected.  If the package is not installed the method falls back to
        a minimal handcrafted stylesheet.

        Parameters
        ----------
        target : QWidget or None
            The widget whose stylesheet will be set.  When called from
            ``PyMOLShortcutsPlugin.init_ui()`` the dialog passes *itself*
            so that the stylesheet is always applied to the correct
            top-level window.  On subsequent Save / Reset calls the stored
            reference (``self._appearance_target``) is used automatically.
        """
        if target is not None:
            self._appearance_target = target
        else:
            target = getattr(self, '_appearance_target', None)
        if target is None:
            target = self.window()

        font_size = self.font_size.value()
        theme_name = self.theme.currentText()

        font_override = f"* {{ font-size: {font_size}pt; }}\n"

        # -----------------------------------------------------------------
        # Primary path: use qdarktheme when available
        # -----------------------------------------------------------------
        if QDARKTHEME_AVAILABLE and theme_name in ("Dark", "Light"):
            try:
                qdt_theme = theme_name.lower()           # "dark" or "light"
                ss = qdarktheme.load_stylesheet(qdt_theme)
                ss = font_override + ss
                target.setStyleSheet(ss)
                print(
                    f"Appearance applied via qdarktheme: "
                    f"theme={theme_name}, font_size={font_size}pt"
                )
                return
            except Exception as exc:
                print(f"qdarktheme failed ({exc}); falling back to built-in stylesheet")

        # -----------------------------------------------------------------
        # Fallback: built-in stylesheets
        # -----------------------------------------------------------------
        if theme_name == "Dark":
            ss = (
                font_override
                + "QWidget { background-color: #2b2b2b; color: #e0e0e0; }\n"
                "QGroupBox { border: 1px solid #555; border-radius: 4px; "
                "margin-top: 8px; padding-top: 14px; color: #e0e0e0; }\n"
                "QGroupBox::title { subcontrol-origin: margin; left: 10px; "
                "padding: 0 4px; }\n"
                "QLineEdit, QTextEdit, QTextBrowser, QSpinBox, QComboBox "
                "{ background-color: #3c3f41; color: #e0e0e0; "
                "border: 1px solid #555; border-radius: 3px; padding: 2px; }\n"
                "QPushButton { background-color: #4a6984; color: #ffffff; "
                "border: 1px solid #3a5974; border-radius: 3px; "
                "padding: 4px 12px; }\n"
                "QPushButton:hover { background-color: #5a7994; }\n"
                "QPushButton:pressed { background-color: #3a5974; }\n"
                "QTabWidget::pane { border: 1px solid #555; }\n"
                "QTabBar::tab { background-color: #3c3f41; color: #e0e0e0; "
                "padding: 6px 14px; border: 1px solid #555; "
                "border-bottom: none; border-top-left-radius: 4px; "
                "border-top-right-radius: 4px; }\n"
                "QTabBar::tab:selected { background-color: #2b2b2b; }\n"
                "QTableView { background-color: #3c3f41; color: #e0e0e0; "
                "gridline-color: #555; }\n"
                "QHeaderView::section { background-color: #3c3f41; "
                "color: #e0e0e0; border: 1px solid #555; padding: 4px; }\n"
                "QScrollBar { background-color: #2b2b2b; }\n"
                "QScrollBar::handle { background-color: #555; "
                "border-radius: 3px; }\n"
                "QCheckBox, QRadioButton { color: #e0e0e0; }\n"
                "QLabel { color: #e0e0e0; }\n"
            )
        elif theme_name == "Light":
            ss = (
                font_override
                + "QWidget { background-color: #ffffff; color: #1e1e1e; }\n"
                "QGroupBox { border: 1px solid #c0c0c0; border-radius: 4px; "
                "margin-top: 8px; padding-top: 14px; }\n"
                "QGroupBox::title { subcontrol-origin: margin; left: 10px; "
                "padding: 0 4px; }\n"
                "QLineEdit, QTextEdit, QTextBrowser, QSpinBox, QComboBox "
                "{ background-color: #fafafa; border: 1px solid #c0c0c0; "
                "border-radius: 3px; padding: 2px; }\n"
                "QPushButton { background-color: #0078d4; color: #ffffff; "
                "border: 1px solid #006abc; border-radius: 3px; "
                "padding: 4px 12px; }\n"
                "QPushButton:hover { background-color: #1a88e0; }\n"
                "QPushButton:pressed { background-color: #006abc; }\n"
                "QTabWidget::pane { border: 1px solid #c0c0c0; }\n"
                "QTabBar::tab { background-color: #f0f0f0; padding: 6px 14px; "
                "border: 1px solid #c0c0c0; border-bottom: none; "
                "border-top-left-radius: 4px; border-top-right-radius: 4px; }\n"
                "QTabBar::tab:selected { background-color: #ffffff; }\n"
                "QTableView { background-color: #ffffff; gridline-color: #e0e0e0; }\n"
                "QHeaderView::section { background-color: #f0f0f0; "
                "border: 1px solid #c0c0c0; padding: 4px; }\n"
            )
        else:
            # "System Default" -- clear custom styling, keep only font
            ss = font_override

        target.setStyleSheet(ss)
        print(f"Appearance applied (built-in): theme={theme_name}, font_size={font_size}pt")


class TutorialTab(QtWidgets.QWidget):
    """Tab with tutorial examples demonstrating shortcut usage."""

    def __init__(self, parent=None):
        super(TutorialTab, self).__init__(parent)
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()

        # Title
        title = QtWidgets.QLabel("<h2>Shortcuts Tutorial</h2>")
        layout.addWidget(title)

        intro = QtWidgets.QLabel(
            "<p>Learn how to use PyMOL shortcuts through practical, step-by-step examples. "
            "Select a tutorial from the list below, then click <b>Run Example</b> to "
            "execute the commands in PyMOL.</p>"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Splitter for list and details
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Tutorial list
        self.tutorial_list = QtWidgets.QListWidget()
        self.tutorial_list.currentRowChanged.connect(self.show_tutorial)
        splitter.addWidget(self.tutorial_list)

        # Tutorial details
        self.tutorial_browser = QtWidgets.QTextBrowser()
        self.tutorial_browser.setOpenExternalLinks(True)
        splitter.addWidget(self.tutorial_browser)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()

        self.run_btn = QtWidgets.QPushButton("Run Example")
        self.run_btn.clicked.connect(self.run_current_example)
        button_layout.addWidget(self.run_btn)

        self.copy_btn = QtWidgets.QPushButton("Copy Commands")
        self.copy_btn.clicked.connect(self.copy_current_commands)
        button_layout.addWidget(self.copy_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Populate tutorials
        self._build_tutorials()
        self._populate_list()

    def _build_tutorials(self):
        """Build the list of tutorial examples."""
        self.tutorials = [
            {
                "title": "1. Getting Started: Fetch and Display a Protein",
                "description": (
                    "This tutorial shows how to fetch a protein structure from the PDB "
                    "and apply basic display settings using shortcuts."
                ),
                "steps": [
                    "Type <code>AO</code> in PyMOL after loading a PDB file to get a "
                    "publication-quality symmetry symmetry symmetry symmetry symmetry symmetry rendering with ambient occlusion.",
                    "Type <code>BW</code> to apply a black-and-white representation suitable for journal figures.",
                    "Type <code>CB</code> to color by B-factor using a rainbow color scheme.",
                ],
                "commands": [
                    "fetch 1lyz, async=0",
                    "AO",
                ],
            },
            {
                "title": "2. Coloring Shortcuts",
                "description": (
                    "PyMOL shortcuts offer many coloring schemes. "
                    "These examples demonstrate common coloring workflows."
                ),
                "steps": [
                    "<code>CB</code> &mdash; Color by B-factor (temperature factor) with a rainbow gradient.",
                    "<code>CR</code> &mdash; Color by chain with a rainbow palette.",
                    "<code>CSS</code> &mdash; Color by secondary structure: helices red, sheets yellow, loops green.",
                ],
                "commands": [
                    "fetch 1lyz, async=0",
                    "CB",
                ],
            },
            {
                "title": "3. Symmetry Mates and Crystal Contacts",
                "description": (
                    "Shortcuts can generate symmetry mates around a protein to visualize "
                    "crystal packing. This is helpful when analyzing crystal contacts."
                ),
                "steps": [
                    "Load a structure with <code>fetch 1lyz</code>.",
                    "Use <code>SC33</code> to generate a 3 x 3 x 3 symmetry mate expansion.",
                    "Use <code>SC222</code> for a 2 x 2 x 2 supercell.",
                ],
                "commands": [
                    "fetch 1lyz, async=0",
                    "SC33",
                ],
            },
            {
                "title": "4. Making Publication-Quality Figures",
                "description": (
                    "Several shortcuts configure PyMOL for ray-traced images suitable for publications."
                ),
                "steps": [
                    "<code>AO</code> &mdash; Ambient occlusion: a soft-shadow effect for depth perception.",
                    "<code>BW</code> &mdash; Black-and-white figure mode.",
                    "<code>PE</code> &mdash; Print-ready export settings.",
                    "After applying a shortcut, use <code>ray</code> to render the image, "
                    "then <code>png filename.png</code> to save it.",
                ],
                "commands": [
                    "fetch 1lyz, async=0",
                    "as cartoon",
                    "AO",
                    "ray 2400, 2400",
                ],
            },
            {
                "title": "5. Working with Electron Density Maps",
                "description": (
                    "Shortcuts simplify the display of electron density maps around a "
                    "molecule or selected residues."
                ),
                "steps": [
                    "Fetch a structure with maps: <code>fetch 1lyz, type=2fofc, async=0</code>.",
                    "Use shortcuts to adjust map contour levels and display radius.",
                ],
                "commands": [
                    "fetch 1lyz, async=0",
                    "fetch 1lyz, type=2fofc, async=0",
                ],
            },
            {
                "title": "6. Selections and Distances",
                "description": (
                    "Shortcuts can create selections and measure distances between atoms."
                ),
                "steps": [
                    "Select active-site residues by name or number.",
                    "Use shortcuts to compute and display hydrogen bonds or distances.",
                ],
                "commands": [
                    "fetch 1lyz, async=0",
                    "select active_site, resi 35+52",
                    "show sticks, active_site",
                ],
            },
            {
                "title": "7. Saving and Loading Sessions",
                "description": (
                    "After setting up a complex scene, save the PyMOL session so you can "
                    "return to it later."
                ),
                "steps": [
                    "Set up your desired view using any combination of shortcuts.",
                    "Save the session: <code>save mysession.pse</code>.",
                    "Reload later: <code>load mysession.pse</code>.",
                ],
                "commands": [
                    "fetch 1lyz, async=0",
                    "AO",
                ],
            },
        ]

    def _populate_list(self):
        """Fill the list widget with tutorial titles."""
        for t in self.tutorials:
            self.tutorial_list.addItem(t["title"])
        if self.tutorials:
            self.tutorial_list.setCurrentRow(0)

    def show_tutorial(self, row):
        """Display the selected tutorial."""
        if row < 0 or row >= len(self.tutorials):
            return

        t = self.tutorials[row]
        steps_html = "".join(f"<li>{s}</li>" for s in t["steps"])
        cmds_html = "<br>".join(t["commands"])

        html = f"""
        <h3>{t['title']}</h3>
        <p>{t['description']}</p>
        <h4>Steps</h4>
        <ol>{steps_html}</ol>
        <h4>Commands</h4>
        <pre style="background-color: #f0f0f0; padding: 10px; font-family: monospace;">
{cmds_html}
</pre>
        <p><i>Click <b>Run Example</b> to execute the commands above in PyMOL, or
        <b>Copy Commands</b> to paste them yourself.</i></p>
        """
        self.tutorial_browser.setHtml(html)

    def run_current_example(self):
        """Execute the commands of the currently selected tutorial."""
        row = self.tutorial_list.currentRow()
        if row < 0 or row >= len(self.tutorials):
            return

        commands = self.tutorials[row]["commands"]
        try:
            for c in commands:
                cmd.do(c)
            print(f"Tutorial executed: {self.tutorials[row]['title']}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Execution Error",
                f"Failed to run tutorial commands:\n{e}"
            )

    def copy_current_commands(self):
        """Copy current tutorial commands to clipboard."""
        row = self.tutorial_list.currentRow()
        if row < 0 or row >= len(self.tutorials):
            return

        commands = "\n".join(self.tutorials[row]["commands"])
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(commands)
        print("Tutorial commands copied to clipboard")


class CitationTab(QtWidgets.QWidget):
    """Tab with citation information for the Mooers 2020 shortcuts paper."""

    def __init__(self, parent=None):
        super(CitationTab, self).__init__(parent)
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()

        # Title
        title = QtWidgets.QLabel("<h2>Cite This Work</h2>")
        layout.addWidget(title)

        intro = QtWidgets.QLabel(
            "<p>If you use the PyMOL shortcuts in your research, please cite the "
            "following publication:</p>"
            "<p><b>Mooers, B. H. M.</b> (2020). Shortcuts for faster image creation "
            "in PyMOL. <i>Protein Science</i>, <b>29</b>(1), 268&ndash;276. "
            "DOI: <a href='https://doi.org/10.1002/pro.3781'>10.1002/pro.3781</a></p>"
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        layout.addWidget(intro)

        # BibTeX section
        bibtex_group = QtWidgets.QGroupBox("BibTeX")
        bibtex_layout = QtWidgets.QVBoxLayout()

        self.bibtex_text = QtWidgets.QTextEdit()
        self.bibtex_text.setReadOnly(True)
        self.bibtex_text.setStyleSheet("font-family: monospace; background-color: #f5f5f5;")
        self.bibtex_text.setPlainText(
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
        self.bibtex_text.setMaximumHeight(280)
        bibtex_layout.addWidget(self.bibtex_text)

        copy_bibtex_btn = QtWidgets.QPushButton("Copy BibTeX")
        copy_bibtex_btn.clicked.connect(self.copy_bibtex)
        bibtex_layout.addWidget(copy_bibtex_btn)

        bibtex_group.setLayout(bibtex_layout)
        layout.addWidget(bibtex_group)

        # EndNote section
        endnote_group = QtWidgets.QGroupBox("EndNote (.enw)")
        endnote_layout = QtWidgets.QVBoxLayout()

        self.endnote_text = QtWidgets.QTextEdit()
        self.endnote_text.setReadOnly(True)
        self.endnote_text.setStyleSheet("font-family: monospace; background-color: #f5f5f5;")
        self.endnote_text.setPlainText(
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
        self.endnote_text.setMaximumHeight(220)
        endnote_layout.addWidget(self.endnote_text)

        copy_endnote_btn = QtWidgets.QPushButton("Copy EndNote")
        copy_endnote_btn.clicked.connect(self.copy_endnote)
        endnote_layout.addWidget(copy_endnote_btn)

        endnote_group.setLayout(endnote_layout)
        layout.addWidget(endnote_group)

        # Save buttons
        save_layout = QtWidgets.QHBoxLayout()

        save_bib_btn = QtWidgets.QPushButton("Save as .bib file")
        save_bib_btn.clicked.connect(self.save_bibtex)
        save_layout.addWidget(save_bib_btn)

        save_enw_btn = QtWidgets.QPushButton("Save as .enw file")
        save_enw_btn.clicked.connect(self.save_endnote)
        save_layout.addWidget(save_enw_btn)

        save_layout.addStretch()
        layout.addLayout(save_layout)

        layout.addStretch()
        self.setLayout(layout)

    def copy_bibtex(self):
        """Copy BibTeX to clipboard."""
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.bibtex_text.toPlainText())
        print("BibTeX entry copied to clipboard")

    def copy_endnote(self):
        """Copy EndNote entry to clipboard."""
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.endnote_text.toPlainText())
        print("EndNote entry copied to clipboard")

    def save_bibtex(self):
        """Save BibTeX entry to a .bib file."""
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save BibTeX File",
            "Mooers2020ShortcutsForFasterImageCreationInPyMOL.bib",
            "BibTeX Files (*.bib);;All Files (*)"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.bibtex_text.toPlainText())
                QtWidgets.QMessageBox.information(
                    self, "Saved", f"BibTeX saved to:\n{filename}"
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Failed to save file:\n{e}"
                )

    def save_endnote(self):
        """Save EndNote entry to an .enw file."""
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save EndNote File",
            "Mooers2020ShortcutsForFasterImageCreationInPyMOL.enw",
            "EndNote Files (*.enw);;All Files (*)"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.endnote_text.toPlainText())
                QtWidgets.QMessageBox.information(
                    self, "Saved", f"EndNote file saved to:\n{filename}"
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Failed to save file:\n{e}"
                )


class LinksTab(QtWidgets.QWidget):
    """Tab with useful links and resources."""
    
    def __init__(self, parent=None):
        super(LinksTab, self).__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()
        
        # Title
        title = QtWidgets.QLabel("<h2>Resources and Links</h2>")
        layout.addWidget(title)
        
        # Introduction
        intro = QtWidgets.QLabel(
            "<p>Quick access to documentation, repositories, and community resources "
            "for PyMOL shortcuts and this plugin.</p>"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        
        # Scrollable text browser for links
        self.links_browser = QtWidgets.QTextBrowser()
        self.links_browser.setOpenExternalLinks(True)
        self.links_browser.setOpenLinks(True)
        
        # Build HTML content with compact links
        html_content = """
        <style>
            body { font-family: sans-serif; }
            h3 { color: #2c3e50; margin-top: 20px; margin-bottom: 10px; }
            ul { margin-top: 5px; margin-bottom: 15px; }
            li { margin-bottom: 5px; }
            a { color: #3498db; text-decoration: none; }
            a:hover { text-decoration: underline; }
            .description { color: #7f8c8d; font-size: 0.9em; margin-left: 20px; }
        </style>
        
        <h3>GitHub Repositories</h3>
        <ul>
            <li><a href="https://github.com/MooersLab/pymolshortcuts">PyMOL Shortcuts Repository</a>
                <div class="description">Main repository containing pymolshortcuts.py with all shortcuts</div>
            </li>
            <li><a href="https://github.com/MooersLab/pymolshortcuts-plugin">Plugin Repository</a>
                <div class="description">Source code for this PyMOL Shortcuts Manager Plugin</div>
            </li>
        </ul>
        
        <h3>Documentation</h3>
        <ul>
            <li><a href="https://pymolshortcuts-plugin.readthedocs.io">Plugin Documentation (Read the Docs)</a>
                <div class="description">Comprehensive documentation including tutorials and API reference</div>
            </li>
            <li><a href="https://pymolwiki.org">PyMOL Wiki</a>
                <div class="description">Official PyMOL documentation and command reference</div>
            </li>
        </ul>
        
        <h3>Community Resources</h3>
        <ul>
            <li><a href="https://sourceforge.net/projects/pymol/lists/pymol-users">PyMOL Mailing List</a>
                <div class="description">Active community for questions and discussions</div>
            </li>
            <li><a href="https://pymol.org">PyMOL Homepage</a>
                <div class="description">Official website with downloads and information</div>
            </li>
        </ul>
        
        <h3>API Resources (for AI Integration)</h3>
        <ul>
            <li><a href="https://console.anthropic.com">Anthropic API Console</a>
                <div class="description">Get Claude API keys and manage usage</div>
            </li>
            <li><a href="https://platform.openai.com">OpenAI API Platform</a>
                <div class="description">Get OpenAI API keys and access documentation</div>
            </li>
            <li><a href="https://ollama.ai">Ollama</a>
                <div class="description">Download and run local AI models</div>
            </li>
        </ul>
        
        <h3>About</h3>
        <ul>
            <li><strong>Author:</strong> Blaine Mooers, PhD</li>
            <li><strong>Email:</strong> <a href="mailto:blaine-mooers@ou.edu">blaine-mooers@ou.edu</a></li>
            <li><strong>Institution:</strong> University of Oklahoma Health Campus</li>
            <li><strong>Department:</strong> Biochemistry and Physiology</li>
            <li><a href="https://github.com/MooersLab">MooersLab GitHub Profile</a>
                <div class="description">Browse other projects and resources</div>
            </li>
        </ul>
        
        <hr style="margin-top: 30px; border: none; border-top: 1px solid #ecf0f1;">
        
        <p style="text-align: center; color: #95a5a6; font-size: 0.9em; margin-top: 20px;">
            <em>PyMOL Shortcuts Manager Plugin v3.0<br>
            Last updated: February 2026</em>
        </p>
        """
        
        self.links_browser.setHtml(html_content)
        layout.addWidget(self.links_browser)
        
        self.setLayout(layout)


class ShortcutsTableModel(QtCore.QAbstractTableModel):
    """Table model for displaying shortcuts."""
    
    def __init__(self, shortcuts, parent=None):
        super(ShortcutsTableModel, self).__init__(parent)
        self.shortcuts = shortcuts
        self.headers = ['Name', 'Keybinding', 'Description']
    
    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.shortcuts)
    
    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.headers)
    
    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        
        if role == QtCore.Qt.DisplayRole:
            shortcut = self.shortcuts[index.row()]
            col = index.column()
            
            if col == 0:
                return shortcut.name
            elif col == 1:
                return shortcut.keybinding
            elif col == 2:
                # Return first line of description
                desc = shortcut.description.split('\n')[0]
                return desc[:100] + '...' if len(desc) > 100 else desc
        
        return None
    
    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.headers[section]
        return None
    
    def get_shortcut(self, row):
        """Get the shortcut object at the given row."""
        if 0 <= row < len(self.shortcuts):
            return self.shortcuts[row]
        return None


class ShortcutsTab(QtWidgets.QWidget):
    """Tab for browsing and executing shortcuts."""
    
    def __init__(self, shortcuts_file=None, parent=None):
        super(ShortcutsTab, self).__init__(parent)
        self.shortcuts_file = shortcuts_file
        self.shortcuts = []
        self.init_ui()
        
        if shortcuts_file:
            self.load_shortcuts()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()
        
        # Search bar
        search_layout = QtWidgets.QHBoxLayout()
        search_layout.addWidget(QtWidgets.QLabel("Search:"))
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Filter shortcuts by name or description...")
        self.search_edit.textChanged.connect(self.filter_shortcuts)
        search_layout.addWidget(self.search_edit)
        layout.addLayout(search_layout)
        
        # Shortcuts table
        self.table_view = QtWidgets.QTableView()
        self.table_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table_view.doubleClicked.connect(self.execute_shortcut)
        layout.addWidget(self.table_view)
        
        # Details panel
        details_group = QtWidgets.QGroupBox("Shortcut Details")
        details_layout = QtWidgets.QVBoxLayout()
        
        self.details_text = QtWidgets.QTextBrowser()
        self.details_text.setOpenExternalLinks(True)
        details_layout.addWidget(self.details_text)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.favorite_btn = QtWidgets.QPushButton("☆ Add to Favorites")
        self.favorite_btn.clicked.connect(self.toggle_favorite)
        button_layout.addWidget(self.favorite_btn)
        
        self.execute_btn = QtWidgets.QPushButton("Execute Shortcut")
        self.execute_btn.clicked.connect(self.execute_selected_shortcut)
        button_layout.addWidget(self.execute_btn)
        
        self.send_to_prompt_btn = QtWidgets.QPushButton("Send to Prompt")
        self.send_to_prompt_btn.setToolTip("Send horizontal PML script to PyMOL prompt for editing before execution")
        self.send_to_prompt_btn.clicked.connect(self.send_to_prompt)
        button_layout.addWidget(self.send_to_prompt_btn)
        
        self.copy_pml_btn = QtWidgets.QPushButton("Copy PML Code")
        self.copy_pml_btn.clicked.connect(self.copy_pml_code)
        button_layout.addWidget(self.copy_pml_btn)
        
        self.copy_python_btn = QtWidgets.QPushButton("Copy Python Code")
        self.copy_python_btn.clicked.connect(self.copy_python_code)
        button_layout.addWidget(self.copy_python_btn)
        
        details_layout.addLayout(button_layout)
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        self.setLayout(layout)
    
    def load_shortcuts(self):
        """Load shortcuts from file."""
        if not self.shortcuts_file or not os.path.exists(self.shortcuts_file):
            self.details_text.setHtml("<p>No shortcuts file specified.</p>")
            return
        
        self.shortcuts = ShortcutsParser.parse_shortcuts(self.shortcuts_file)
        self.model = ShortcutsTableModel(self.shortcuts)
        self.proxy_model = QtCore.QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.proxy_model.setFilterKeyColumn(-1)  # Search all columns
        
        self.table_view.setModel(self.proxy_model)
        self.table_view.resizeColumnsToContents()
        self.table_view.horizontalHeader().setStretchLastSection(True)
        
        # Connect selection change signal after model is set
        # Disconnect first in case we're reloading
        try:
            self.table_view.selectionModel().selectionChanged.disconnect(self.show_details)
        except:
            pass  # No previous connection
        self.table_view.selectionModel().selectionChanged.connect(self.show_details)
        
        self.details_text.setHtml(f"<p>Loaded {len(self.shortcuts)} shortcuts.</p>")
    
    def set_shortcuts_file(self, filepath):
        """Set the shortcuts file and reload."""
        self.shortcuts_file = filepath
        self.load_shortcuts()
    
    def filter_shortcuts(self, text):
        """Filter shortcuts based on search text."""
        if hasattr(self, 'proxy_model'):
            self.proxy_model.setFilterFixedString(text)
    
    def show_details(self, selected, deselected):
        """Show detailed information about selected shortcut."""
        # Check if model exists
        if not hasattr(self, 'model') or self.model is None:
            return
            
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return
        
        proxy_index = indexes[0]
        source_index = self.proxy_model.mapToSource(proxy_index)
        shortcut = self.model.get_shortcut(source_index.row())
        
        if not shortcut:
            return
        
        # Build HTML display with links
        html = f"""
        <h2>{shortcut.name}</h2>
        <p><strong>Keybinding:</strong> {shortcut.keybinding}</p>
        
        <h3>Description</h3>
        <p>{self._format_text(shortcut.description)}</p>
        
        <h3>Usage</h3>
        <pre>{self._format_text(shortcut.usage)}</pre>
        
        <h3>Arguments</h3>
        <p>{self._format_text(shortcut.arguments)}</p>
        
        <h3>Example</h3>
        <pre>{self._format_text(shortcut.example)}</pre>
        
        <h3>More Details</h3>
        <p>{self._format_text(shortcut.details)}</p>
        
        <h3>PML Code (Vertical)</h3>
        <pre style="background-color: #f0f0f0; padding: 10px;">{self._format_text(shortcut.pml_vertical)}</pre>
        
        <h3>PML Code (Horizontal)</h3>
        <pre style="background-color: #f0f0f0; padding: 10px;">{self._format_text(shortcut.pml_horizontal)}</pre>
        
        <h3>Python Code</h3>
        <pre style="background-color: #f0f0f0; padding: 10px;">{self._format_text(shortcut.python_code)}</pre>
        """
        
        self.details_text.setHtml(html)
        self.update_favorite_button()
    
    def _format_text(self, text):
        """Format text for HTML display."""
        if not text:
            return "<i>Not available</i>"
        # Escape HTML special characters
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return text
    
    def get_selected_shortcut(self):
        """Get the currently selected shortcut."""
        # Check if model exists
        if not hasattr(self, 'model') or self.model is None:
            return None
            
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return None
        
        proxy_index = indexes[0]
        source_index = self.proxy_model.mapToSource(proxy_index)
        return self.model.get_shortcut(source_index.row())
    
    def execute_shortcut(self, index=None):
        """Execute the selected shortcut by entering its keybinding at the PyMOL prompt."""
        shortcut = self.get_selected_shortcut()
        if not shortcut:
            return
        
        try:
            # Execute the shortcut command
            cmd.do(shortcut.keybinding)
            print(f"Executed shortcut: {shortcut.keybinding}")
            
            # Add to history if history tab exists
            main_window = self.window()
            if hasattr(main_window, 'history_tab'):
                main_window.history_tab.add_to_history(shortcut.keybinding)
        except Exception as e:
            print(f"Error executing shortcut {shortcut.keybinding}: {e}")
    
    def toggle_favorite(self):
        """Toggle favorite status of selected shortcut."""
        shortcut = self.get_selected_shortcut()
        if not shortcut:
            QtWidgets.QMessageBox.information(
                self,
                "No Shortcut Selected",
                "Please select a shortcut from the table first."
            )
            return
        
        main_window = self.window()
        if not hasattr(main_window, 'favorites_tab'):
            QtWidgets.QMessageBox.warning(
                self,
                "Favorites Not Available",
                "The Favorites tab is not available."
            )
            return
        
        favorites_tab = main_window.favorites_tab
        
        if favorites_tab.is_favorite(shortcut.keybinding):
            # Remove from favorites
            favorites_tab.remove_favorite_by_name(shortcut.keybinding)
            self.favorite_btn.setText("☆ Add to Favorites")
            print(f"Removed {shortcut.keybinding} from favorites")
        else:
            # Add to favorites
            favorites_tab.add_favorite(shortcut.keybinding)
            self.favorite_btn.setText("★ Remove from Favorites")
            print(f"Added {shortcut.keybinding} to favorites")
    
    def update_favorite_button(self):
        """Update favorite button based on current selection."""
        shortcut = self.get_selected_shortcut()
        if not shortcut:
            self.favorite_btn.setText("☆ Add to Favorites")
            return
        
        main_window = self.window()
        if hasattr(main_window, 'favorites_tab'):
            if main_window.favorites_tab.is_favorite(shortcut.keybinding):
                self.favorite_btn.setText("★ Remove from Favorites")
            else:
                self.favorite_btn.setText("☆ Add to Favorites")
    
    def execute_selected_shortcut(self):
        """Execute the selected shortcut from button click."""
        self.execute_shortcut()
    
    def copy_pml_code(self):
        """Copy PML code to clipboard."""
        shortcut = self.get_selected_shortcut()
        if not shortcut or not shortcut.pml_horizontal:
            return
        
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(shortcut.pml_horizontal)
        print(f"Copied PML code for {shortcut.name} to clipboard")
    
    def copy_python_code(self):
        """Copy Python code to clipboard."""
        shortcut = self.get_selected_shortcut()
        if not shortcut or not shortcut.python_code:
            return
        
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(shortcut.python_code)
        print(f"Copied Python code for {shortcut.name} to clipboard")
    
    def send_to_prompt(self):
        """Send horizontal PML script to prompt for user editing."""
        shortcut = self.get_selected_shortcut()
        if not shortcut:
            QtWidgets.QMessageBox.information(
                self,
                "No Shortcut Selected",
                "Please select a shortcut from the table first."
            )
            return
        
        if not shortcut.pml_horizontal:
            QtWidgets.QMessageBox.information(
                self,
                "No PML Code Available",
                f"The shortcut '{shortcut.name}' does not have horizontal PML code available."
            )
            return
        
        # Copy to clipboard
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(shortcut.pml_horizontal)
        
        # Show explanatory dialog
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Send to Prompt - Instructions")
        dialog.setMinimumWidth(500)
        
        layout = QtWidgets.QVBoxLayout()
        
        # Title
        title_label = QtWidgets.QLabel(f"<h3>PML Code for: {shortcut.name}</h3>")
        layout.addWidget(title_label)
        
        # Instructions
        instructions = QtWidgets.QLabel(
            "<p><b>How to use this feature:</b></p>"
            "<ol>"
            "<li>The horizontal PML script has been <b>copied to your clipboard</b></li>"
            "<li>Click on the PyMOL command prompt (the input line at the bottom of PyMOL)</li>"
            "<li>Paste the code using:"
            "<ul>"
            "<li><b>macOS:</b> Cmd+V</li>"
            "<li><b>Windows/Linux:</b> Ctrl+V</li>"
            "<li><b>Or:</b> Right-click and select Paste</li>"
            "</ul>"
            "</li>"
            "<li><b>Edit the code</b> as needed (change parameters, add options, etc.)</li>"
            "<li>Press <b>Enter</b> to execute the customized command</li>"
            "</ol>"
            "<p><b>Tip:</b> This allows you to see and modify the PML code before running it, "
            "which is useful for learning PyMOL commands or adjusting parameters.</p>"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Show the code
        code_group = QtWidgets.QGroupBox("PML Code (copied to clipboard):")
        code_layout = QtWidgets.QVBoxLayout()
        
        code_display = QtWidgets.QTextEdit()
        code_display.setPlainText(shortcut.pml_horizontal)
        code_display.setReadOnly(True)
        code_display.setMaximumHeight(100)
        code_display.setStyleSheet("font-family: monospace; background-color: #f0f0f0;")
        code_layout.addWidget(code_display)
        
        code_group.setLayout(code_layout)
        layout.addWidget(code_group)
        
        # Note about PyMOL prompt location
        note_label = QtWidgets.QLabel(
            "<p><i>Note: The PyMOL command prompt is typically located at the bottom "
            "of the PyMOL window, below the viewing area. It shows a '> PyMOL>' prefix.</i></p>"
        )
        note_label.setWordWrap(True)
        layout.addWidget(note_label)
        
        # Buttons
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        dialog.exec_()
        
        print(f"PML code for {shortcut.name} copied to clipboard - paste into PyMOL prompt to customize and execute")


class PyMOLShortcutsPlugin(QtWidgets.QDialog):
    """Main plugin dialog with tabbed interface."""
    
    def __init__(self, parent=None):
        super(PyMOLShortcutsPlugin, self).__init__(parent)
        self.setWindowTitle("PyMOL Shortcuts Manager")
        self.setMinimumSize(900, 700)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout()

        # Create tab widget
        self.tabs = QtWidgets.QTabWidget()

        # Create tabs
        self.install_tab = InstallationTab()
        self.shortcuts_tab = ShortcutsTab()
        self.add_shortcut_tab = AddShortcutTab()
        self.ai_tab = AIIntegrationTab()
        self.agentic_tab = AgenticAITab(
            ai_tab=self.ai_tab,
            add_shortcut_tab=self.add_shortcut_tab,
            shortcuts_tab=self.shortcuts_tab,
        )
        self.history_tab = HistoryTab()
        self.favorites_tab = FavoritesTab()
        self.tutorial_tab = TutorialTab()
        self.citation_tab = CitationTab()
        self.settings_tab = SettingsTab()
        self.links_tab = LinksTab()

        self.tabs.addTab(self.install_tab, "Installation")
        self.tabs.addTab(self.shortcuts_tab, "Shortcuts")
        self.tabs.addTab(self.add_shortcut_tab, "Add Shortcut")
        self.tabs.addTab(self.ai_tab, "AI Assistant")
        self.tabs.addTab(self.agentic_tab, "Agentic AI")
        self.tabs.addTab(self.history_tab, "History")
        self.tabs.addTab(self.favorites_tab, "Favorites")
        self.tabs.addTab(self.tutorial_tab, "Tutorial")
        self.tabs.addTab(self.citation_tab, "Citation")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.links_tab, "Links")

        # Set default tab to Shortcuts
        self.tabs.setCurrentIndex(1)

        # Connect the InstallationTab's success signal (fires only after
        # cmd.do("run ...") succeeds, carrying the verified filepath).
        self.install_tab.shortcuts_installed.connect(self.on_shortcuts_installed)

        # Auto-populate the Shortcuts tab from saved settings or the
        # module-level path that __init_plugin__ recorded at startup.
        self._auto_populate_shortcuts()

        layout.addWidget(self.tabs)

        # Close button
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self.setLayout(layout)

        # Apply saved appearance settings (font size & theme) on first open.
        # Called AFTER setLayout so the full widget tree is assembled and the
        # stylesheet cascades to every child widget.
        self.settings_tab.apply_appearance(target=self)

    def _auto_populate_shortcuts(self):
        """Populate the Shortcuts tab on startup from the best available source.

        Resolution order (first match wins):
        1. The module-level ``_auto_loaded_shortcuts_path`` set by
           ``__init_plugin__`` (highest priority because the file was
           already ``run`` into PyMOL during this session).
        2. The ``shortcuts/default_path`` stored in QSettings (persisted
           across sessions by ``on_shortcuts_installed``).
        3. Well-known filesystem locations where pymolshortcuts.py is
           commonly placed (covers the case where the user loaded
           shortcuts via ``.pymolrc`` or manually before the plugin was
           ever configured).
        """
        global _auto_loaded_shortcuts_path

        filepath = None

        # Priority 1: path from __init_plugin__ auto-load
        if _auto_loaded_shortcuts_path and os.path.exists(_auto_loaded_shortcuts_path):
            filepath = _auto_loaded_shortcuts_path

        # Priority 2: default path saved in QSettings
        if filepath is None:
            settings = QtCore.QSettings("MooersLab", "PyMOLShortcutsPlugin")
            saved_path = settings.value("shortcuts/default_path", "")
            if saved_path and os.path.exists(saved_path):
                filepath = saved_path

        # Priority 3: scan well-known locations
        if filepath is None:
            home = os.path.expanduser("~")
            candidates = [
                os.path.join(home, "pymolshortcuts.py"),
                os.path.join(home, "Library", "PyMOL", "startup", "pymolshortcuts.py"),
                os.path.join(home, ".pymol", "startup", "pymolshortcuts.py"),
            ]
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                candidates.append(
                    os.path.join(appdata, "PyMOL", "startup", "pymolshortcuts.py")
                )
            for candidate in candidates:
                if os.path.exists(candidate):
                    filepath = candidate
                    break

        if filepath:
            self.shortcuts_tab.set_shortcuts_file(filepath)
            # Keep install_tab in sync so the AI tab can also find the file
            self.install_tab.last_installed_path = filepath
            # Keep the Agentic AI tab in sync so its retrieval context and
            # its Append to Shortcuts File button both target the right file.
            self.agentic_tab.set_shortcuts_file(filepath)
            print(f"Shortcuts tab populated from: {filepath}")

    def on_shortcuts_installed(self, filepath):
        """Handle successful shortcuts installation.

        Called by the InstallationTab.shortcuts_installed signal with the
        verified filepath.  Persists the path in QSettings so that the
        Shortcuts tab auto-populates on every subsequent plugin open.
        """
        global _auto_loaded_shortcuts_path

        if not filepath or not os.path.exists(filepath):
            return

        # 1. Refresh the Shortcuts table immediately
        self.shortcuts_tab.set_shortcuts_file(filepath)

        # 2. Persist the path in QSettings so it survives dialog close/reopen
        settings = QtCore.QSettings("MooersLab", "PyMOLShortcutsPlugin")
        settings.setValue("shortcuts/default_path", filepath)
        settings.sync()

        # 3. Update the Settings tab widget so it stays in sync
        self.settings_tab.default_shortcuts_path.setText(filepath)

        # 4. Update the module-level variable for the AI tab fallback
        _auto_loaded_shortcuts_path = filepath

        # 4b. Point the Agentic AI tab at the same file
        self.agentic_tab.set_shortcuts_file(filepath)

        # 5. Switch to the Shortcuts tab
        self.tabs.setCurrentIndex(1)


def __init_plugin__(app=None):
    """Initialize the plugin."""
    global _auto_loaded_shortcuts_path

    from pymol.plugins import addmenuitemqt
    addmenuitemqt('PyMOL Shortcuts Manager', run_plugin_gui)

    # Auto-load shortcuts if configured
    settings = QtCore.QSettings("MooersLab", "PyMOLShortcutsPlugin")
    auto_load = settings.value("shortcuts/auto_load", False, type=bool)
    default_path = settings.value("shortcuts/default_path", "")
    if auto_load and default_path and os.path.exists(default_path):
        try:
            cmd.do(f"run {default_path}")
            # Store the path so the GUI can populate the Shortcuts tab
            # immediately when the user opens the plugin dialog.
            _auto_loaded_shortcuts_path = default_path
            print(f"Auto-loaded shortcuts from: {default_path}")
        except Exception as e:
            print(f"Failed to auto-load shortcuts: {e}")


def run_plugin_gui():
    """Run the plugin GUI."""
    dialog = PyMOLShortcutsPlugin()
    dialog.exec_()


# For testing outside PyMOL
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    dialog = PyMOLShortcutsPlugin()
    dialog.show()
    sys.exit(app.exec_())

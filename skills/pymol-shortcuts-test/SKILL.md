---
name: pymol-shortcuts-test
description: Write a pytest module for a candidate PyMOL shortcut that runs
  with no PyMOL installation and no display server. Use this skill when the
  task is to test, verify, or add coverage for a shortcut function destined for
  pymolshortcuts.py, when a request mentions "test this pymolshortcut", "write
  tests for the candidate shortcut", or when the Agentic AI tab of the PyMOL
  Shortcuts Manager runs its test stage.
---

# Testing a PyMOL shortcut

The test suite for this project runs on continuous integration machines that
have no PyMOL and no display server, so a test may never import the real
`pymol` package. Mock it before the candidate module is imported. The pattern
below mirrors the mock architecture already used in
`test_pymolshortcuts_manager.py`.

A shortcut is a thin wrapper over a handful of `cmd` calls, so the useful
assertion is almost always about which calls were issued and with what
arguments. Testing the rendered image is neither possible here nor meaningful.

## The mock preamble

```python
import sys
import importlib.util
from unittest.mock import MagicMock

mock_cmd = MagicMock()
mock_pymol = MagicMock(cmd=mock_cmd)
sys.modules['pymol'] = mock_pymol
sys.modules['pymol.cmd'] = mock_cmd

spec = importlib.util.spec_from_file_location(
    "candidate", "candidate_<name>.py"
)
candidate = importlib.util.module_from_spec(spec)
candidate.cmd = mock_cmd
spec.loader.exec_module(candidate)
```

Reset the mock between tests with `mock_cmd.reset_mock()` in a fixture, because
a shared MagicMock accumulates calls across tests and turns a passing suite
into a lying one.

## What to assert

Write at least four tests.

The first covers the default call. Invoke the shortcut with no arguments and
assert that every command its `VERTICAL PML SCRIPT` section promises was
issued. Compare against `mock_cmd.method_calls` or assert on the specific
method, for example `mock_cmd.color.assert_any_call(...)`.

The second covers a non-default argument. Pass an explicit selection or color
and assert that the value reached the `cmd` call rather than being silently
dropped, which is the usual failure when a shortcut interpolates the wrong
variable.

The third covers the docstring contract. Assert that the function's docstring
contains each of the eight section headers and that `DESCRIPTION:`, `USAGE:`,
`EXAMPLE:`, and `PYTHON CODE:` are followed by text.

The fourth covers registration. Assert that `cmd.extend` was called with the
shortcut's name and the function object.

## What not to do

Do not call `cmd.fetch`, because a test must not reach the network. Do not
assert on the exact number of `cmd` calls unless the shortcut's whole purpose
is a fixed sequence, because an incidental extra call then breaks a test that
should have passed. Do not use `time.sleep`. Do not write files.

## Skeleton

```python
import pytest


@pytest.fixture(autouse=True)
def clean_cmd():
    mock_cmd.reset_mock()
    yield


def test_default_call_issues_expected_commands():
    candidate.colorBP()
    assert mock_cmd.color.call_count == 2


def test_selection_reaches_the_command():
    candidate.colorBP(selection='chain A')
    args = [call.args[1] for call in mock_cmd.color.call_args_list]
    assert all('chain A' in arg for arg in args)


def test_docstring_carries_every_section():
    doc = candidate.colorBP.__doc__
    for header in ("DESCRIPTION:", "USAGE:", "ARGUMENTS:", "EXAMPLE:",
                   "MORE DETAILS:", "VERTICAL PML SCRIPT:",
                   "HORIZONTAL PML SCRIPT:", "PYTHON CODE:"):
        assert header in doc


def test_shortcut_is_registered():
    names = [call.args[0] for call in mock_cmd.extend.call_args_list]
    assert 'colorBP' in names
```

Use only pytest and `unittest.mock`. Add no third-party dependency.

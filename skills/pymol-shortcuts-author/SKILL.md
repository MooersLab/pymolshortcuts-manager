---
name: pymol-shortcuts-author
description: Write one new shortcut for pymolshortcuts.py that satisfies the
  Mooers Laboratory docstring contract. Use this skill when the task is to
  author, extend, or repair a PyMOL shortcut function that will be appended to
  pymolshortcuts.py, when a request mentions "write a pymolshortcut", "add a
  shortcut to pymolshortcuts.py", "generate a PyMOL shortcut", or when the
  Agentic AI tab of the PyMOL Shortcuts Manager runs its generate stage.
---

# Authoring a PyMOL shortcut

A shortcut is one top-level Python function plus one `cmd.extend` call. The
plugin parses the function's docstring to fill its table, its detail pane, and
its clipboard buttons, so the docstring is a machine-read contract rather than
a courtesy to the reader. A shortcut whose docstring drifts from the contract
disappears from the table even though the code runs.

## The contract

Write exactly one top-level function. Give it a single-quoted triple-quoted
docstring holding these eight section headers, each alone on its line, in this
order:

```
DESCRIPTION:
USAGE:
ARGUMENTS:
EXAMPLE:
MORE DETAILS:
VERTICAL PML SCRIPT:
HORIZONTAL PML SCRIPT:
PYTHON CODE:
```

Four of them must be non-empty: `DESCRIPTION:`, `USAGE:`, `EXAMPLE:`, and
`PYTHON CODE:`. Write `None` under `ARGUMENTS:` when the function takes no
arguments rather than leaving the section blank.

The two PML sections carry the same commands. The vertical one puts one command
per line. The horizontal one joins those same commands with semicolons so the
user can paste a single line into the PyMOL prompt. A mismatch between the two
is the most common defect in a generated shortcut, so write the vertical script
first and derive the horizontal one from it mechanically.

End the module with `cmd.extend('<name>', <name>)`, where `<name>` matches the
function name exactly. The name is also the command the user types in PyMOL.

## Style

Follow the examples you are given rather than inventing a house style. When no
examples are supplied, keep to these rules: import nothing but
`from pymol import cmd` and the standard library; give every argument a default
so the shortcut runs bare; accept `selection='all'` as the first argument
whenever the operation could sensibly apply to a subset; and prefer
`cmd.set`, `cmd.color`, `cmd.show_as`, and the other Python API calls over
`cmd.do` with a command string, because the API raises a catchable exception
where `cmd.do` swallows one.

Keep the function short. A shortcut that runs to fifty lines is a script, and a
script belongs in its own file.

## Prohibitions

The generated code runs inside the user's live PyMOL session, so never call
`eval`, `exec`, `compile`, `__import__`, `input`, `os.system`, `os.remove`,
`shutil.rmtree`, or anything in `subprocess`. The validator rejects a candidate
that contains any of them.

Never write to a path outside the run directory you were given.

## Worked example

```python
from pymol import cmd


def colorBP(selection='all', purine='skyblue', pyrimidine='salmon'):
    '''
    DESCRIPTION:
    Color the bases of a nucleic acid by purine or pyrimidine identity.

    USAGE:
    colorBP [selection [, purine [, pyrimidine]]]

    ARGUMENTS:
    selection: PyMOL selection (default: all)
    purine: color applied to A and G (default: skyblue)
    pyrimidine: color applied to C, U, and T (default: salmon)

    EXAMPLE:
    colorBP chain A, marine, firebrick

    MORE DETAILS:
    Colors only the base atoms, so the backbone keeps whatever color it
    already carries. Useful for showing base composition along a duplex.

    VERTICAL PML SCRIPT:
    color skyblue, all and resn A+G and not (name P+OP1+OP2+O5'+C5'+C4'+O4'+C3'+O3'+C2'+O2'+C1')
    color salmon, all and resn C+U+T and not (name P+OP1+OP2+O5'+C5'+C4'+O4'+C3'+O3'+C2'+O2'+C1')

    HORIZONTAL PML SCRIPT:
    color skyblue, all and resn A+G and not (name P+OP1+OP2+O5'+C5'+C4'+O4'+C3'+O3'+C2'+O2'+C1'); color salmon, all and resn C+U+T and not (name P+OP1+OP2+O5'+C5'+C4'+O4'+C3'+O3'+C2'+O2'+C1')

    PYTHON CODE:
    backbone = "name P+OP1+OP2+O5'+C5'+C4'+O4'+C3'+O3'+C2'+O2'+C1'"
    cmd.color(purine, f"{selection} and resn A+G and not ({backbone})")
    cmd.color(pyrimidine, f"{selection} and resn C+U+T and not ({backbone})")
    '''
    backbone = "name P+OP1+OP2+O5'+C5'+C4'+O4'+C3'+O3'+C2'+O2'+C1'"
    cmd.color(purine, f"{selection} and resn A+G and not ({backbone})")
    cmd.color(pyrimidine, f"{selection} and resn C+U+T and not ({backbone})")


cmd.extend('colorBP', colorBP)
```

## Checklist before you finish

- One top-level function, named as requested.
- All eight docstring headers present, four of them filled.
- The horizontal PML script matches the vertical one command for command.
- `cmd.extend` present and spelled with the same name.
- No banned call anywhere in the module.
- The function runs without error on the reference structure you were given.

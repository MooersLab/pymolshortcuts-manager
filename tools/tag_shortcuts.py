#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""First-pass tagger for pymolshortcuts.py.

This is a one-time developer tool, not part of the distributed plugin, so
it is self-contained and does not import the plugin (which imports PyMOL).
It proposes a TAGS section for every shortcut that lacks one, drawing the
tags from the comment banner the shortcut sits under and from keyword cues
in the description, the details, and the function body.  The proposals are
a first draft for human review, never a final answer.

Usage
-----
    python3 tools/tag_shortcuts.py pymolshortcuts.py            # dry run
    python3 tools/tag_shortcuts.py pymolshortcuts.py --diff     # show diff
    python3 tools/tag_shortcuts.py pymolshortcuts.py --apply    # write file

A dry run writes the proposals to tools/tag_proposals.tsv and a unified
diff to tools/tags.diff, and prints a summary.  --apply rewrites the file
in place after a timestamped backup.

The TAGS section is placed immediately after the DESCRIPTION block, in the
same format the live editor in the plugin writes, so a shortcut tagged
here round-trips cleanly through a later edit in the Shortcuts tab.
"""

from __future__ import print_function
import argparse
import difflib
import os
import re
import shutil
from datetime import datetime

# The controlled vocabulary.  Keep this in step with TAG_VOCABULARY in
# pymolshortcuts_manager.py.
TAG_VOCABULARY = (
    "web-search", "database-search", "data-analysis", "image-manipulation",
    "molecular-graphics", "text-editor", "terminal", "website",
    "rendering", "ambient-occlusion", "coloring", "selection", "measurement",
    "alignment", "superposition", "symmetry", "electron-density", "map",
    "publication", "fetch", "save-session", "animation", "surface", "cartoon",
    "sticks", "spheres", "mesh", "label", "view", "sequence", "quit",
    "utility",
)

SHORTCUT_DOC_MARKERS = (
    "DESCRIPTION:", "TAGS:", "USAGE:", "ARGUMENTS:", "EXAMPLE:",
    "MORE DETAILS:", "VERTICAL PML SCRIPT:", "HORIZONTAL PML SCRIPT:",
    "PYTHON CODE:",
)

# Keyword cues mapped to tags.  Each (needles, tags) rule fires when any
# needle appears in the lowercased haystack of name, description, details,
# and function body.  Web shortcuts are handled separately in compute_tags
# from the actual browser call, so no web rules live here.
KEYWORD_RULES = (
    (("cmd.fetch", "fetch(", " fetch "), ("fetch", "molecular-graphics")),
    (("ambient", "ambient_occlusion"), ("ambient-occlusion", "rendering")),
    (("ray(", "ray ", "ray_trace", ".png", "png(", "draw("),
     ("rendering",)),
    (("publication", "300 dpi", "dpi", "figure"), ("publication",)),
    (("set_color", "spectrum", "util.cbc", "color(", "recolor", "colour"),
     ("coloring",)),
    (("cealign", "cmd.align", "cmd.super", "align(", "super("),
     ("alignment",)),
    (("super(", "cmd.super", "superpose", "superimpose"), ("superposition",)),
    (("get_distance", "cmd.distance", "dihedral", "get_angle", "measure"),
     ("measurement",)),
    (("symexp", "symmetry", "unit cell", "unitcell", "unit_cell"),
     ("symmetry",)),
    (("isomesh", "ccp4", ".mtz", "2fofc", "fofc", "electron density",
      "isosurface", "map_", "cmd.map"), ("electron-density",)),
    (("isomesh", "as mesh", "show mesh"), ("mesh",)),
    (("isosurface", "as surface", "show surface", "get_area"), ("surface",)),
    ((".pse", "save session", "session file", "save_session"),
     ("save-session",)),
    (("quit", "reinitialize", "reinit"), ("quit",)),
    (("mset", "mplay", "movie", "frame", "rock", "cmd.turn", "cmd.roll"),
     ("animation",)),
    (("as cartoon", "show cartoon", "cartoon"), ("cartoon",)),
    (("as sticks", "show sticks", "show_as sticks"), ("sticks",)),
    (("as spheres", "show spheres"), ("spheres",)),
    (("cmd.label", "label ", "labels"), ("label",)),
    (("set_view", "get_view", "orient", "zoom", "turn ", "reset "), ("view",)),
    (("fasta", "sequence", "get_fastastr"), ("sequence",)),
    (("cmd.select", "select ", "selection"), ("selection",)),
    (("bbedit", "emacs", "vim", "nano", "sublime", "vscode", "textmate",
      "notepad", "gedit"), ("text-editor",)),
    (("iterm", "xterm", "konsole", "gnome-terminal"), ("terminal",)),
    (("jupyter", "rstudio", "pandas", "numpy", "matplotlib", "excel",
      "libreoffice"), ("data-analysis",)),
    (("gimp", "photoshop", "inkscape", "imagemagick", "affinity"),
     ("image-manipulation",)),
    (("coot", "chimera", "vmd", "jmol", "molscript", "raster3d", "ccp4i"),
     ("molecular-graphics",)),
)

MAX_TAGS = 4


def normalize_tags(value):
    """Return a clean, ordered, unique list of tags from a string or list."""
    if not value:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\n]", value)
    else:
        parts = []
        for item in value:
            parts.extend(re.split(r"[,\n]", str(item)))
    seen = []
    for part in parts:
        tag = re.sub(r"\s+", "-", part.strip().lower())
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def _doc_marker(line):
    stripped = line.strip()
    for marker in SHORTCUT_DOC_MARKERS:
        if stripped == marker or stripped.startswith(marker):
            return marker
    return None


def _rewrite_tags_in_source(content, name, tags):
    """Insert or replace the TAGS section of one shortcut in source text.

    This mirrors update_shortcut_tags in the plugin so tags land in the
    same place and the same format the live editor uses.
    """
    pattern = re.compile(
        r"(def\s+" + re.escape(name) + r"\([^)]*\):\s*''')(.*?)(''')",
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return content, False

    lines = match.group(2).split("\n")

    indent = "    "
    for line in lines:
        if _doc_marker(line) == "DESCRIPTION:":
            indent = line[:len(line) - len(line.lstrip())] or "    "
            break

    tags_index = next(
        (i for i, line in enumerate(lines) if _doc_marker(line) == "TAGS:"),
        None,
    )
    if tags_index is not None:
        end = tags_index + 1
        while end < len(lines) and _doc_marker(lines[end]) is None:
            end += 1
        del lines[tags_index:end]

    desc_index = next(
        (i for i, line in enumerate(lines)
         if _doc_marker(line) == "DESCRIPTION:"),
        None,
    )

    normalized = normalize_tags(tags)
    if normalized:
        block = [indent + "TAGS:", indent + ", ".join(normalized), ""]
        insert_at = len(lines)
        if desc_index is not None:
            for i in range(desc_index + 1, len(lines)):
                if _doc_marker(lines[i]) is not None:
                    insert_at = i
                    break
        else:
            insert_at = 0
        if insert_at > 0 and lines[insert_at - 1].strip() != "":
            block = [""] + block
        lines[insert_at:insert_at] = block

    new_body = "\n".join(lines)
    new_content = content[:match.start(2)] + new_body + content[match.end(2):]
    return new_content, True


def _section(docstring, marker):
    """Pull one section's text out of a raw docstring."""
    lines = docstring.split("\n")
    collecting = False
    collected = []
    for line in lines:
        mk = _doc_marker(line)
        if mk == marker:
            collecting = True
            continue
        if collecting and mk is not None:
            break
        if collecting:
            collected.append(line.strip())
    return "\n".join(collected).strip()


def compute_tags(name, docstring, body):
    """Propose tags for one shortcut. Always returns at least one tag."""
    description = _section(docstring, "DESCRIPTION:")
    details = _section(docstring, "MORE DETAILS:")
    doc = " ".join([name, description, details]).lower()
    body_l = body.lower()
    haystack = doc + " " + body_l

    tags = []

    # Web shortcuts are recognised by the actual browser call in the body,
    # then classified as exactly one of database-search, web-search, or a
    # plain website launcher.
    if "webbrowser" in body_l:
        database = ("rcsb", "wwpdb", "uniprot", "ncbi", "pubmed", "genbank",
                    "protein data bank", "pdb ")
        search = ("arxiv", "biorxiv", "scholar", "springer", "sciencedirect",
                  "researchgate", "stackoverflow", "google", "amazon", "bing",
                  "duckduckgo", "youtube", "search")
        if any(key in haystack for key in database):
            tags.append("database-search")
        elif any(key in haystack for key in search):
            tags.append("web-search")
        else:
            tags.append("website")

    for needles, rule_tags in KEYWORD_RULES:
        if any(needle in haystack for needle in needles):
            for tag in rule_tags:
                if tag not in tags:
                    tags.append(tag)

    # Keep only vocabulary tags, then cap the count.
    known = set(TAG_VOCABULARY)
    tags = [tag for tag in tags if tag in known]
    if not tags:
        tags = ["utility"]
    return tags[:MAX_TAGS]


def parse_shortcuts(content):
    """Yield (name, docstring, body, start_offset) for each shortcut."""
    pattern = r"def\s+(\w+)\([^)]*\):\s*'''\s*(.*?)'''\s*(.*?)(?=\ndef\s+\w+\(|$)"
    for match in re.finditer(pattern, content, re.DOTALL):
        docstring = match.group(2)
        if "DESCRIPTION" not in docstring:
            continue
        yield match.group(1), docstring, match.group(3), match.start()


def main():
    parser = argparse.ArgumentParser(description="First-pass tagger.")
    parser.add_argument("path", help="path to pymolshortcuts.py")
    parser.add_argument("--apply", action="store_true",
                        help="write the file in place after a backup")
    parser.add_argument("--diff", action="store_true",
                        help="print the unified diff to stdout")
    parser.add_argument("--force", action="store_true",
                        help="retag shortcuts that already carry a TAGS section")
    args = parser.parse_args()

    with open(args.path, "r", encoding="utf-8") as handle:
        original = handle.read()

    proposals = []
    for name, docstring, body, offset in parse_shortcuts(original):
        if not args.force and "TAGS:" in docstring:
            continue
        tags = compute_tags(name, docstring, body)
        proposals.append((name, tags))

    content = original
    for name, tags in proposals:
        content, found = _rewrite_tags_in_source(content, name, tags)
        if not found:
            print(f"WARNING: could not locate {name}")

    here = os.path.dirname(os.path.abspath(__file__))
    tsv_path = os.path.join(here, "tag_proposals.tsv")
    with open(tsv_path, "w", encoding="utf-8") as handle:
        for name, tags in proposals:
            handle.write(f"{name}\t{', '.join(tags)}\n")

    diff = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        content.splitlines(keepends=True),
        fromfile=args.path, tofile=args.path + " (tagged)",
    ))
    diff_path = os.path.join(here, "tags.diff")
    with open(diff_path, "w", encoding="utf-8") as handle:
        handle.writelines(diff)

    if args.diff:
        print("".join(diff))

    # Summary counts.
    counter = {}
    for _, tags in proposals:
        for tag in tags:
            counter[tag] = counter.get(tag, 0) + 1
    print(f"Shortcuts tagged: {len(proposals)}")
    print(f"Proposals written to: {tsv_path}")
    print(f"Diff written to:      {diff_path}")
    print("Tag frequency:")
    for tag, count in sorted(counter.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {tag}")

    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f"{args.path}.{stamp}.bak"
        shutil.copy2(args.path, backup)
        with open(args.path, "w", encoding="utf-8") as handle:
            handle.write(content)
        print(f"Applied. Backup written to {backup}")
    else:
        print("Dry run. Re-run with --apply to write the file.")


if __name__ == "__main__":
    main()

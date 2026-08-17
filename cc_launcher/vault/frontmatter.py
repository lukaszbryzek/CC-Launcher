"""Reading a note's YAML frontmatter, and making sense of a linked value.

Two jobs, both of which the reference implementation did nearly right and
therefore silently wrong in cases this vault will reach.
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    import yaml
except ImportError:  # degraded, but a missing parser must not stop the scan
    yaml = None

# What ends a frontmatter block. YAML allows either; Obsidian writes the first.
_CLOSERS = ("---", "...")

# Frontmatter is tens of lines. A block past this is an accident or an attack,
# and either way it is not something the gates can read a codename out of.
MAX_BLOCK_CHARS = 65536

# A YAML anchor definition. Obsidian never writes anchors, and SafeLoader still
# expands aliases -- a few hundred bytes of nested anchors balloon into
# gigabytes (the billion-laughs shape), which no size cap on the block catches.
_ANCHOR = re.compile(r"&\S+")


def split_frontmatter(text: str) -> str | None:
    """The frontmatter block's own text, or None when there is not one.

    Delimiters are matched as whole lines. The reference implementation tested
    `text.startswith("---")` and then searched for the next `"\\n---"` anywhere,
    which makes two mistakes: a note opening with a `----` horizontal rule looks
    like frontmatter, and a block whose value contains a line starting with
    three dashes is cut short there, dropping everything after it without a
    word.
    """
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip() in _CLOSERS:
            return "\n".join(lines[1:index])
    # An unterminated block is not frontmatter; treating the whole note as one
    # would hand the body to a YAML parser.
    return None


def _flat_parse(block: str) -> dict:
    """A minimal reader for when PyYAML is absent.

    Handles `key: value` and the `key:` / `  - item` list form. Lists are worth
    the extra few lines: they are exactly the shape that breaks link resolution,
    so a fallback that dropped them would reintroduce the bug it is standing in
    for.

    Rejects what it cannot read, mirroring parse()'s contract: with PyYAML a
    bad block is no block, and the same vault must not grade differently on a
    machine that merely lacks the parser.
    """
    data: dict = {}
    key = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and key is not None:
            # Not setdefault: the `key:` line above already stored None for an
            # empty value, and setdefault leaves that in place -- which dropped
            # every list item on the floor.
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(stripped[2:].strip().strip("\"'"))
            continue
        if line[:1] in (" ", "\t"):
            continue
        name, sep, value = line.partition(":")
        if not sep:
            return {}   # a top-level line that is not `key: value` -- a bad block
        key = name.strip()
        value = value.strip().strip("\"'")
        data[key] = value if value else None
    return data


def parse(block: str) -> dict:
    """Frontmatter text into a mapping. Never raises; a bad block is no block."""
    if len(block) > MAX_BLOCK_CHARS or _ANCHOR.search(block):
        return {}
    if yaml is None:
        return _flat_parse(block)
    try:
        data = yaml.safe_load(block)
    except Exception:
        # Not just YAMLError: deeply nested flow collections come back as
        # RecursionError out of the composer, and the contract does not change
        # with the exception type -- a block that cannot be parsed is no block.
        return {}
    return data if isinstance(data, dict) else {}


def read_frontmatter(note: Path) -> dict:
    """A note's frontmatter as a dict. Unreadable or absent means empty.

    utf-8-sig, not utf-8: a BOM survives a plain utf-8 read as U+FEFF glued to
    the opening ---, which silently disabled the whole block for a note saved
    by an editor that writes one. And undecodable is a kind of unreadable --
    caught here, because one note saved in a legacy encoding must not take the
    whole scan down with it.
    """
    try:
        text = note.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    block = split_frontmatter(text)
    return parse(block) if block is not None else {}


def first_scalar(value: object) -> object | None:
    """The first plain value inside whatever nesting it arrived in.

    Needed because the same link reaches us in three shapes depending on how it
    was written, and only one of them is a string:

        parent_project: "[[A]]"      -> "[[A]]"
        parent_project: [[A]]        -> [["A"]]     (YAML reads it as a sequence)
        parent_project:\\n  - "[[A]]" -> ["[[A]]"]   (Obsidian's List property)

    A property that holds one link is one link however it is spelled, so the
    first entry is the answer and the rest is ignored.
    """
    while isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    if isinstance(value, (dict, set)):
        return None
    return value


def strip_wikilink(value: object) -> str:
    """A frontmatter value reduced to the bare note name it points at.

    `[[Note|Alias]]` collapses to `Note`, since the target is what identifies
    the note. Anything that is not a wikilink comes back trimmed and unchanged.

    The reference version started with str(value), which turned a list-valued
    property into its own repr -- "['[[A]]']" -- and that matched no project, so
    a child quietly detached from its parent and rendered as top level. Nothing
    raised, nothing warned; the nesting simply stopped happening.
    """
    scalar = first_scalar(value)
    if scalar is None:
        return ""
    text = str(scalar).strip().strip('"').strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    return text.split("|", 1)[0].strip()

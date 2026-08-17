"""What the scan found out about one project, and how a pane lays it out.

Two types, deliberately separate. Entry is what the vault says; Row is where a
particular pane decided to put it. The reference implementation had one type
doing both, and paid for it -- see Row.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    """Everything the scan established about one project.

    Assembled once, so drawing a pane and moving the selection never go back to
    disk. Frozen, because these are findings: nothing downstream has any
    business editing what the vault said.

    `gaps` is a tuple rather than a list for the same reason -- a list inside a
    frozen record is still editable in place, which is the mutability the freeze
    was meant to remove.
    """

    name: str                      # the directory name, which is the identifier
    company: str | None            # text_company from the note's frontmatter
    ov_path: Path                  # the project's directory inside the vault
    codebase: Path | None          # where its code is expected to be
    display_name: str = ""         # the note's `name`: a human-facing title
    description: str = ""
    parent: str | None = None      # the parent's identifier, link already resolved
    parent_description: str = ""   # resolved during the scan, not at draw time
    gaps: tuple[str, ...] = ()     # empty means ready

    @property
    def ready(self) -> bool:
        return not self.gaps

    @property
    def label(self) -> str:
        """The row as the picker prints it, and the sort key within a level.

        Left exactly as the reference wrote it, including what a project with no
        company renders as. That case is worth being able to see.
        """
        return f"[{self.company}] {self.name}"

    @property
    def title(self) -> str:
        """The name to show a person: the note's own, or the directory's."""
        return self.display_name or self.name


@dataclass(frozen=True)
class Row:
    """One entry as a pane is about to draw it, indent included.

    Depth used to live on the entry, written into it by the code that ordered
    the list. That made ordering a mutation of someone else's data, with two
    consequences worth avoiding: ordering the same entries twice overwrote the
    first answer, and one project could never appear in two places at once --
    a list and a set of search results, say -- because a single field cannot
    hold two different indents.

    Keeping it here says what it is: not a fact about the project, but a
    decision by whatever is drawing it.
    """

    entry: Entry
    depth: int = 0

    @property
    def label(self) -> str:
        return self.entry.label

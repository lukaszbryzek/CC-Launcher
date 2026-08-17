"""Walking the filesystem to pick a directory.

The state of a directory browser, with no prompt_toolkit in sight: which
directory is open, what is in it, where the cursor sits and what a keypress does
to all three. The screen that draws it lives in configure.py.

Split for the same reason Theme is: this half is the part with rules worth
testing, and testing it should not require a terminal.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

USE = "use"    # confirm the open directory
UP = "up"      # go to the parent
DIR = "dir"    # descend into a subdirectory


@dataclass(frozen=True)
class Item:
    kind: str
    label: str
    path: Path


def nearest_existing(path: Path) -> Path:
    """The deepest ancestor of `path` that is a directory, home as a last resort.

    A configured vault that has since been moved or was never created should not
    dump the browser at the filesystem root; opening the closest place that does
    exist keeps the user near where they meant to be.
    """
    candidate = path if path.is_absolute() else Path.home()
    while True:
        if candidate.is_dir():
            return candidate
        parent = candidate.parent
        if parent == candidate:      # reached the root and found nothing
            return Path.home()
        candidate = parent


class Browser:
    """Which directory is open, and where the cursor is in it."""

    def __init__(self, start: Path, show_hidden: bool = False) -> None:
        self.cwd = nearest_existing(start)
        self.show_hidden = show_hidden
        self.index = 0
        self.error = ""
        self.items: list[Item] = []
        self.refresh()

    # --- contents ------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the listing for the open directory.

        An unreadable directory is reported rather than raised: a browser that
        crashes on /root is worse than one that says it cannot look inside, and
        the user still has the parent to go back to.
        """
        self.error = ""
        items = [Item(USE, "use this directory", self.cwd)]
        if self.cwd.parent != self.cwd:
            items.append(Item(UP, "..", self.cwd.parent))

        try:
            children = sorted(
                (child for child in self.cwd.iterdir() if child.is_dir()),
                key=lambda child: child.name.lower(),
            )
        except OSError as exc:
            self.error = exc.strerror or str(exc)
            children = []

        for child in children:
            if child.name.startswith(".") and not self.show_hidden:
                continue
            items.append(Item(DIR, child.name, child))

        self.items = items
        self.index = min(self.index, len(items) - 1)

    def open(self, directory: Path) -> None:
        """Move into a directory, with the cursor back at the top."""
        self.cwd = directory
        self.index = 0
        self.refresh()

    # --- keys ----------------------------------------------------------------

    def move(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.items)

    def toggle_hidden(self) -> None:
        """Show or hide dot-directories, keeping the cursor on its item if it can.

        Hiding them by default keeps a home directory readable; being unable to
        reach one at all would be a dead end, which is why this exists rather
        than the filter being permanent.
        """
        here = self.items[self.index]
        self.show_hidden = not self.show_hidden
        self.refresh()
        for position, item in enumerate(self.items):
            if item.path == here.path and item.kind == here.kind:
                self.index = position
                return
        self.index = 0

    def activate(self) -> Path | None:
        """Act on the highlighted item. A path means "this one was chosen"."""
        item = self.items[self.index]
        if item.kind == USE:
            return item.path
        self.open(item.path)
        return None

    # --- rendering support ---------------------------------------------------

    def window(self, height: int) -> tuple[int, int]:
        """The slice of items to draw, as (first, last-exclusive).

        The list scrolls rather than the frame growing, so a home directory with
        two hundred entries does not produce a float taller than the terminal.
        The cursor is kept inside the window instead of the window being
        centred on it, which stops the list sliding under the eye on every step.
        """
        total = len(self.items)
        if height >= total:
            return 0, total
        first = min(max(0, self.index - height // 2), total - height)
        return first, first + height

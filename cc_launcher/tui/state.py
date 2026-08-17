"""What the picker knows between keystrokes.

No prompt_toolkit here: this is the scan result plus a cursor, and both are
worth being able to test without a terminal.
"""
from __future__ import annotations

from ..vault.hierarchy import order_by_hierarchy
from ..vault.locations import Locations
from ..vault.model import Entry, Row
from ..vault.scan import scan


class State:
    """The graded vault, and which project is highlighted.

    The selection is remembered as a project name rather than a row number.
    That is the fix for a real annoyance: rescanning is a keypress, and the
    reference clamped the index and left it there, so adding a project that
    sorts earlier -- or fixing one, which moves it from the incomplete pane into
    the ready one -- silently slid the highlight onto a different project. You
    press r to see your fix appear and end up pointing at something else.
    """

    def __init__(self, locations: Locations, disabled: frozenset[str] = frozenset()) -> None:
        self.locations = locations
        self.disabled = disabled
        self.ready: tuple[Row, ...] = ()
        self.incomplete: tuple[Entry, ...] = ()
        self.problems: tuple[str, ...] = ()
        self._name: str | None = None   # the selected project, by identifier
        self._index = 0                 # where it was, for when it is gone
        self.refresh()

    # --- reading -------------------------------------------------------------

    @property
    def index(self) -> int:
        """Where the highlight sits now.

        Looked up rather than stored, so it cannot drift from the name it is
        supposed to follow.
        """
        for position, row in enumerate(self.ready):
            if row.entry.name == self._name:
                return position
        return min(self._index, max(0, len(self.ready) - 1))

    @property
    def selected(self) -> Entry | None:
        return self.ready[self.index].entry if self.ready else None

    # --- moving --------------------------------------------------------------

    def move(self, delta: int) -> None:
        if not self.ready:
            return
        position = (self.index + delta) % len(self.ready)
        self.select(position)

    def select(self, position: int) -> None:
        if not self.ready:
            self._name, self._index = None, 0
            return
        position = max(0, min(position, len(self.ready) - 1))
        self._index = position
        self._name = self.ready[position].entry.name

    # --- rescanning ----------------------------------------------------------

    def refresh(self) -> None:
        """Read the vault again, keeping the highlight on the same project.

        If it is gone -- deleted, or newly incomplete -- the highlight stays at
        the same position instead, which is the least surprising thing left to
        do once the thing it was pointing at no longer exists.
        """
        result = scan(self.locations, self.disabled)
        self.ready = order_by_hierarchy(result.ready)
        self.incomplete = result.incomplete
        self.problems = result.problems

        if not self.ready:
            self._name, self._index = None, 0
            return
        if self._name is None:
            self.select(0)
            return
        if any(row.entry.name == self._name for row in self.ready):
            self._index = self.index      # keep the fallback position current
        else:
            self.select(min(self._index, len(self.ready) - 1))

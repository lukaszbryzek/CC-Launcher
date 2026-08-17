"""Ordering projects so each child follows its parent.

The output is Rows -- entry plus indent -- rather than entries with a depth
written into them. Ordering is a decision about layout, and layout has no
business editing what the scan found.
"""
from __future__ import annotations

from .model import Entry, Row


def order_by_hierarchy(entries: tuple[Entry, ...] | list[Entry]) -> tuple[Row, ...]:
    """Parents first, children beneath, alphabetical by label at every level.

    Two situations are handled on purpose rather than left to chance, because
    either would otherwise make a project vanish from the pane:

    - A child whose parent is not in this set is treated as top level. That
      happens whenever the parent exists but is not ready, since the ready and
      incomplete panes are ordered separately.
    - A cycle of parent links is broken by emitting whatever it did not reach at
      top level afterwards. Without that the walk would either recurse forever
      or silently drop every project in the loop.
    """
    present = {e.name for e in entries}
    children: dict[str, list[Entry]] = {}
    roots: list[Entry] = []

    for entry in entries:
        if entry.parent and entry.parent != entry.name and entry.parent in present:
            children.setdefault(entry.parent, []).append(entry)
        else:
            roots.append(entry)

    ordered: list[Row] = []
    seen: set[str] = set()

    def emit(entry: Entry, depth: int) -> None:
        # `seen` is what stops a cycle: recursion is bounded by the number of
        # projects, not by the shape of the links between them.
        if entry.name in seen:
            return
        seen.add(entry.name)
        ordered.append(Row(entry, depth))
        for child in sorted(children.get(entry.name, []), key=lambda c: c.label):
            emit(child, depth + 1)

    for root in sorted(roots, key=lambda e: e.label):
        emit(root, 0)

    # Anything a cycle kept out of the walk. Shown flat rather than not at all:
    # a project missing from the list is worse than one whose nesting is wrong.
    for entry in sorted(entries, key=lambda e: e.label):
        if entry.name not in seen:
            seen.add(entry.name)
            ordered.append(Row(entry, 0))

    return tuple(ordered)

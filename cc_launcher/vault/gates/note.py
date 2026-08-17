"""The project must have the note it is named after."""
from __future__ import annotations

from .base import PROJECT, Gate, Subject


def check(subject: Subject) -> str | None:
    if subject.locations.project_note(subject.name).is_file():
        return None
    return f"project note {subject.name}.md missing"


GATE = Gate("note", PROJECT, "the project's own note exists", check)

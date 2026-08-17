"""The project should have an Environment note.

Created by the project template alongside the note, the glossary and the first
ADR, so this only fires on a hand-made project or after a deletion -- which is
exactly the kind of rule someone will want to switch off.
"""
from __future__ import annotations

from .base import PROJECT, Gate, Subject


def check(subject: Subject) -> str | None:
    if subject.locations.environment(subject.name).is_file():
        return None
    return "Environment.md missing"


GATE = Gate("environment", PROJECT, "the project has an Environment note", check)

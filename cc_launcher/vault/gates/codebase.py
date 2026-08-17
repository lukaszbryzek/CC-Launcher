"""There must be code to launch in."""
from __future__ import annotations

from ...paths import short_path
from .base import PROJECT, Gate, Subject


def check(subject: Subject) -> str | None:
    if not subject.company:
        return None
    where = subject.locations.codebase(subject.company, subject.name)
    if where.is_dir():
        return None
    # The path that was actually looked at. The reference wrote a literal
    # "~/Projects/..." into this sentence, which was true only while the
    # projects root was hardcoded; with it configurable, the message would name
    # a place the launcher never checked -- the worst possible hint.
    return f"codebase {short_path(where)} not found"


GATE = Gate("codebase", PROJECT, "the codebase is where it should be", check)

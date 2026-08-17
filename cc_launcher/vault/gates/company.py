"""The note must say which company the project belongs to."""
from __future__ import annotations

from ..frontmatter import strip_wikilink
from .base import PROJECT, Gate, Subject


def check(subject: Subject) -> str | None:
    if subject.company:
        return None
    # company_of refuses a value that is not a plain name (separators, '..',
    # control characters), because it becomes a path component. Saying "no
    # company" about a note that visibly has one would send the user hunting
    # in the wrong place, so the rejected value is named instead.
    raw = strip_wikilink(subject.frontmatter.get("text_company")
                         or subject.frontmatter.get("company"))
    if raw:
        return f"'company' is not a plain codename: {raw!r}"
    return "no 'company' in frontmatter"


GATE = Gate("company", PROJECT, "the note names a company", check)

"""The company folder must hold an About_Me, which the loaders import."""
from __future__ import annotations

from .base import PROJECT, Gate, Subject


def check(subject: Subject) -> str | None:
    if not subject.company:
        return None
    if not subject.locations.company_dir(subject.company).is_dir():
        return None          # already covered by the company_dir rule
    if subject.locations.company_about_me(subject.company).is_file():
        return None
    return f"About_Me missing in Companies/{subject.company}"


GATE = Gate("about_me", PROJECT, "the company folder has an About_Me", check)

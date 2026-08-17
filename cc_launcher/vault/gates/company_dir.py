"""That company must have a folder in the vault."""
from __future__ import annotations

from .base import PROJECT, Gate, Subject


def check(subject: Subject) -> str | None:
    # Unanswerable without a company, which is not the same as passing: the
    # missing company is already reported by its own rule, and inventing
    # "Companies/None not found" would only add noise to it.
    if not subject.company:
        return None
    if subject.locations.company_dir(subject.company).is_dir():
        return None
    return f"Companies/{subject.company} not found"


GATE = Gate("company_dir", PROJECT, "that company has a folder", check)

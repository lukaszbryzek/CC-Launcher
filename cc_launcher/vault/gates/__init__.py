"""The readiness rules, one module each, applied in the order listed here.

A rule is a file: its module name is its key, and its key is what switches it
off. Adding one means writing <key>.py and naming it below; the order rules run
in, and so the order their messages appear in, is this list and nothing else.

Importing them explicitly rather than discovering them keeps that order visible
and reviewable. Auto-discovery would sort them by filename and hide the decision.
"""
from __future__ import annotations

from ..locations import Locations
from . import (
    about_me,
    codebase,
    company,
    company_dir,
    conventions,
    environment,
    note,
    projects_dir,
)
from .base import PROJECT, VAULT, Gate, Subject, company_of

__all__ = [
    "PROJECT", "VAULT", "Gate", "Subject", "company_of",
    "GATES", "by_scope", "project_gaps", "vault_problems",
]

# Order matters twice over: rules run in it, and gaps are reported in it. The
# project rules go outside-in -- does the note exist, does it name a company,
# does that company exist, does it have an About_Me -- so a reader meets the
# causes before the consequences.
GATES: tuple[Gate, ...] = (
    note.GATE,
    company.GATE,
    company_dir.GATE,
    about_me.GATE,
    codebase.GATE,
    environment.GATE,
    projects_dir.GATE,
    conventions.GATE,
)


def by_scope(scope: str, disabled: frozenset[str] = frozenset()) -> tuple[Gate, ...]:
    return tuple(g for g in GATES if g.scope == scope and g.key not in disabled)


def project_gaps(subject: Subject,
                 disabled: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """Everything wrong with one project, in rule order.

    Every rule runs. A missing note also means a missing company, and both are
    reported: they are two separate things to go and fix, and deciding which one
    the reader "really" needs is not this function's call.
    """
    found = (gate.check(subject) for gate in by_scope(PROJECT, disabled))
    return tuple(gap for gap in found if gap)


def vault_problems(locations: Locations,
                   disabled: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """What is wrong with the vault itself, said once.

    Kept apart from the per-project gaps deliberately. The reference appended
    the missing-Conventions sentence to every project, so one absent file
    emptied the READY pane and filled the other one with N copies of the same
    line -- burying the single real cause under its own repetitions.
    """
    found = (gate.check(locations) for gate in by_scope(VAULT, disabled))
    return tuple(problem for problem in found if problem)

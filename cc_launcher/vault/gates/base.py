"""What every gate is made of.

Separate from the package's __init__ so a gate module can import these without
importing the registry that imports it -- the same reason platform/base.py
exists one directory up.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Mapping, TypeVar

from ..frontmatter import strip_wikilink
from ..locations import Locations

PROJECT = "project"   # asked once per project
VAULT = "vault"       # asked once for the whole vault

T = TypeVar("T")


@dataclass(frozen=True)
class Subject:
    """One project, as much as is known before the gates have run."""

    locations: Locations
    name: str
    # A Mapping by declaration: gates report on the frontmatter, they do not
    # edit it -- the same shallow-freeze rule model.py states for its tuples.
    frontmatter: Mapping
    company: str | None


@dataclass(frozen=True)
class Gate(Generic[T]):
    """One rule.

    `key` is the stable name used to switch the rule off, and it matches the
    module the rule lives in -- so the answer to "where does this message come
    from" is the message's own key with .py after it.

    Typed by what it checks: PROJECT gates take a Subject and VAULT gates take
    a Locations, and the parameter lets the type checker enforce what the scope
    string alone can only label.
    """

    key: str
    scope: str
    summary: str
    check: Callable[[T], str | None]


def valid_component(value: str) -> bool:
    """True when the value is safe to use as a single path component.

    pathlib restarts a join on an absolute component and happily walks `..`,
    so a frontmatter value that is anything but a plain name would send the
    gates -- and the launcher's chdir -- outside the configured roots. The name
    test rejects separators, drives and absolutes; '.' and '..' pass it and are
    named outright; isprintable keeps control characters out of the generated
    loaders.
    """
    if not value or value in (".", ".."):
        return False
    return Path(value).name == value and value.isprintable()


def company_of(frontmatter: Mapping) -> str | None:
    """The company codename a project belongs to.

    text_company holds the plain codename and is the real source. `company`
    holds a wikilink to the company note and is read only as a fallback for
    notes written before the split -- through strip_wikilink, so it at least
    yields a name rather than "[[Algotech Polska]]" with the brackets attached.

    A value that is not a single path component is treated as absent: the
    codename becomes Companies/<codename> and <projects>/<codename>/<name>,
    and following a path-shaped one would aim every check somewhere else
    entirely. The company gate names the rejected value in its gap.
    """
    for key in ("text_company", "company"):
        value = strip_wikilink(frontmatter.get(key))
        if value and valid_component(value):
            return value
    return None

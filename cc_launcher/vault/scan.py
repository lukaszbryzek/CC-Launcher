"""One walk over the vault, producing everything the picker needs.

The expensive part is reading notes off disk, so it happens once: every
project's frontmatter is loaded up front, and resolving a parent afterwards is a
dictionary lookup rather than a second read of a file already in hand.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .frontmatter import first_scalar, read_frontmatter, strip_wikilink
from .gates import PROJECT, Subject, company_of, project_gaps, vault_problems
from .locations import Locations
from .model import Entry


@dataclass(frozen=True)
class Scan:
    """What one walk found.

    The vault's own problems are kept apart from the projects' gaps, because
    they are a different kind of news: one says "this project is not ready", the
    other says "the vault is not what I expected", and folding the second into
    the first is what made a single missing file look like every project being
    broken.
    """

    entries: tuple[Entry, ...]
    problems: tuple[str, ...]

    @property
    def ready(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.ready)

    @property
    def incomplete(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if not e.ready)


def _text(frontmatter: dict, key: str) -> str:
    # Through first_scalar: str() on a list-valued property renders its repr,
    # the exact failure strip_wikilink's docstring records as fixed -- the
    # display fields get the same cure, or a note's List-typed `name` shows as
    # "['Foo']" in the preview pane.
    scalar = first_scalar(frontmatter.get(key))
    return "" if scalar is None else str(scalar).strip()


def scan(locations: Locations, disabled: frozenset[str] = frozenset()) -> Scan:
    """Read the vault and grade every project in it."""
    problems = vault_problems(locations, disabled)

    root = locations.vault_projects
    try:
        directories = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        # Already described by the projects_dir rule, or by whatever stopped the
        # listing. Nothing to add here beyond not crashing.
        return Scan((), problems)

    # Every note read once, before anything is graded.
    notes = {d.name: read_frontmatter(locations.project_note(d.name)) for d in directories}

    entries = []
    for directory in directories:
        name = directory.name
        frontmatter = notes[name]
        company = company_of(frontmatter)

        # A parent that is not itself a project simply has no description to
        # borrow. That is not a gap: nothing in the loaders depends on it.
        parent = strip_wikilink(frontmatter.get("parent_project")) or None
        parent_frontmatter = notes.get(parent, {}) if parent else {}

        entries.append(Entry(
            name=name,
            company=company,
            ov_path=directory,
            codebase=locations.codebase(company, name) if company else None,
            display_name=_text(frontmatter, "name"),
            description=_text(frontmatter, "description"),
            parent=parent,
            parent_description=_text(parent_frontmatter, "description"),
            # Proxied, not handed over: Subject promises a read-only Mapping,
            # and this dict is shared with the notes cache above.
            gaps=project_gaps(Subject(locations, name, MappingProxyType(frontmatter), company),
                              disabled),
        ))
    return Scan(tuple(entries), problems)

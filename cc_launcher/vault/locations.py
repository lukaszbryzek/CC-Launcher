"""Where everything lives, derived once from the settings.

Path arithmetic and nothing else. Whether any of these exist is a separate
question, asked by the readiness gates -- keeping the two apart is what lets a
missing directory be reported as a gap rather than crashing the scan.

The reference implementation kept these as module constants computed at import
from Path.home(). They are a value built from Settings here instead, because the
vault root is now configurable: a constant would freeze whatever the home
directory was when the module first loaded, and a test could not point at a
sample vault without reaching into the module's globals.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Settings


@dataclass(frozen=True)
class Locations:
    """The two configured roots, and everything reachable from them."""

    vault: Path
    projects: Path

    # --- inside the vault ----------------------------------------------------

    @property
    def vault_projects(self) -> Path:
        return self.vault / "Projects"

    @property
    def vault_companies(self) -> Path:
        return self.vault / "Companies"

    @property
    def conventions(self) -> Path:
        """The vault-wide house rules, imported by the vault loader."""
        return self.vault / "Conventions.md"

    @property
    def shared_about_me(self) -> Path:
        return self.vault / "Templates" / "About_Me_Shared.md"

    # --- one project ---------------------------------------------------------

    def project_dir(self, name: str) -> Path:
        return self.vault_projects / name

    def project_note(self, name: str) -> Path:
        """The note a project is named after: Projects/Foo/Foo.md.

        The directory name is the identifier, and the note repeats it -- so the
        name is passed in rather than being read from anywhere, and the two
        cannot disagree.
        """
        return self.project_dir(name) / f"{name}.md"

    def environment(self, name: str) -> Path:
        return self.project_dir(name) / "Environment.md"

    def glossary(self, name: str) -> Path:
        return self.project_dir(name) / "docs" / "Glossary.md"

    def project_loader(self, name: str) -> Path:
        """The generated per-project CLAUDE.md. Overwritten on every launch."""
        return self.project_dir(name) / ".claude" / "CLAUDE.md"

    # --- one company ---------------------------------------------------------

    def company_dir(self, codename: str) -> Path:
        return self.vault_companies / codename

    def company_about_me(self, codename: str) -> Path:
        return self.company_dir(codename) / "About_Me.md"

    # --- outside the vault ---------------------------------------------------

    def codebase(self, codename: str, name: str) -> Path:
        """Where a project's code is expected: <projects>/<company>/<project>.

        Derived rather than configured per project, which is the whole
        convention: renaming a project or changing its company moves where the
        launcher looks, with nothing else to update.
        """
        return self.projects / codename / name

    @property
    def vault_loader(self) -> Path:
        """The generated vault-wide CLAUDE.md. Overwritten on every launch."""
        return self.vault / ".claude" / "CLAUDE.md"


def from_settings(settings: Settings) -> Locations:
    return Locations(vault=settings.vault_dir, projects=settings.projects_dir)


def current() -> Locations:
    """Locations from the settings file as it stands.

    Falls back to the defaults when the file is missing or unusable, because
    load() always hands back something workable; deciding whether the user needs
    telling about that is the caller's job, not this one's.
    """
    from ..config import load

    return from_settings(load().settings)

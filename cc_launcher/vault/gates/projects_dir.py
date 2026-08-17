"""The vault must have the folder the scan walks."""
from __future__ import annotations

from ...paths import short_path
from ..locations import Locations
from .base import VAULT, Gate


def check(locations: Locations) -> str | None:
    # Without it there is nothing to list, and the reference simply returned an
    # empty list -- leaving a blank pane and no clue whether the vault is empty
    # or the path is wrong.
    if locations.vault_projects.is_dir():
        return None
    return f"{short_path(locations.vault_projects)} not found"


GATE = Gate("projects_dir", VAULT, "the vault has a Projects folder", check)

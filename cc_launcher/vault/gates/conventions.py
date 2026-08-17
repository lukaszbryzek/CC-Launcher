"""The vault must have its house rules, which the vault-wide loader imports."""
from __future__ import annotations

from ...paths import short_path
from ..locations import Locations
from .base import VAULT, Gate


def check(locations: Locations) -> str | None:
    if locations.conventions.is_file():
        return None
    return f"{short_path(locations.conventions)} missing"


GATE = Gate("conventions", VAULT, "the vault has its Conventions note", check)

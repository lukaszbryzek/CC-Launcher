"""Linux.

Identical to POSIX today, and the XDG defaults it inherits are the native ones
here rather than a compromise.
"""
from __future__ import annotations

from .base import Posix


class Linux(Posix):
    name = "linux"

    def _python_globs(self) -> list[str]:
        return super()._python_globs() + ["/usr/local/python*/bin", "/opt/python*/bin"]

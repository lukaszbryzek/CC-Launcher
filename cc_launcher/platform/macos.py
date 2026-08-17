"""macOS.

Identical to POSIX today. It is a separate class because the divergences are
already known and documented rather than hypothetical: the native cache location
is ~/Library/Caches, not ~/.cache, and /usr/bin/python3 is an xcselect
trampoline rather than an interpreter. Neither is acted on here — moving the
cache would relocate existing installs' state, and interpreter discovery belongs
to the installer.
"""
from __future__ import annotations

from .base import Posix


class MacOS(Posix):
    name = "macos"

    def _python_globs(self) -> list[str]:
        # /opt/homebrew/opt/python@*/libexec/bin is the keg-only directory that
        # holds the unversioned python/python3 links and is not on PATH — the
        # exact place a PATH-only sweep misses.
        return super()._python_globs() + [
            "/opt/homebrew/bin", "/opt/homebrew/opt/python@*/bin",
            "/opt/homebrew/opt/python@*/libexec/bin",
            "/usr/local/opt/python@*/bin", "/usr/local/opt/python@*/libexec/bin",
            "/Library/Frameworks/Python.framework/Versions/*/bin",
            "/Library/Developer/CommandLineTools/usr/bin",
        ]

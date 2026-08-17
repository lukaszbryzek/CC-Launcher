"""Colour, and the rules for when to withhold it."""
from __future__ import annotations
import functools
import os
import re
import sys

from .platform import current

_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "blue": "\033[34m", "cyan": "\033[36m",
}

# Everything C0 except newline and tab, plus DEL. ESC is in the range, which is
# the point: stripping it beheads every CSI/OSC sequence, and whatever printable
# residue remains is just text.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def printable(text: str) -> str:
    """Text with terminal control characters removed; newlines and tabs stay.

    For anything that arrives from the remote and ends up on the terminal.
    Commit messages are printed directly in front of the update-consent prompt,
    and a message carrying ESC can repaint the very screen the user is deciding
    on -- or, via OSC 52, write their clipboard.
    """
    return _CONTROL.sub("", text)


@functools.lru_cache(maxsize=1)
def colour_enabled() -> bool:
    """Colour when a terminal is watching, and never when asked not to.

    NO_COLOR is honoured because it is the cross-tool convention, and TERM=dumb
    because that is what editors and CI set when they cannot render escapes.

    Cached on first use rather than computed at import: enable_ansi() mutates
    the Windows console, and a side effect like that belongs to the first
    paint, not to whoever happens to import this module.
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    if not sys.stdout.isatty():
        return False
    # A POSIX terminal is already able; a Windows console has to be switched
    # into virtual terminal mode first, and may refuse.
    return current().enable_ansi()

def paint(text: str, *styles: str) -> str:
    if not colour_enabled() or not text:
        return text
    return "".join(_ANSI[s] for s in styles) + text + _ANSI["reset"]

"""The colour palettes and which one is active.

Lifted from the reference cc.py, whose palettes are carried over unchanged --
they were tuned and signed off once, and a migration is no place to redecorate.
What is new is resolution by name, because the settings file stores a name and
the configurator picks from a list rather than cycling.

Pure data with an injected style factory, exactly as before: no prompt_toolkit
import lives here, so this module loads on a machine where the TUI dependency
is absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class Theme:
    """A named colour palette, keyed by the `class:*` names the UI paints with.

    The palette is a Mapping by declaration: model.py states the shallow-freeze
    rule -- a mutable container inside a frozen record is the mutability the
    freeze was meant to remove -- and a palette edited in place would poison
    the per-name style cache in ThemeManager.
    """

    name: str
    palette: Mapping[str, str]


# One Dark (Atom) and its light companion, One Light. Both themes define the same
# class names, so no layout code needs to know which one is active.
#
# The light accents are One Light's hues darkened until each clears a 7:1 contrast
# ratio (WCAG AAA) against the surface it actually paints on. They were scaled
# toward black, which preserves the hue, so these stay One Light colours — just
# deeper. Two deliberate exceptions: plain text (#383a42) already measures 10.9:1
# and is left as-is, and `sep` draws the pane divider rather than any text, so it
# keeps its quiet canonical value instead of being forced to a text target.
THEMES: list[Theme] = [
    Theme("dark", {
        "":            "bg:#0c0c0c #d4d4d4",
        "frame.label": "bg:#282c34 #61afef bold",
        "sel":         "bg:#282c34 #e5c07b bold",
        "ok":          "#98c379 bold",
        "warn":        "#e5c07b bold",
        "fail":        "#e06c75",
        "dim":         "#5c6370",
        "sep":         "#3e4452",
        "status":      "bg:#3e4452 #ffffff bold",
        "status.key":  "bg:#3e4452 #e5c07b bold",
        "modal":       "bg:#1c2027 #d4d4d4",
        "modal.title": "bg:#1c2027 #61afef bold",
        "preview.key": "#61afef bold",
        "preview.val": "#d4d4d4",
    }),
    Theme("light", {
        "":            "bg:#fafafa #383a42",
        "frame.label": "bg:#e5e5e6 #26478f bold",
        "sel":         "bg:#e5e5e6 #634401 bold",
        "ok":          "#2f5f2f bold",
        "warn":        "#744f01 bold",
        "fail":        "#94382f",
        "dim":         "#4c4c50",
        "sep":         "#d3d3d4",
        "status":      "bg:#d3d3d4 #24292f bold",
        "status.key":  "bg:#d3d3d4 #553a01 bold",
        "modal":       "bg:#eaeaeb #383a42",
        "modal.title": "bg:#eaeaeb #274994 bold",
        "preview.key": "#2c52a5 bold",
        "preview.val": "#383a42",
    }),
]

DEFAULT = THEMES[0].name


def names() -> list[str]:
    """Every theme name, in the order the UI should offer them."""
    return [theme.name for theme in THEMES]


def find(name: str) -> Theme | None:
    """The theme with this name, or None.

    Case-insensitively, because the name may have been typed into the settings
    file by hand and "Dark" is not a different theme from "dark".
    """
    wanted = (name or "").strip().lower()
    for theme in THEMES:
        if theme.name.lower() == wanted:
            return theme
    return None


class ThemeManager:
    """Holds the available themes and tracks which one is active.

    `style_factory` (i.e. `Style.from_dict`) is injected so this class carries no
    prompt_toolkit dependency of its own; built styles are cached per theme name
    because rebuilding one on every render would be wasted work.

    An unrecognised `initial` falls back to the first theme rather than failing.
    This is where the settings layer's promise is kept: it stores whatever name
    it was given without judging it, on the understanding that this decides what
    a name means -- so a hand-edited `theme: mauve` costs you the default, not
    a launcher that will not start.
    """

    def __init__(self, themes: list[Theme],
                 style_factory: Callable[[Mapping[str, str]], Any],
                 initial: str = "") -> None:
        self._themes = themes
        self._factory = style_factory
        self._cache: dict[str, Any] = {}
        self._index = 0
        if initial:
            self.select(initial)

    @property
    def current(self) -> Theme:
        return self._themes[self._index]

    @property
    def style(self) -> Any:
        """The built style object for the active theme (built once, then cached)."""
        theme = self.current
        if theme.name not in self._cache:
            self._cache[theme.name] = self._factory(theme.palette)
        return self._cache[theme.name]

    def select(self, name: str) -> bool:
        """Activate a theme by name. False when there is no such theme.

        The configurator needs this: it offers a list and previews the choice,
        which cycling cannot express.
        """
        wanted = (name or "").strip().lower()
        for index, theme in enumerate(self._themes):
            if theme.name.lower() == wanted:
                self._index = index
                return True
        return False

    def toggle(self) -> None:
        self._index = (self._index + 1) % len(self._themes)

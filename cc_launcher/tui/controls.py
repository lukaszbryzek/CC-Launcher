"""Widgets that prompt_toolkit does not provide.

prompt_toolkit is imported at module level here, unlike everywhere else in this
package, because the class below subclasses one of its types and that has to
happen at definition time. Nothing outside the tui package may import this.
"""
from __future__ import annotations

import textwrap
from typing import Callable

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout.controls import FormattedTextControl

# A pane can be dragged narrower than any sensible reading width. Rather than
# wrap at two characters, stop shrinking and let the text overrun.
MIN_ROOM = 8


class WordWrapped(FormattedTextControl):
    """A `Label: value` line that wraps on word boundaries, hanging-indented.

    prompt_toolkit's own wrap_lines breaks at whichever character lands on the
    pane edge, which cuts words in half -- "bind" became "bin" and "d" on two
    lines. Wrapping therefore has to happen here, and only the renderer knows
    how wide the pane ended up, so the width is captured in create_content and
    the text is folded with textwrap before being handed over as explicit lines.

    The reference defined this class anew inside the function that built each
    row, so six preview fields meant six identical classes. It is parameterised
    instead.
    """

    def __init__(self, label: str, value_of: Callable[[], str],
                 key_style: str = "class:preview.key",
                 value_style: str = "class:preview.val") -> None:
        self.prefix = f" {label}: "
        self.indent = " " * len(self.prefix)
        self.value_of = value_of
        self.key_style = key_style
        self.value_style = value_style
        self.width = 0
        super().__init__(self._render)

    def preferred_width(self, max_available_width: int):
        """No preference, and deliberately without rendering to find one.

        The base class measures by folding the text, which fills this render
        pass's fragment cache before create_content has supplied the real pane
        width -- freezing every value at whatever width the measurement guessed.
        Observed as every field wrapping at eight columns.
        """
        return None

    def create_content(self, width: int, height: int | None = None):
        self.width = width
        return super().create_content(width, height)

    def _render(self) -> FormattedText:
        room = max(MIN_ROOM, self.width - len(self.prefix))
        lines = textwrap.wrap(str(self.value_of()), width=room) or [""]
        parts = [(self.key_style, self.prefix), (self.value_style, lines[0])]
        for line in lines[1:]:
            # Continuation lines start under the value, not at the margin, so a
            # wrapped field still reads as one field.
            parts.append((self.value_style, f"\n{self.indent}{line}"))
        return FormattedText(parts)


def field(label: str, value_of: Callable[[], str], **styles):
    """The control wrapped in a window sized to its own content."""
    from prompt_toolkit.layout.containers import Window

    return Window(WordWrapped(label, value_of, **styles), dont_extend_height=True)

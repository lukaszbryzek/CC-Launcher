"""A scrollable view of the project's history, in the shape of git log.

One line per commit: the day, the short hash, the Conventional Commit type with
its scope, the subject, and any release tag the commit carries. Newest first,
the way git log reads, with a bar on the row being read.
"""
from __future__ import annotations

import textwrap

from ..config import Settings
from ..history import Details, Entry
from . import theme as themes

# Column widths. Fixed, so the subjects line up into a column that the eye can
# run down, rather than each row starting wherever the previous field ended.
DATE_WIDTH = 10
SHA_WIDTH = 7
KIND_WIDTH = 16     # fits refactor(vault); longer kinds are elided, not cut

# Rows the frame and the status bar take, which the list does not get: the
# frame's two borders and the one-line bar beneath it.
CHROME = 3

# Types the changelog gives their own colour; anything else is plain.
ACCENTED = {"feat": "class:ok", "fix": "class:fail", "perf": "class:warn"}


def kind_of(entry: Entry) -> str:
    """`type(scope)` as one field, or a marker for a commit that is neither."""
    change = entry.change
    if not change.type:
        return "-"
    return f"{change.type}({change.scope})" if change.scope else change.type


def clip(text: str, width: int) -> str:
    """`text` cut to width, with an ellipsis so the cut is visible.

    One line per commit is the point of this view, so wrapping would break the
    columns it exists for. What must not happen is a silent cut: a subject that
    simply stops mid-word reads as the whole subject.
    """
    if width <= 1 or len(text) <= width:
        return text
    return text[:width - 1] + "…"


def line(entry: Entry, width: int = 0,
         selected: bool = False) -> list[tuple[str, str]]:
    """One row, as styled fragments, fitted to the pane if its width is known.

    A selected row is painted in one style across its whole width rather than
    keeping its per-field colours. A bar that stops where the text stops is not
    a bar, and colours competing with a highlight make both harder to read.
    """
    kind = clip(kind_of(entry), KIND_WIDTH)
    # In front of the subject, not after it. A warning that arrives once the
    # sentence has been read is not a warning, and trailing it also put it at a
    # different place on every row, where the eye has to hunt for it.
    flag = "BREAKING " if entry.change.breaking else ""
    tail = "".join(f"  {tag}" for tag in entry.tags)

    subject = entry.change.subject
    if width:
        used = (1 + DATE_WIDTH + 1 + SHA_WIDTH + 1 + KIND_WIDTH + 1
                + len(flag) + len(tail))
        subject = clip(subject, max(8, width - used))

    fields = [
        ("class:dim", f" {entry.date:<{DATE_WIDTH}} "),
        ("class:dim", f"{entry.change.sha:<{SHA_WIDTH}} "),
        (ACCENTED.get(entry.change.type, "class:preview.key"), f"{kind:<{KIND_WIDTH}} "),
    ]
    if flag:
        fields.append(("class:fail", flag))
    fields.append(("class:preview.val", subject))
    for tag in entry.tags:
        # Releases are the landmarks in this list, so they are the one thing
        # allowed to interrupt the columns.
        fields.append(("class:sel", f"  {tag}"))

    if not selected:
        return fields
    text = "".join(part for _, part in fields)
    if width:
        text = text.ljust(width)[:width]
    return [("class:sel", text)]


def detail_text(found: Details | None, width: int) -> list[tuple[str, str]]:
    """One commit in full, as styled fragments.

    Everything the list has no room for: the time as well as the day, who wrote
    it, what it touched, the body in full, and a link to the commit on GitHub.
    """
    if found is None:
        return [("class:fail", " could not read this commit\n")]

    room = max(20, width - 2)

    def field(label: str, value: str) -> list[tuple[str, str]]:
        return [("class:preview.key", f" {label:<10}"), ("class:preview.val", f"{value}\n")]

    parts: list[tuple[str, str]] = [("class:modal.title", f" {clip(found.subject, room)}\n\n")]
    parts += field("commit", found.sha)
    parts += field("author", found.author)
    parts += field("date", found.when)
    if found.tags:
        parts += field("released", ", ".join(found.tags))
    changed = (f"{found.files} file{'s' if found.files != 1 else ''}, "
               f"+{found.insertions} -{found.deletions}")
    parts += field("changed", changed if found.files else "nothing (empty commit)")
    if found.url:
        parts += field("url", found.url)

    if found.body:
        parts.append(("", "\n"))
        for paragraph in found.body.split("\n\n"):
            # Reflowed rather than shown as written: the pane is not the width
            # the message was wrapped to, so its own line breaks would leave
            # ragged half-lines all the way down.
            folded = textwrap.wrap(" ".join(paragraph.split()), width=room) or [""]
            for row in folded:
                parts.append(("class:preview.val", f" {row}\n"))
            parts.append(("", "\n"))
    return parts


def run_pager(entries: tuple[Entry, ...], settings: Settings, note: str = "") -> None:
    """Show the history until q. Returns nothing: this only reads."""
    from prompt_toolkit import Application
    from prompt_toolkit.application import get_app
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.layout.containers import (
        ConditionalContainer, Float, FloatContainer, HSplit, Window,
    )
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension as D
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.styles import DynamicStyle, Style
    from prompt_toolkit.widgets import Frame

    theme = themes.ThemeManager(themes.THEMES, Style.from_dict, initial=settings.theme)
    cursor = [0]
    top = [0]
    width = [100]     # the renderer reports the real one; only the cut depends on it
    opened: list = [None]   # the commit whose details are on screen, if any

    def rows() -> int:
        """How many commits fit.

        Taken from the terminal rather than learned from create_content. A
        control only finds out its height by being drawn, so the first paint
        used whatever default had been guessed -- twenty rows in a window with
        room for twenty-seven, until any keypress redrew it correctly.
        """
        try:
            return max(1, get_app().output.get_size().rows - CHROME)
        except Exception:
            return 20

    def reveal() -> None:
        """Scroll the least amount that puts the cursor back on screen."""
        if not entries:
            cursor[0] = top[0] = 0
            return
        height = rows()
        cursor[0] = max(0, min(cursor[0], len(entries) - 1))
        top[0] = min(top[0], cursor[0])
        top[0] = max(top[0], cursor[0] - height + 1)
        top[0] = max(0, min(top[0], max(0, len(entries) - height)))

    def body() -> FormattedText:
        if not entries:
            return FormattedText([("class:dim", "  (no history to show)\n")])
        reveal()
        parts: list[tuple[str, str]] = []
        for index in range(top[0], min(top[0] + rows(), len(entries))):
            parts.extend(line(entries[index], width[0], selected=index == cursor[0]))
            parts.append(("", "\n"))
        return FormattedText(parts)

    class Sized(FormattedTextControl):
        """Learns the pane width, which decides where a subject is cut.

        preferred_width answers with no preference and, crucially, without
        rendering to find one: the base class measures by folding the text,
        which fills this pass's fragment cache at a width nobody chose. That
        showed up as rows built for a wider pane than they landed in, hard-cut
        with no ellipsis.
        """

        def preferred_width(self, max_available_width):
            return None

        def create_content(self, content_width, content_height=None):
            width[0] = content_width
            return super().create_content(content_width, content_height)

    def details_body() -> FormattedText:
        return FormattedText(detail_text(opened[0], max(40, width[0] - 8)))

    def status() -> FormattedText:
        if opened[0] is not None:
            parts = [("class:status", "  ")]
            for key, description in (("q", "back"),):
                parts.append(("class:status.key", key))
                parts.append(("class:status", f" {description}    "))
            return FormattedText(parts)
        position = f"{cursor[0] + 1} of {len(entries)}" if entries else "empty"
        parts = [("class:status", f"  {position}    ")]
        for key, description in (("↑/↓", "move"), ("pgup/pgdn", "page"),
                                 ("home/end", "ends"), ("⏎", "details"), ("q", "close")):
            parts.append(("class:status.key", key))
            parts.append(("class:status", f" {description}    "))
        return FormattedText(parts)

    def title() -> str:
        return f" History{'  ·  ' + note if note else ''} "

    def move(delta: int) -> None:
        cursor[0] += delta
        reveal()

    kb = KeyBindings()
    in_list = Condition(lambda: opened[0] is None)
    in_details = Condition(lambda: opened[0] is not None)

    @kb.add("enter", filter=in_list)
    def _(event):
        from ..history import details
        if entries:
            # Read now rather than with the list: a hundred commits are listed
            # and almost none are opened, so the body and the diff stat would be
            # a hundred reads to serve one.
            opened[0] = details(entries[cursor[0]].change.sha)

    @kb.add("q", filter=in_details)
    @kb.add("Q", filter=in_details)
    @kb.add("enter", filter=in_details)
    @kb.add("escape", filter=in_details)
    def _(event):
        opened[0] = None

    @kb.add("up", filter=in_list)
    def _(event):
        move(-1)

    @kb.add("down", filter=in_list)
    def _(event):
        move(1)

    @kb.add("pageup", filter=in_list)
    def _(event):
        move(-rows())

    @kb.add("pagedown", filter=in_list)
    def _(event):
        move(rows())

    @kb.add("home", filter=in_list)
    def _(event):
        cursor[0] = 0
        reveal()

    @kb.add("end", filter=in_list)
    def _(event):
        cursor[0] = len(entries) - 1
        reveal()

    @kb.add("q", filter=in_list)
    @kb.add("Q", filter=in_list)
    @kb.add("c-c")
    def _(event):
        event.app.exit()

    listing = HSplit([
        Frame(Window(Sized(body)), title=title, style="class:frame", height=D(weight=1)),
        Window(FormattedTextControl(status), height=1, style="class:status"),
    ])
    detail = ConditionalContainer(
        Frame(Window(FormattedTextControl(details_body), wrap_lines=True),
              title="Commit", style="class:modal"),
        filter=in_details,
    )
    layout = Layout(FloatContainer(content=listing, floats=[
        Float(content=detail, left=4, right=4, top=2, bottom=3)]))
    Application(layout=layout, key_bindings=kb,
                style=DynamicStyle(lambda: theme.style), full_screen=True).run()

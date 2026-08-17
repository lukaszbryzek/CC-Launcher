"""The picker: two panes, a preview, and the modal that starts a session.

The screen the whole project exists for. Everything it draws was worked out
before it ran -- the scan, the ordering, the readiness gaps -- so moving the
selection is a redraw and nothing more.

It never launches anything itself. Choosing a project ends the application and
hands the choice back, because replacing this process while prompt_toolkit still
owns the terminal would leave the alternate screen up and the terminal in a
state nobody restored.
"""
from __future__ import annotations

from dataclasses import replace

from ..config import Settings, save
from ..launch import MODES, Mode
from ..paths import short_path
from ..vault.locations import Locations
from ..vault.model import Entry
from . import theme as themes
from .state import State


def run_picker(locations: Locations,
               settings: Settings) -> tuple[Entry, Mode] | None:
    """Show the picker. Returns the chosen project and mode, or None."""
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import (
        ConditionalContainer, Float, FloatContainer, HSplit, VSplit, Window,
    )
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension as D
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.styles import DynamicStyle, Style
    from prompt_toolkit.widgets import Frame

    from .controls import field

    state = State(locations)
    theme = themes.ThemeManager(themes.THEMES, Style.from_dict, initial=settings.theme)
    chosen: list[tuple[Entry, Mode] | None] = [None]
    mode_index = [0]
    picking = [False]          # is the launch modal open
    notice = [""]              # one line of bad news for the status bar

    # --- the panes -----------------------------------------------------------

    def ready_text() -> FormattedText:
        if not state.ready:
            return FormattedText([("class:dim", "  (no ready projects)\n")])
        parts = []
        # Once, not per row: State.index is a linear scan, and asking it inside
        # the loop makes this pane O(n²) per keystroke as the vault grows.
        selected = state.index
        for position, row in enumerate(state.ready):
            style = "class:sel" if position == selected else "class:ok"
            parts.append((style, f"  {'  ' * row.depth}{row.entry.label}\n"))
        return FormattedText(parts)

    def incomplete_text() -> FormattedText:
        parts: list[tuple[str, str]] = []
        # The vault's own problems first: one missing Conventions.md is a fact
        # about the vault, not about eight projects, and it belongs above them.
        for problem in state.problems:
            parts.append(("class:fail", f"  ! {problem}\n"))
        if state.problems and state.incomplete:
            parts.append(("", "\n"))
        if not state.incomplete:
            if not state.problems:
                parts.append(("class:dim", "  (none)\n"))
            return FormattedText(parts)
        for entry in state.incomplete:
            parts.append(("class:warn", f"  [{entry.company or '?'}] {entry.name}\n"))
            for gap in entry.gaps:
                parts.append(("class:fail", f"      - {gap}\n"))
        return FormattedText(parts)

    # --- the preview ---------------------------------------------------------

    def current() -> Entry | None:
        return state.selected

    def value(fn, empty="—"):
        def read() -> str:
            entry = current()
            return fn(entry) if entry else empty
        return read

    has_parent = Condition(lambda: (entry := current()) is not None
                           and entry.parent is not None)

    preview_rows = [
        # `Type` is a property line rather than a framed box: ADR-0002 traded
        # the per-field frames away for the room they cost.
        field("Type", value(lambda e: "Child" if e.parent else "Parent")),
        field("Name", value(lambda e: e.title)),
        field("Description", value(lambda e: e.description or "—",
                                   empty="(nothing to preview)")),
        # Only a child has a parent to describe, so the line is absent entirely
        # rather than sitting there showing a dash.
        ConditionalContainer(
            field("Parent Description", value(lambda e: e.parent_description or "—")),
            filter=has_parent),
        field("OV", value(lambda e: short_path(e.ov_path))),
        field("Codebase", value(lambda e: short_path(e.codebase) if e.codebase else "—")),
        Window(),          # spacer, absorbing whatever height is left
    ]

    # --- chrome --------------------------------------------------------------

    def status_text() -> FormattedText:
        items: tuple[tuple[str, str], ...]
        if picking[0]:
            items = (("↑/↓", "pick mode"), ("⏎", "launch"), ("t", "theme"), ("q", "back"))
        else:
            items = (("↑/↓", "move"), ("⏎", "launch"), ("t", "theme"),
                     ("r", "rescan"), ("q", "quit"))
        parts = [("class:status", "  ")]
        for key, description in items:
            parts.append(("class:status.key", key))
            parts.append(("class:status", f" {description}    "))
        if notice[0]:
            parts.append(("class:fail", f"  {notice[0]}"))
        return FormattedText(parts)

    def modal_text() -> FormattedText:
        entry = current()
        parts = [("class:modal.title", f" Launch: {entry.name if entry else ''} \n\n")]
        for position, mode in enumerate(MODES):
            style = "class:sel" if position == mode_index[0] else "class:modal"
            parts.append((style, f"  {mode.label:<11} {mode.description}\n"))
        parts.append(("class:dim", "\n  ⏎ launch    q cancel\n"))
        return FormattedText(parts)

    # --- keys ----------------------------------------------------------------

    in_list = Condition(lambda: not picking[0])
    in_modal = Condition(lambda: picking[0])
    kb = KeyBindings()

    @kb.add("up", filter=in_list)
    def _(event):
        state.move(-1)

    @kb.add("down", filter=in_list)
    def _(event):
        state.move(1)

    @kb.add("enter", filter=in_list)
    def _(event):
        if state.ready:
            mode_index[0] = 0
            picking[0] = True

    @kb.add("r", filter=in_list)
    @kb.add("c-r", filter=in_list)
    def _(event):
        state.refresh()

    @kb.add("q", filter=in_list)
    @kb.add("Q", filter=in_list)
    @kb.add("c-c")
    def _(event):
        event.app.exit()

    # Unfiltered: the theme can be flipped from the list and from the modal
    # alike. Safe as a bare letter because nothing here takes typed text.
    @kb.add("t")
    @kb.add("T")
    def _(event):
        theme.toggle()
        # Remembered, so the choice survives the session. A no-op write is
        # skipped by save(), so flipping back and forth leaves no backups.
        # save() reports failure as a string, and swallowing it meant the theme
        # silently reverted next launch -- the status bar is where one line of
        # bad news belongs.
        complaint = save(replace(settings, theme=theme.current.name))
        notice[0] = f"theme not saved — {complaint}" if complaint else ""

    @kb.add("up", filter=in_modal)
    def _(event):
        mode_index[0] = (mode_index[0] - 1) % len(MODES)

    @kb.add("down", filter=in_modal)
    def _(event):
        mode_index[0] = (mode_index[0] + 1) % len(MODES)

    @kb.add("enter", filter=in_modal)
    def _(event):
        entry = current()
        if entry is not None:
            chosen[0] = (entry, MODES[mode_index[0]])
        event.app.exit()

    @kb.add("q", filter=in_modal)
    @kb.add("Q", filter=in_modal)
    def _(event):
        picking[0] = False

    # --- layout --------------------------------------------------------------

    # READY sizes to its own row count and PREVIEW takes the remainder, so the
    # boundary between them holds still while the selection moves. Sizing
    # PREVIEW to its contents instead made the split jump three rows whenever a
    # child was highlighted.
    ready_pane = Frame(Window(FormattedTextControl(ready_text), dont_extend_height=True),
                       title="READY", style="class:frame")
    preview_pane = Frame(HSplit(preview_rows, height=D(weight=1)),
                         title="PREVIEW", style="class:frame")
    # wrap_lines, because every line in this pane is a sentence about something
    # being wrong and the informative half is at the end. Clipped, a vault
    # problem reads "! /var/folders/1m/3sdw6sk17b3dkr..." and never reaches the
    # word "missing" -- observed, with the filename cut off entirely.
    incomplete_pane = Frame(Window(FormattedTextControl(incomplete_text), wrap_lines=True),
                            title="INCOMPLETE (gaps)", style="class:frame")

    body = HSplit([
        VSplit([
            HSplit([ready_pane, preview_pane], width=D(weight=1)),
            Window(width=1, char="│", style="class:sep"),
            HSplit([incomplete_pane], width=D(weight=1)),
        ]),
        Window(FormattedTextControl(status_text), height=1, style="class:status"),
    ])
    modal = ConditionalContainer(
        Frame(Window(FormattedTextControl(modal_text), width=D(min=46)),
              title="Launch mode", style="class:modal"),
        filter=in_modal,
    )

    # mouse_support is deliberately off: nothing here responds to a click, and
    # turning it on only takes the terminal's own text selection away.
    Application(layout=Layout(FloatContainer(content=body, floats=[Float(content=modal)])),
                key_bindings=kb, style=DynamicStyle(lambda: theme.style),
                full_screen=True).run()
    return chosen[0]

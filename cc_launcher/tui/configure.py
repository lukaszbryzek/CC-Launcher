"""The configurator: the screen a first run lands on.

Step 5.1 is the frame and the way out of it. The three values are shown but not
yet editable; the fields, their validation, the theme picker and the save
confirmation each arrive in their own step. What is settled here is the shape --
a draft that the screen renders and the later steps mutate, and a single exit
point that answers "these settings" or "nothing".

prompt_toolkit is imported inside the function, the way the rest of this package
does it, so importing the module costs nothing on a machine that never opens the
screen.
"""
from __future__ import annotations

from ..config import Settings, config_file, render
from ..paths import short_path
from . import browse
from . import theme as themes

# The rows, in the order they are shown and navigated. Index order matters: it
# is what the cursor counts through and what body() maps onto the draft.
ROWS = ("Vault", "Projects", "Theme")

# How much room a value gets before it is elided. Fixed, so the verdict column
# stays put no matter what the values are.
VALUE_WIDTH = 38

# The confirmation names a file; this is how much of it fits on one line.
CONFIRM_WIDTH = 56

# What leaving the screen can mean. Yes first, because having just configured
# something, saving it is the answer being reached for.
SAVE_CHOICES = (("Yes", "write it and quit"),
                ("No", "quit without saving"),
                ("Cancel", "back to the settings"))


def fit(text: str, width: int) -> str:
    """`text` shortened from the left to `width`, with a leading ellipsis.

    From the left because the end of a path is the part that identifies it:
    ".../Projects/OV" says more than "/Users/somebody/Docum...". Without this a
    long path runs straight into the column beside it -- observed, with the tick
    printed hard against the last character of the path and no space between.
    """
    if len(text) <= width:
        return text
    return "…" + text[-(width - 1):]


class Draft:
    """The values as the screen holds them: text, not paths.

    Editing happens in the spelling the user typed and the file stores, so the
    draft keeps strings and only becomes Settings on the way out. Turning "~/x"
    into an absolute path on every keystroke would make the field fight whoever
    is typing in it.
    """

    def __init__(self, settings: Settings) -> None:
        self.vault_dir = short_path(settings.vault_dir)
        self.projects_dir = short_path(settings.projects_dir)
        self.theme = settings.theme

    def to_settings(self) -> Settings:
        """The draft as Settings, interpreted by the reader's own rules.

        The three strings are rendered as a settings file and handed to
        parse_settings, rather than expanded again here. Whatever the file would
        mean by a value is exactly what the screen should mean by it, and two
        implementations of that would eventually disagree -- which is the class
        of bug where the configurator shows one path and the launcher uses
        another.
        """
        from ..config import parse_settings, quote_scalar

        settings, _complaint = parse_settings(
            f"vault_dir: {quote_scalar(self.vault_dir)}\n"
            f"projects_dir: {quote_scalar(self.projects_dir)}\n"
            f"theme: {quote_scalar(self.theme)}\n"
        )
        return settings


def run_configurator(settings: Settings | None = None) -> Settings | None:
    """Open the configurator. Returns the chosen settings, or None if cancelled.

    None means "the user backed out" and nothing should be written. It is a
    distinct answer from a Settings that happens to equal the defaults, because
    accepting the defaults is a decision and abandoning the screen is not.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import (
        ConditionalContainer, Float, FloatContainer, HSplit, Window,
    )
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension as D
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.styles import DynamicStyle, Style
    from prompt_toolkit.widgets import Frame

    draft = Draft(settings or Settings())
    theme = themes.ThemeManager(themes.THEMES, Style.from_dict, initial=draft.theme)
    result: list[Settings | None] = [None]
    cursor = [0]            # which row is highlighted
    browser: list = [None]  # the open directory browser, or None
    picking: list = [None]  # the theme being previewed: (index, name to restore)
    saving: list = [None]   # None when not asking; else (choice index, error)

    def row_value(index: int) -> str:
        return (draft.vault_dir, draft.projects_dir, draft.theme)[index]

    def body() -> FormattedText:
        """The three rows, the highlighted one included.

        Values are read through to_settings() for the verdict rather than being
        checked as typed, so what is judged here is the path the launcher would
        actually use -- a relative entry reports on the default it falls back
        to, not on the text that will never be used.
        """
        resolved = draft.to_settings()
        checks = (resolved.vault_dir, resolved.projects_dir, None)
        parts: list[tuple[str, str]] = []
        for index, label in enumerate(ROWS):
            selected = index == cursor[0]
            parts.append(("class:sel" if selected else "class:dim",
                          f"  {'>' if selected else ' '} "))
            parts.append(("class:sel" if selected else "class:preview.key", f"{label:<10}"))
            parts.append(("class:sel" if selected else "class:preview.val",
                          f" {fit(row_value(index), VALUE_WIDTH):<{VALUE_WIDTH}} "))
            parts.extend(verdict(checks[index]))
            parts.append(("", "\n"))
        return FormattedText(parts)

    def verdict(path) -> list[tuple[str, str]]:
        """Whether a directory setting points at something that exists.

        Only existence is judged here. Whether a directory is plausibly an OV
        vault is a question about the vault's shape, and that belongs to the
        vault layer rather than being guessed at from the UI.
        """
        if path is None:
            return [("", "")]
        if path.is_dir():
            return [("class:ok", "✓ found")]
        if path.exists():
            return [("class:fail", "✗ not a directory")]
        return [("class:fail", "✗ does not exist")]

    def intro() -> FormattedText:
        return FormattedText([
            ("class:dim",
             " CC_Launcher needs to know where your vault and your codebases live.\n"),
        ])

    def status() -> FormattedText:
        if browser[0] is not None:
            keys = (("↑/↓", "move"), ("⏎", "open / choose"),
                    (".", "hidden"), ("q", "back"))
        elif picking[0] is not None:
            keys = (("↑/↓", "preview"), ("⏎", "keep"), ("q", "cancel"))
        elif saving[0] is not None:
            keys = (("↑/↓", "choose"), ("⏎", "confirm"), ("q", "back"))
        else:
            keys = (("↑/↓", "move"), ("⏎", "browse / change"), ("q", "quit"))
        parts = [("class:status", "  ")]
        for key, description in keys:
            parts.append(("class:status.key", key))
            parts.append(("class:status", f" {description}    "))
        return FormattedText(parts)

    # --- the file that would be written --------------------------------------

    def preview_title() -> str:
        return f" {short_path(config_file())} "

    def preview() -> FormattedText:
        """The settings as the file will hold them.

        Rendered by config.render -- the same function save() calls -- so the
        text here is the text that gets written, quoting and ~ form included. A
        preview merely similar to the file would be worse than none: it invites
        trust in a claim nothing checks.

        The file's comment header is skipped. It is four lines of boilerplate,
        identical every time and saying nothing about these settings, and the
        room it costs is better spent on the screen above. It is still written
        to the file; it is just not news.
        """
        parts: list[tuple[str, str]] = []
        for line in render(draft.to_settings()).splitlines():
            if line.startswith("#") or not line.strip():
                continue
            key, sep, value = line.partition(":")
            parts.append(("class:preview.key", f" {key}{sep}"))
            parts.append(("class:preview.val", f"{value}\n"))
        return FormattedText(parts)

    # --- saving --------------------------------------------------------------

    def confirm_text() -> FormattedText:
        parts: list[tuple[str, str]] = [
            ("class:preview.val", f" {fit(short_path(config_file()), CONFIRM_WIDTH)}\n"),
            ("", "\n"),
        ]
        index, error = saving[0]
        for position, (label, description) in enumerate(SAVE_CHOICES):
            selected = position == index
            parts.append(("class:sel" if selected else "class:modal",
                          f" {'>' if selected else ' '} {label:<8}"))
            parts.append(("class:sel" if selected else "class:dim",
                          f"{description}\n"))
        if error:
            # A failure keeps the dialog open. There is nothing to do about a
            # full disk from in here, but being told beats a screen that closes
            # as though it had worked.
            parts.append(("class:fail", f"\n {error}\n"))
        return FormattedText(parts)

    def get_app_exit() -> None:
        from prompt_toolkit.application import get_app
        get_app().exit()

    def do_save() -> None:
        from ..config import save

        chosen = draft.to_settings()
        complaint = save(chosen)
        if complaint:
            index, _ = saving[0]
            saving[0] = (index, complaint)
            return
        # A returned Settings means it is on disk. The dialog named a file, so
        # the function that showed it is the one that must write it -- handing
        # the job back to a caller that might write somewhere else, or not at
        # all, would make the promise on screen untrue.
        result[0] = chosen
        get_app_exit()

    def answer_save() -> None:
        """Act on the highlighted choice."""
        index, _ = saving[0]
        label = SAVE_CHOICES[index][0]
        if label == "Yes":
            do_save()
        elif label == "No":
            saving[0] = None      # result stays None: nothing was written
            get_app_exit()
        else:
            saving[0] = None

    # --- the theme picker ----------------------------------------------------

    def theme_text() -> FormattedText:
        if picking[0] is None:
            return FormattedText([])
        index, _original = picking[0]
        parts: list[tuple[str, str]] = []
        for position, name in enumerate(themes.names()):
            selected = position == index
            parts.append(("class:sel" if selected else "class:preview.val",
                          f" {'>' if selected else ' '} {name}\n"))
        return FormattedText(parts)

    def show_theme(name: str) -> None:
        """Apply a theme to the whole screen and to the draft at once.

        Previewing by repainting everything, rather than by colouring a swatch:
        the question being answered is "do I want to look at this", and only the
        real screen answers it. The draft moves with it so the row and the file
        preview agree with what is on screen -- a preview that showed one theme
        while the file said another would be its own small lie.
        """
        draft.theme = name
        theme.select(name)

    def open_theme_picker() -> None:
        names = themes.names()
        current = draft.theme if draft.theme in names else names[0]
        picking[0] = (names.index(current), draft.theme)

    def close_theme_picker(keep: bool) -> None:
        """Leave the picker, either taking the previewed theme or undoing it."""
        _index, original = picking[0]
        if not keep:
            show_theme(original)
        picking[0] = None

    # --- the directory browser ----------------------------------------------

    BROWSER_ROWS = 12

    def browser_title() -> str:
        return f" {short_path(browser[0].cwd)} " if browser[0] else ""

    def browser_text() -> FormattedText:
        view = browser[0]
        if view is None:
            return FormattedText([])
        parts: list[tuple[str, str]] = []
        first, last = view.window(BROWSER_ROWS)
        if first > 0:
            parts.append(("class:dim", f"    ⋮ {first} more above\n"))
        for position in range(first, last):
            item = view.items[position]
            selected = position == view.index
            if item.kind == browse.USE:
                label, style = "· use this directory", "class:ok"
            elif item.kind == browse.UP:
                label, style = "↰ ..", "class:dim"
            else:
                label, style = f"  {item.label}/", "class:preview.val"
            parts.append(("class:sel" if selected else style,
                          f" {'>' if selected else ' '} {label}\n"))
        remaining = len(view.items) - last
        if remaining > 0:
            parts.append(("class:dim", f"    ⋮ {remaining} more below\n"))
        if view.error:
            parts.append(("class:fail", f"    cannot read this directory: {view.error}\n"))
        return FormattedText(parts)

    def open_browser() -> None:
        """Start browsing from where the current value points.

        From the value rather than from home, so reopening the picker lands
        back where it was last left instead of making the walk again.
        """
        resolved = draft.to_settings()
        start = (resolved.vault_dir, resolved.projects_dir)[cursor[0]]
        browser[0] = browse.Browser(start)

    def take(chosen) -> None:
        """Write a chosen directory back into the draft, in its ~ form."""
        if cursor[0] == 0:
            draft.vault_dir = short_path(chosen)
        else:
            draft.projects_dir = short_path(chosen)
        browser[0] = None

    kb = KeyBindings()
    in_list = Condition(lambda: browser[0] is None and picking[0] is None
                        and saving[0] is None)
    in_browser = Condition(lambda: browser[0] is not None)
    in_theme = Condition(lambda: picking[0] is not None)
    in_save = Condition(lambda: saving[0] is not None)

    # `q` rather than escape, which is too easy to hit by accident. It can be a
    # bare letter only because nothing on this screen takes typed text: the
    # paths are chosen by browsing, not written into a field.
    @kb.add("q", filter=in_list)
    @kb.add("Q", filter=in_list)
    def _(event):
        # Asks rather than leaving. There is no other way out, so this is where
        # the choice between keeping and discarding the work is made.
        saving[0] = (0, "")

    @kb.add("c-c")
    def _(event):
        # The one unconditional exit, from anywhere, saving nothing. ctrl-c has
        # meant that everywhere for decades and should not start negotiating.
        result[0] = None
        event.app.exit()

    @kb.add("up", filter=in_list)
    def _(event):
        cursor[0] = (cursor[0] - 1) % len(ROWS)

    @kb.add("down", filter=in_list)
    def _(event):
        cursor[0] = (cursor[0] + 1) % len(ROWS)

    @kb.add("enter", filter=in_list)
    def _(event):
        if cursor[0] in (0, 1):
            open_browser()
        else:
            open_theme_picker()

    # --- save dialog keys ----------------------------------------------------

    @kb.add("up", filter=in_save)
    @kb.add("down", filter=in_save)
    def _(event):
        index, error = saving[0]
        step = 1 if event.key_sequence[0].key == "down" else -1
        saving[0] = ((index + step) % len(SAVE_CHOICES), error)

    @kb.add("enter", filter=in_save)
    def _(event):
        answer_save()

    @kb.add("q", filter=in_save)
    @kb.add("Q", filter=in_save)
    def _(event):
        # q means "back out of this panel" everywhere else here, so it means
        # Cancel rather than No -- leaving without saving needs to be chosen.
        saving[0] = None

    # --- theme picker keys ---------------------------------------------------

    @kb.add("up", filter=in_theme)
    @kb.add("down", filter=in_theme)
    def _(event):
        names = themes.names()
        index, original = picking[0]
        index = (index + (1 if event.key_sequence[0].key == "down" else -1)) % len(names)
        picking[0] = (index, original)
        show_theme(names[index])

    @kb.add("enter", filter=in_theme)
    def _(event):
        close_theme_picker(keep=True)

    @kb.add("q", filter=in_theme)
    @kb.add("Q", filter=in_theme)
    def _(event):
        close_theme_picker(keep=False)

    # --- browser keys --------------------------------------------------------

    @kb.add("up", filter=in_browser)
    def _(event):
        browser[0].move(-1)

    @kb.add("down", filter=in_browser)
    def _(event):
        browser[0].move(1)

    @kb.add("enter", filter=in_browser)
    def _(event):
        chosen = browser[0].activate()
        if chosen is not None:
            take(chosen)

    @kb.add("left", filter=in_browser)
    @kb.add("backspace", filter=in_browser)
    def _(event):
        # Going up is common enough to deserve a key of its own, rather than
        # only being reachable by finding ".." in the list.
        view = browser[0]
        if view.cwd.parent != view.cwd:
            view.open(view.cwd.parent)

    @kb.add(".", filter=in_browser)
    def _(event):
        browser[0].toggle_hidden()

    @kb.add("q", filter=in_browser)
    @kb.add("Q", filter=in_browser)
    def _(event):
        # Closes the browser only. Leaving the whole screen from in here would
        # discard a walk the user is halfway through by mistake.
        browser[0] = None

    main = HSplit([
        Frame(HSplit([
            Window(FormattedTextControl(intro), height=1),
            Window(height=1),
            Window(FormattedTextControl(body), dont_extend_height=True),
            Window(),
        ], height=D(min=6, weight=1)), title="CC_Launcher settings", style="class:frame"),
        # Sized to the file rather than given a share of the screen: it is as
        # tall as it is, and the settings above take whatever is left.
        Frame(Window(FormattedTextControl(preview), dont_extend_height=True),
              title=preview_title, style="class:frame"),
        Window(FormattedTextControl(status), height=1, style="class:status"),
    ])

    directories = ConditionalContainer(
        Frame(Window(FormattedTextControl(browser_text), width=D(min=52)),
              title=browser_title, style="class:modal"),
        filter=in_browser,
    )
    palettes = ConditionalContainer(
        Frame(Window(FormattedTextControl(theme_text), width=D(min=24)),
              title="Theme", style="class:modal"),
        filter=in_theme,
    )
    confirmation = ConditionalContainer(
        Frame(Window(FormattedTextControl(confirm_text), width=D(min=46)),
              title="Save config?", style="class:modal"),
        filter=in_save,
    )
    layout = Layout(FloatContainer(content=main, floats=[
        Float(content=directories), Float(content=palettes), Float(content=confirmation)]))

    Application(layout=layout, key_bindings=kb,
                style=DynamicStyle(lambda: theme.style),
                full_screen=True).run()
    return result[0]

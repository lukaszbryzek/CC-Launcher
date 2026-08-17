"""User settings: what they are, what they default to, where they live, and how
they are read back.

Writing and the "is this a fresh install" test arrive in their own steps.

There is no environment-variable override for any of this. The file is the
single source of truth: one place to look when a path is wrong, and nothing that
can silently disagree with what the configurator last wrote. The installer's own
variables (CCL_HOME, CCL_ALIAS, CCL_BIN, PYTHON) are a different thing and stay —
they configure the install, and they act before any of this exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # a flat three-key file does not actually need a YAML parser
    yaml = None

from .paths import short_path
from .platform import current

CONFIG_NAME = "config.yaml"

DEFAULT_THEME = "dark"


def default_vault_dir() -> Path:
    return Path.home() / "Projects" / "OV"


def default_projects_dir() -> Path:
    return Path.home() / "Projects"


@dataclass(frozen=True)
class Settings:
    """Everything the configurator asks for, and nothing else.

    Frozen, like Theme and Interpreter elsewhere here: the configurator edits a
    draft of its own and builds one of these at save time, so there is no object
    that is half-edited and still reachable. Use dataclasses.replace to derive a
    changed copy.

    Paths are held expanded and absolute. `~` is a spelling for the file, not a
    value the rest of the program should ever have to think about, so it is
    resolved on the way in and rendered again on the way out.
    """

    vault_dir: Path = field(default_factory=default_vault_dir)
    projects_dir: Path = field(default_factory=default_projects_dir)
    # A plain string rather than a member of the theme list. Validating it here
    # would make configuration depend on the UI layer, and the theme names are
    # the UI's business; the theme layer resolves this and falls back when it
    # does not recognise the name.
    theme: str = DEFAULT_THEME


def config_file() -> Path:
    """Where the settings live.

    Under config_dir() rather than in the install directory, which an update
    resets — settings kept there would be wiped by every upgrade. This also
    means the configurator does not reappear after an update, and that the
    uninstaller has one directory to ask about.

    Not cached: config_dir() reads the environment every call, which is what
    lets a test point the whole thing at a scratch directory.
    """
    return current().config_dir() / CONFIG_NAME


# --- reading ------------------------------------------------------------------

MISSING = "missing"    # no file yet: a fresh install
LOADED = "loaded"      # settings came from the file
INVALID = "invalid"    # a file exists but could not be used


@dataclass(frozen=True)
class ConfigLoad:
    """What reading the file produced.

    Three states rather than an optional Settings, because "no file" and "broken
    file" must not be confused. Treating a broken file as a fresh install would
    send the user into the configurator, which would then overwrite the very
    settings that failed to parse -- silently destroying something recoverable.

    `settings` is always usable: defaults stand in for whatever could not be
    read, so a caller that only wants somewhere to point can ignore the state.
    """

    settings: Settings
    state: str
    detail: str = ""


def _scalar(value: object) -> str | None:
    """A single-line value as text, or None when it is not one.

    Lists and mappings are not paths or theme names, and neither is a blank.
    """
    if value is None or isinstance(value, (list, tuple, dict, set)):
        return None
    text = str(value).strip()
    return text or None


def _as_dir(value: object, fallback: Path) -> Path:
    """A directory setting, expanded, or the default when it is unusable.

    A relative path is rejected rather than resolved. There is no defensible
    base to resolve it against: launch() chdirs into the selected codebase, so
    the working directory is not the same when a path is read and when it is
    used, and anchoring to home would silently turn a typo into a real location.
    """
    text = _scalar(value)
    if text is None:
        return fallback
    path = Path(text).expanduser()
    return path if path.is_absolute() else fallback


def _flat_mapping(text: str) -> dict[str, str]:
    """Top-level `key: value` pairs, for when PyYAML is not installed.

    Enough for a flat three-key file, and the same trick the vault's frontmatter
    reader uses. Trailing comments are deliberately not stripped: `#` is legal in
    a directory name, and losing part of a path is worse than keeping a stray
    comment that will simply fail to be a directory.

    It only has to read what render() writes, which is always single-quoted --
    so the doubled quote that YAML uses for a literal one is undone here. It is
    not a YAML parser and is not trying to be; a hand-written double-quoted
    value gets its quotes removed and its backslash escapes left alone.
    """
    data: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line.startswith((" ", "\t", "-")):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        # Exactly one matching pair, not str.strip: a path may legitimately end
        # in a quote, and strip would eat it along with the delimiter.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote, value = value[0], value[1:-1]
            if quote == "'":
                value = value.replace("''", "'")
        data[key.strip()] = value
    return data


def _yaml_complaint(exc: Exception) -> str:
    """A YAML error as one line the user can act on.

    str() on these runs to seven lines of context and a caret diagram, and its
    first line is the least useful part: "while parsing a flow sequence" says
    nothing about what is wrong or where. PyYAML keeps the two things that
    matter as separate attributes, so they are read directly -- `problem` is the
    actual complaint, `problem_mark` carries the position, and the mark counts
    lines from zero while every editor counts from one.
    """
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    if problem is None:
        return str(exc).splitlines()[0]
    return f"line {mark.line + 1}: {problem}" if mark is not None else str(problem)


def parse_settings(text: str) -> tuple[Settings, str]:
    """Settings from the file's text, plus a complaint when it was not usable.

    An empty complaint means the file was read; anything else is the reason it
    was not. Split from load() so the rules can be exercised without a file,
    exactly as meta.py splits parse_version from local_version.

    A structurally sound file with one nonsense value is not an error: that key
    falls back to its default and the rest is kept. Only a file that cannot
    yield settings at all is a failure.
    """
    if not text.strip():
        # Never written by this program -- the writer is atomic, so a truncated
        # or empty file means something outside it interfered. Say so instead of
        # treating it as a fresh install.
        return Settings(), "the file is empty"

    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return Settings(), f"not valid YAML -- {_yaml_complaint(exc)}"
    else:
        data = _flat_mapping(text)

    if not isinstance(data, dict):
        return Settings(), f"expected a mapping of settings, found {type(data).__name__}"

    # Unknown keys are ignored on purpose: a file written by a newer version
    # must not break an older one.
    return Settings(
        vault_dir=_as_dir(data.get("vault_dir"), default_vault_dir()),
        projects_dir=_as_dir(data.get("projects_dir"), default_projects_dir()),
        theme=_scalar(data.get("theme")) or DEFAULT_THEME,
    ), ""


def load() -> ConfigLoad:
    """Read the settings file, distinguishing absent from broken."""
    path = config_file()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ConfigLoad(Settings(), MISSING)
    except (OSError, UnicodeDecodeError) as exc:
        # Unreadable is not absent -- and undecodable is a kind of unreadable.
        # The file is there and holds something, so overwriting it without a
        # word is the one thing not to do.
        return ConfigLoad(Settings(), INVALID,
                          f"cannot read {path} ({getattr(exc, 'strerror', None) or exc})")

    settings, complaint = parse_settings(text)
    if complaint:
        return ConfigLoad(settings, INVALID, complaint)
    return ConfigLoad(settings, LOADED)


# --- asking about the file ----------------------------------------------------
#
# Two predicates, not one, and they are not each other's negation. A first run
# and a damaged file both mean "no usable settings", but they call for opposite
# treatment: the first should walk into the configurator without comment, the
# second must say what is wrong before anything overwrites it. Anything that has
# to tell those apart -- the startup flow above all -- reads load().state, which
# is the real answer; these two exist so the common questions read as questions
# instead of as comparisons against a magic string.


def is_fresh() -> bool:
    """No settings file at all: this is a first run.

    Answered by looking, not by parsing. A file that exists but cannot be read
    is emphatically not a first run, and is_file() gets that right -- stat needs
    the parent directory, not the file, so an unreadable config still reports as
    present.

    A parent directory that cannot even be stat'ed reads as fresh. The
    configurator will then run and its save will fail with the real reason,
    which is a better place to surface that than here.
    """
    return not config_file().is_file()


def is_configured() -> bool:
    """Settings were read from the file and are usable.

    False covers both a first run and a broken file, so do not read `not
    is_configured()` as "fresh install" -- use is_fresh() for that, or load()
    when the difference matters.
    """
    return load().state == LOADED


# --- writing ------------------------------------------------------------------

HEADER = (
    "# CC_Launcher settings.\n"
    "# Written by the configurator, and safe to edit by hand.\n"
    "# Unlike the generated CLAUDE.md loaders, this file is yours: nothing\n"
    "# overwrites it on launch, and an update does not reset it.\n"
    "\n"
)


def quote_scalar(text: str) -> str:
    """A YAML single-quoted scalar.

    Single quotes rather than double: inside them a backslash is literal, so a
    Windows path survives intact, where "C:\\Users" would be read as an escape
    sequence. The only thing to escape is the quote itself, by doubling it.

    Quoting unconditionally, because a directory name may legally contain ':',
    '#' or a leading character that would otherwise change the value's type.
    """
    return "'" + text.replace("'", "''") + "'"


def render(settings: Settings) -> str:
    """The file's exact text.

    Hand-rendered rather than dumped by PyYAML: this keeps the header comment,
    keeps the keys in the order the configurator asks for them, writes paths in
    their ~ form, and works on a machine with no PyYAML at all -- which the
    reader already tolerates, so the writer must too.
    """
    return HEADER + "".join(
        f"{key}: {quote_scalar(value)}\n" for key, value in (
            ("vault_dir", short_path(settings.vault_dir)),
            ("projects_dir", short_path(settings.projects_dir)),
            ("theme", settings.theme),
        )
    )


BACKUP_FORMAT = "%Y-%m-%d__%H-%M-%S"

BACKUPS_KEPT = 10


def _prune_backups(path: Path) -> None:
    """Keep the newest few backups, delete the rest.

    Every real save leaves one behind, and months of theme toggles are an
    unbounded pile of files differing by one word. Newest-first by name works
    because the stamp sorts lexicographically.
    """
    try:
        backups = sorted(path.parent.glob(f"{path.name}_*"), reverse=True)
        for old in backups[BACKUPS_KEPT:]:
            old.unlink()
    except OSError:
        pass  # pruning is a nicety; never fail a save over it


def backup_name(path: Path, when=None) -> Path:
    """Where the previous settings are kept: config.yaml_2026-08-16__14-30-05.

    The stamp is appended to the whole filename rather than replacing the
    extension, so the original name stays readable and the backups sort next to
    it. Second resolution means two saves in the same second share a name, which
    is the same trade the shell installers make for their own backups.
    """
    from datetime import datetime

    stamp = (when or datetime.now()).strftime(BACKUP_FORMAT)
    return path.with_name(f"{path.name}_{stamp}")


def save(settings: Settings) -> str:
    """Write the settings, keeping a copy of what was there.

    Returns an empty string, or why it failed.

    The write is atomic: a temporary file beside the target, then os.replace.
    Writing in place would mean a crash or a full disk leaves a half-written
    file, and the reader would rightly call that INVALID -- losing settings that
    were fine a moment earlier.

    Three details make it actually atomic rather than nearly so:

    - The temporary file goes in the target's own directory. os.replace across
      filesystems fails with EXDEV, so a temp in /tmp would break on any machine
      whose home is a separate mount.
    - os.replace, never os.rename: on Windows rename refuses when the target
      exists, so an update to an existing config would fail there and nowhere
      else.
    - fsync before the replace. Without it the rename can be durable while the
      data is not, which is exactly how a zero-length config appears after a
      power cut -- the one outcome this is meant to prevent.

    The directory itself is deliberately not fsynced. That would only decide
    whether a completed save survives a crash in the seconds after it, and the
    worst case there is the previous settings, which is a benign state rather
    than a corrupt one.

    mkstemp creates the file 0600 and the replace carries that over, which is
    the right mode for something only its owner reads.
    """
    import os
    import tempfile

    path = config_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"cannot create {path.parent} ({exc.strerror or exc})"

    wanted = render(settings)
    try:
        if path.read_text(encoding="utf-8") == wanted:
            # Nothing to do, and saying so matters: every save keeps a backup,
            # so writing an identical file would leave a copy behind for a
            # change that did not happen. Toggling the theme back and forth
            # would otherwise litter the directory.
            return ""
    except (OSError, UnicodeDecodeError):
        pass

    handle = temp_name = None
    try:
        fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(wanted)
            handle.flush()
            os.fsync(handle.fileno())

        # Copied, not moved: the replace below is what makes the new file
        # appear, and moving the old one first would leave a window with no
        # settings at all. A backup that cannot be written stops the save --
        # overwriting the previous settings without the copy that was promised
        # is worse than not saving, and anything that blocks the copy will
        # almost certainly block the replace a line later anyway.
        if path.exists():
            import shutil
            try:
                shutil.copy2(str(path), str(backup_name(path)))
            except OSError as exc:
                os.unlink(temp_name)
                return f"cannot back up {path} ({exc.strerror or exc}) -- nothing written"

        os.replace(temp_name, str(path))
        _prune_backups(path)
        return ""
    except OSError as exc:
        if temp_name is not None:
            # Leaving these behind would litter the directory one file per
            # failed save, and they are invisible enough to never be noticed.
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        return f"cannot write {path} ({exc.strerror or exc})"

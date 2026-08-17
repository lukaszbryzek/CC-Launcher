"""Starting Claude Code in a project's codebase.

This step is the check that runs before anything is written. Order is the whole
point: the reference regenerated both CLAUDE.md loaders and only then reached
for `claude`, so a machine without it on PATH got a raw FileNotFoundError with
the vault already rewritten -- a failure that left the disk changed and said
nothing useful about why.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from . import brain
from .paths import short_path
from .platform import current
from .vault.locations import Locations
from .vault.model import Entry

CLAUDE = "claude"


def preflight(entry: Entry) -> tuple[str, ...]:
    """Everything that would stop this project launching, or an empty tuple.

    Re-checked here rather than trusted from the scan. The scan can be minutes
    old -- rescanning is a keypress, not a background job -- and a directory
    that has been moved since then would otherwise be discovered by chdir,
    after the loaders were rewritten.
    """
    problems: list[str] = []

    if shutil.which(CLAUDE) is None:
        problems.append(f"`{CLAUDE}` is not on PATH")

    if entry.codebase is None:
        # Reachable whenever a project has no company: the codebase path is
        # derived from the company, so without one there is nothing to derive.
        # The reference passed this straight to chdir, which answered with
        # "TypeError: path should be string, bytes... not NoneType" -- true, and
        # no help at all.
        problems.append(f"{entry.name} has no company, so there is no codebase path")
    elif not entry.codebase.is_dir():
        problems.append(f"codebase {short_path(entry.codebase)} is not there")

    return tuple(problems)


@dataclass(frozen=True)
class Mode:
    """One way of starting Claude Code, as offered in the launch modal."""

    label: str
    description: str
    args: tuple[str, ...] = ()


MODES: tuple[Mode, ...] = (
    Mode("claude", "New session"),
    Mode("claude -c", "Continue the most recent session", ("-c",)),
    Mode("claude -r", "Resume — pick a past session", ("-r",)),
)

# Set so Claude Code loads the CLAUDE.md files found in the --add-dir
# directories; without it the generated loaders are shipped and ignored.
LOADER_ENV = "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD"


def command(locations: Locations, entry: Entry, args: tuple[str, ...] = ()) -> list[str]:
    """The argv Claude Code is started with.

    Both directories are mounted: the vault, for the house rules and the shared
    About_Me, and the project's own folder for its notes. Built separately from
    the launching so it can be read without a process being replaced.
    """
    return [CLAUDE, *args,
            "--add-dir", str(locations.vault),
            "--add-dir", str(entry.ov_path)]


def launch(locations: Locations, entry: Entry, args: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Hand the terminal to Claude Code. Returns only if it could not.

    The order is the fix from the previous step made structural: ask first,
    write second, hand over last. Nothing on disk changes until the launch is
    known to be possible.
    """
    problems = preflight(entry)
    if problems:
        return problems

    codebase = entry.codebase
    if codebase is None:
        # preflight already refused this; repeated so the type checker knows
        # the chdir below never sees None.
        return (f"{entry.name} has no company, so there is no codebase path",)

    # Resolved to an absolute path before the chdir below. Windows resolves a
    # bare name through the *new* current directory ahead of PATH, so a
    # codebase shipping its own claude.exe would be what gets launched. POSIX
    # searches PATH only -- unless PATH contains '.', the same hole spelled
    # differently -- so both get the resolved path.
    argv = command(locations, entry, args)
    resolved = shutil.which(CLAUDE)
    if resolved is None:
        return (f"`{CLAUDE}` left PATH between the check and the launch",)
    argv[0] = resolved

    try:
        brain.write_vault_loader(locations)
        brain.write_project_loader(locations, entry)
    except OSError as exc:
        return (f"could not write the brain loaders ({exc.strerror or exc})",)

    env = dict(os.environ)
    env[LOADER_ENV] = "1"

    try:
        os.chdir(codebase)
    except OSError as exc:
        return (f"could not enter {short_path(codebase)} ({exc.strerror or exc})",)

    try:
        current().exec_and_exit(argv, env)
    except OSError as exc:
        # preflight found `claude` a moment ago, so this is the narrow window
        # where it stopped being runnable -- or it is there but not executable.
        return (f"could not start {CLAUDE} ({exc.strerror or exc})",)
    return ()   # exec_and_exit does not return; here for the type checker

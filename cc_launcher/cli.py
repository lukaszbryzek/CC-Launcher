"""Argument parsing and dispatch."""
from __future__ import annotations
import argparse
import os
import sys

from . import config, net
from .paths import HOME_DIR
from .uninstall import run_uninstall
from .update.apply import set_version
from .update.flow import run_update
from .vcs import describe_version

# Options that are a variant of another one, shown indented beneath it. argparse
# has no notion of this, and a flat list makes --update-nightly and --purge look
# like peers of --update and --uninstall rather than the narrower forms they are.
CHILDREN = {"update_nightly", "purge"}


class Indented(argparse.HelpFormatter):
    """The standard help, with variant options stepped in under their parent.

    The indent goes on the invocation rather than on the finished block, which
    matters for more than tidiness: argparse measures the help column from what
    this method returns, so indenting afterwards shifts a child's description
    two places right of everyone else's and the column stops being a column.
    """

    def _format_action_invocation(self, action):
        text = super()._format_action_invocation(action)
        return f"  {text}" if action.dest in CHILDREN else text


def main() -> int:
    # allow_abbrev is on by default, which makes `--uni` run --uninstall and wipe
    # the install. A destructive command must be spelled out.
    #
    # add_help=False so -h can be added by hand in its alphabetical place:
    # argparse prints options in the order they were added, and that order IS
    # the sort -- everything below is alphabetical by long name, with a variant
    # staying indented under its parent (--update-nightly, --purge).
    parser = argparse.ArgumentParser(prog="ccl", add_help=False, allow_abbrev=False,
                                     formatter_class=Indented,
                                     description="Launch Claude Code from an Obsidian vault.")
    parser.add_argument("--changelog", action="store_true",
                        help="page through the project's history, newest first")
    parser.add_argument("--config", action="store_true",
                        help="open the configurator: vault path, projects path, theme")
    parser.add_argument("-h", "--help", action="help",
                        help="show this help message and exit")
    # Two independent commands rather than a flag modifying another: each names
    # the channel it acts on, and both ignore the six-day interval because both
    # are an explicit request to look now. --set-version shares their group but
    # sorts apart from them; argparse keeps the group's meaning either way.
    channel = parser.add_mutually_exclusive_group()
    channel.add_argument("--set-version", metavar="REF",
                         help="switch to a release (x.y.z) or a commit hash, downgrades included")
    # Two commands, not a flag with a modifier: --purge is what --uninstall is,
    # plus the settings file. Spelling it as its own word means there is no such
    # thing as a --purge that forgot to say what it was purging.
    removal = parser.add_mutually_exclusive_group()
    removal.add_argument("--uninstall", action="store_true",
                         help="remove everything: the clone, the shim, the alias and cached state")
    removal.add_argument("--purge", action="store_true",
                         help="the same, and your settings file with it")
    channel.add_argument("--update", action="store_true",
                         help="check for a newer release and ask before installing it")
    channel.add_argument("--update-nightly", action="store_true",
                         help="check the branch tip and ask before installing it; "
                              "the automatic check never uses this channel")
    parser.add_argument("-v", "--version", action="store_true",
                        help="print the installed version and exit")
    args = parser.parse_args()

    # Anything the user typed is explicit, so it gets the longer network budget.
    if args.update or args.update_nightly or args.set_version:
        net.use_explicit_timeout()

    if args.version:
        print(describe_version())
        return 0

    if args.changelog:
        return show_changelog()

    if args.config:
        return reconfigure()

    if args.set_version:
        return set_version(args.set_version)

    if args.uninstall or args.purge:
        return run_uninstall(purge=args.purge)

    if args.update or args.update_nightly:
        return run_update(ignore_interval=True, nightly=args.update_nightly)[0]

    # Normally free: the interval is a file read, and the network is only
    # touched every CHECK_EVERY_DAYS days. The automatic check follows releases;
    # nightly is opt-in per invocation.
    _, applied = run_update(ignore_interval=False)

    if applied:
        # The files on disk are new; this process still holds the old ones.
        # Hand over to the updated code rather than running a version that no
        # longer exists on disk.
        #
        # The target is the entry script, not this module: cc_launcher/cli.py
        # cannot be run as a file at all, because its own imports are relative
        # and there is no package around it that way.
        entry = HOME_DIR / "ccl.py"
        try:
            os.execv(sys.executable, [sys.executable, str(entry), *sys.argv[1:]])
        except OSError as exc:
            # execv only returns by failing. Saying so beats carrying on with
            # code that was replaced under us.
            print(f"ccl: updated, but could not restart {entry} ({exc}) — "
                  f"start it again yourself", file=sys.stderr)
            return 1

    settings = settle_configuration()
    if settings is None:
        return 0
    return run_picker(settings)


def run_picker(settings: config.Settings) -> int:
    """Show the picker, and launch whatever it hands back.

    The launch happens after the application has returned, never inside it.
    Replacing this process while prompt_toolkit still owns the terminal would
    leave the alternate screen up and nothing to restore it.
    """
    from .launch import launch
    from .tui.picker import run_picker as show
    from .vault.locations import from_settings

    locations = from_settings(settings)
    choice = show(locations, settings)
    if choice is None:
        return 0

    entry, mode = choice
    problems = launch(locations, entry, mode.args)
    for problem in problems:
        print(f"ccl: {problem}", file=sys.stderr)
    return 1 if problems else 0


def reconfigure() -> int:
    """Open the configurator on demand, seeded with the settings as they stand.

    Unlike the automatic flow, this opens over an INVALID file too: refusing
    there protects a broken file from being overwritten unasked, and --config
    is precisely the asking. save() keeps a timestamped backup regardless, but
    the complaint is still worth a line first, so the user knows the file they
    are about to replace could not be read.

    Configure-and-exit, like --changelog: declining is "not now", not an error,
    and the next plain `ccl` runs with whatever was (or was not) saved.
    """
    from .tui.configure import run_configurator

    state = config.load()
    if state.state == config.INVALID:
        print(f"ccl: {config.config_file()} could not be read ({state.detail}); "
              f"saving here will replace it, with a backup kept beside it",
              file=sys.stderr)
    run_configurator(state.settings)
    return 0


def show_changelog() -> int:
    """Page through the history, fetching it first if the clone is still shallow.

    Announced before it happens rather than after: the install is cloned one
    commit deep, so the first run of this has to reach the network, and a
    terminal that sits there silently looks like a hang.
    """
    from . import history
    from .tui.pager import run_pager

    note = ""
    if history.is_shallow():
        print("ccl: fetching the history (first time only)...", file=sys.stderr)
        note = history.deepen()

    entries = history.read()
    if not entries:
        print(f"ccl: no history to show{' -- ' + note if note else ''}", file=sys.stderr)
        return 1
    run_pager(entries, config.load().settings, note)
    return 0


def settle_configuration() -> config.Settings | None:
    """Settle on settings before going further. None means stop.

    Three states, three answers, which is the whole reason config.load reports
    them separately:

    - No file at all is a first run. The configurator opens without comment,
      because being asked where your vault is the first time you run something
      is not an error, it is the setup.
    - A file that exists but cannot be used is reported and left alone. Opening
      the configurator here would end with it overwriting the very file that
      failed, destroying something recoverable; the launcher carries on with
      defaults instead, and the user can look at what they have.
    - Otherwise there is nothing to do.

    Declining the configurator stops the run rather than continuing to a
    launcher that has not been told where anything is. It is not an error --
    "not now" is a legitimate answer -- so the caller returns 0.

    Returns the settings to run with, so the picker is handed the same object
    the configurator just wrote rather than reading the file a second time.
    """
    state = config.load()
    if state.state == config.LOADED:
        return state.settings

    if state.state == config.INVALID:
        print(f"ccl: {config.config_file()} could not be read "
              f"({state.detail}); using defaults and leaving it alone",
              file=sys.stderr)
        return state.settings

    from .tui.configure import run_configurator

    return run_configurator(state.settings)

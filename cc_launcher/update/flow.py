"""The interactive flow: check, show, ask, apply."""
from __future__ import annotations
import sys

from ..changes import render_changelog
from ..term import paint
from ..update.apply import apply_update
from ..update.detect import check_nightly, check_release
from ..update.state import due_for_check, stamp_check

def run_update(*, ignore_interval: bool, nightly: bool = False,
               assume_yes: bool = False) -> tuple[int, bool]:
    """The whole flow.

    The flags are deliberately separate. `ignore_interval` only decides whether
    it is time to look; `assume_yes` decides whether to install without being
    told to. Conflating those two is what made `--update` skip the very question
    it exists to bring back. `nightly` picks the channel, and is never on for the
    automatic check — following the branch is something you ask for.

    Returns (exit code, whether the clone was actually changed) — the caller
    needs the second value because code already in memory is stale afterwards.
    """
    if not ignore_interval and not due_for_check():
        return 0, False

    status = check_nightly() if nightly else check_release()
    if status.reason:
        if ignore_interval:  # asked for explicitly, so say why nothing happened
            print(f"ccl: {status.reason}", file=sys.stderr)
            return 1, False
        return 0, False

    stamp_check()

    if not status.behind:
        if ignore_interval:
            print(f"CC_Launcher {paint(status.local_version, 'red')} — "
                  f"{paint('already up to date', 'green')}")
        return 0, False

    print(paint(status.message, "cyan", "bold"))

    # Before the question, not after it: what you are agreeing to should be on
    # screen while you decide.
    changelog = render_changelog(status.changes)
    if changelog:
        print(changelog)
        print()

    if not assume_yes:
        if not sys.stdin.isatty():
            return 0, False
        try:
            answer = input("Update now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0, False
        if answer not in ("", "y", "yes"):
            print("Skipped. Run `ccl --update` to be asked again.")
            return 0, False

    # apply_update takes the update lock itself; a refusal comes back as the
    # failure detail, blame included.
    ok, detail = apply_update(status)

    # A failure goes where failures go. `ccl --update 2>err.log` was losing the
    # reason while still exiting 1.
    print(f"ccl: {detail}", file=sys.stdout if ok else sys.stderr)
    return (0 if ok else 1), ok

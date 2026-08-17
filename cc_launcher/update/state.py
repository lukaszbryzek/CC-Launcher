"""State that must survive an update, so it lives outside the clone."""
from __future__ import annotations

from ..platform import current
import os
import time
from pathlib import Path

CHECK_EVERY_DAYS = 6

LOCK_STALE_SECONDS = 24 * 3600

def cache_dir() -> Path:
    return current().cache_dir()

def _stamp_file() -> Path:
    return cache_dir() / "last-check"

def _today() -> int:
    """Days since the epoch — the same granularity Oh My Zsh throttles on."""
    return int(time.time() // 86400)

def due_for_check() -> bool:
    try:
        last = int(_stamp_file().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (_today() - last) >= CHECK_EVERY_DAYS

def stamp_check() -> None:
    """Record that a check happened — including one the user answered "no" to.

    That is why `--update` exists: a declined prompt stays quiet for the full
    interval, so there has to be a way to ask again on demand.
    """
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        _stamp_file().write_text(f"{_today()}\n", encoding="utf-8")
    except OSError:
        pass

class UpdateLock:
    """Atomic `mkdir` as a mutex, the way Oh My Zsh does it.

    Two launchers started at once must not both reset the same clone. A lock
    left behind by a killed process goes stale after a day.

    `blame` says why the lock is not held, when it is not. FileExistsError is
    the one signal that actually means "someone else has it"; an unwritable
    cache directory or a read-only filesystem is a different failure, and
    telling the user to wait for a process that does not exist would be a lie.
    """

    def __init__(self) -> None:
        self.path = cache_dir() / "update.lock"
        self.held = False
        self.blame = ""

    def __enter__(self) -> UpdateLock:
        try:
            cache_dir().mkdir(parents=True, exist_ok=True)
            self._sweep_stale()
            self.path.mkdir()
            self.held = True
        except FileExistsError:
            self.blame = "another update is already running"
        except OSError as exc:
            self.blame = f"could not take the update lock ({exc.strerror or exc})"
        return self

    def _sweep_stale(self) -> None:
        """Take over a lock left by a killed process, atomically.

        rmdir-then-mkdir lets two sweepers interleave: the second rmdir can
        remove the first sweeper's freshly created lock, and both then believe
        they hold it -- two concurrent `reset --hard`s on one clone. Renaming
        the stale directory aside first is atomic: exactly one process wins,
        and the loser falls through to mkdir for the true answer.
        """
        try:
            age = time.time() - self.path.stat().st_mtime
            if age <= LOCK_STALE_SECONDS:
                return
            grave = self.path.with_name(f"update.lock.stale.{os.getpid()}")
            self.path.rename(grave)
            grave.rmdir()
        except OSError:
            # No lock to sweep, or another process swept it first. Either way
            # the mkdir that follows gives the honest verdict.
            pass

    def __exit__(self, *_exc) -> None:
        if self.held:
            try:
                self.path.rmdir()
            except OSError:
                pass

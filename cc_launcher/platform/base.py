"""What differs between operating systems, and nothing else.

Every OS-dependent decision the launcher makes lives behind this protocol, so
adding a system means writing one file rather than hunting `sys.platform` checks
through the codebase. The members here are not a guess at what might differ —
each one is a place where the code already had to branch, or was silently wrong
on a platform it had not been run on.
"""
from __future__ import annotations

import os
from pathlib import Path


class Platform:
    """The base contract. Subclasses override only what actually differs."""

    name = "unknown"

    # --- directories ---------------------------------------------------------

    def cache_dir(self) -> Path:
        """Throw-away state: the update stamp and the lock.

        Deliberately outside the install directory, which an update resets.
        """
        raise NotImplementedError

    def config_dir(self) -> Path:
        """User configuration. Nothing writes here yet; the uninstaller clears it."""
        raise NotImplementedError

    # --- the virtualenv ------------------------------------------------------

    def venv_bin(self, venv: Path) -> Path:
        """`bin` on POSIX, `Scripts` on Windows — the one layout difference that
        breaks every naive path built against a virtualenv."""
        raise NotImplementedError

    def venv_python(self, venv: Path) -> Path:
        raise NotImplementedError

    def venv_pip(self, venv: Path) -> Path:
        raise NotImplementedError

    # --- running the shipped scripts -----------------------------------------

    def shell_script_name(self, stem: str) -> str:
        """The filename under tools/ that this platform can actually run.

        `uninstall` is one script per platform, not one script: POSIX ships
        uninstall.sh and Windows uninstall.ps1. The caller names the job and
        gets back the file, instead of hardcoding an extension that is wrong on
        half the platforms.
        """
        raise NotImplementedError

    def run_shell_script(self, path: Path, args: tuple[str, ...] = ()) -> int:
        """Run one of the scripts under tools/ and return its exit code.

        POSIX runs it with `sh`. Windows has no `sh`, so it needs its own script
        and its own interpreter — which is why this is a method and not a
        hardcoded argv. Arguments are forwarded, without which --purge could be
        spelled on the uninstaller and never reached from `ccl --uninstall`.
        """
        raise NotImplementedError

    # --- handing over --------------------------------------------------------

    def exec_and_exit(self, argv: list[str], env: dict[str, str]):
        """Hand the terminal to the program and leave with its exit code.

        The one method launch() depends on, declared here like every other
        divergence — a platform that forgot it used to fail with AttributeError
        at launch time instead of this deliberate NotImplementedError. POSIX
        replaces the process outright (os.execvpe), so the call never returns;
        Windows cannot, so it waits for the child and raises SystemExit with
        its code. Callers treat both as "does not return".
        """
        raise NotImplementedError

    # --- interpreters --------------------------------------------------------

    def python_search_dirs(self) -> list[Path]:
        """Directories worth sweeping for interpreters, beyond PATH.

        PATH alone under-reports: Homebrew keeps a versioned formula's
        unversioned links in a keg-only directory that is not on it.
        """
        raise NotImplementedError

    # --- terminal ------------------------------------------------------------

    def enable_ansi(self) -> bool:
        """Make raw ANSI escapes render, returning whether they now will.

        POSIX terminals need nothing. A Windows console needs the virtual
        terminal mode switched on first, and without it every escape the
        launcher writes outside prompt_toolkit prints as literal garbage —
        prompt_toolkit enables it for its own output only.
        """
        raise NotImplementedError


class Posix(Platform):
    """Shared by macOS and Linux, which differ in none of this today."""

    name = "posix"

    def cache_dir(self) -> Path:
        import os
        root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        return Path(root) / "ccl"

    def config_dir(self) -> Path:
        import os
        root = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(root) / "ccl"

    def venv_bin(self, venv: Path) -> Path:
        return venv / "bin"

    def venv_python(self, venv: Path) -> Path:
        return self.venv_bin(venv) / "python"

    def venv_pip(self, venv: Path) -> Path:
        return self.venv_bin(venv) / "pip"

    def shell_script_name(self, stem: str) -> str:
        return f"{stem}.sh"

    def run_shell_script(self, path: Path, args: tuple[str, ...] = ()) -> int:
        import subprocess
        return subprocess.run(["sh", str(path), *args], check=False).returncode

    def exec_and_exit(self, argv: list[str], env: dict[str, str]):
        import os
        os.execvpe(argv[0], argv, env)

    def python_search_dirs(self) -> list[Path]:
        import glob
        roots: list[Path] = []
        for pattern in self._python_globs():
            roots.extend(Path(p) for p in glob.glob(os.path.expanduser(pattern)))
        return [r for r in roots if r.is_dir()]

    def _python_globs(self) -> list[str]:
        return [
            "/usr/bin", "/usr/local/bin",
            "~/.pyenv/versions/*/bin",
            "~/.local/share/uv/python/*/bin",
        ]

    def enable_ansi(self) -> bool:
        return True

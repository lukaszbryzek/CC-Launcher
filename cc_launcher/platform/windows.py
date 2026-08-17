"""Windows.

Written from the specifications rather than from a machine — no part of this has
run on Windows yet. What could be tested without one has been: the registry walk
is exercised against a stand-in for winreg, and both PowerShell scripts are
parsed with PowerShell's own parser. The Win32 calls in enable_ansi are the one
thing neither covers.
"""
from __future__ import annotations

import os
from pathlib import Path

from .base import Platform

# PEP 514. The same Company\Tag tree appears under three roots, and an
# environment registered in one is invisible from the others.
_REGISTRY_ROOTS = (
    ("HKEY_CURRENT_USER", r"Software\Python"),
    ("HKEY_LOCAL_MACHINE", r"Software\Python"),
    # What a 32-bit process sees as Software\Python. A 64-bit process has to ask
    # for it by name, which is how 32-bit installs go missing from a 64-bit
    # sweep — the reason the two access masks below are not enough on their own.
    ("HKEY_LOCAL_MACHINE", r"Software\Wow6432Node\Python"),
)

# "The company name PyLauncher is reserved for the PEP 397 launcher (py.exe). It
# does not follow this convention and should be ignored by tools." — PEP 514.
_RESERVED_COMPANIES = {"pylauncher"}


class Windows(Platform):
    name = "windows"

    def cache_dir(self) -> Path:
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "ccl" / "cache"

    def config_dir(self) -> Path:
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "ccl"

    def venv_bin(self, venv: Path) -> Path:
        return venv / "Scripts"

    def venv_python(self, venv: Path) -> Path:
        return self.venv_bin(venv) / "python.exe"

    def venv_pip(self, venv: Path) -> Path:
        return self.venv_bin(venv) / "pip.exe"

    # --- running the shipped scripts -----------------------------------------

    def shell_script_name(self, stem: str) -> str:
        return f"{stem}.ps1"

    def run_shell_script(self, path: Path, args: tuple[str, ...] = ()) -> int:
        """Run a shipped .ps1 under whichever PowerShell is installed.

        -ExecutionPolicy Bypass is passed for the child process only. Without it
        the uninstaller would be unrunnable on a default Windows client, where
        the effective policy is Restricted and no .ps1 runs at all — and being
        unable to remove software is worse than the risk of running a file this
        program installed itself. The setting is not persisted anywhere.
        """
        import shutil
        import subprocess

        # pwsh first: it is the current PowerShell, and 5.1 is the fallback that
        # is guaranteed present rather than the preferred one.
        exe = shutil.which("pwsh") or shutil.which("powershell")
        if exe is None:
            raise FileNotFoundError("neither pwsh nor powershell is on PATH")
        # Deliberately not -NonInteractive: the uninstaller asks for confirmation
        # first, and under that switch Read-Host throws instead of prompting, so
        # `ccl --uninstall` would refuse itself every time. The console is
        # inherited, exactly as `sh` inherits it on POSIX.
        # Everything after the -File path reaches the script as its own
        # arguments -- the forwarding the base contract promises, without which
        # `ccl --purge` ran uninstall.ps1 in plain mode and quietly kept the
        # settings the user asked to delete.
        return subprocess.run(
            [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), *args],
            check=False,
        ).returncode

    def exec_and_exit(self, argv: list[str], env: dict[str, str]):
        """Run the program, wait for it, and leave with its exit code.

        Not os.execvpe. On Windows that spawns a new process and ends this one
        at once, so the shell prints its prompt while the launched program is
        still using the terminal, and the exit code belongs to nobody. Waiting
        is what POSIX exec gives for free here.
        """
        import subprocess
        import sys

        completed = subprocess.run(argv, env=env, check=False)
        raise SystemExit(completed.returncode)

    # --- interpreters --------------------------------------------------------

    def python_search_dirs(self) -> list[Path]:
        """Every registered environment's prefix, plus the usual unregistered spots.

        The registry is the authority here, in the way that a directory sweep is
        on POSIX: PEP 514 exists precisely so that an installer can say where it
        put an interpreter, and installs outside PATH — all-users installs, the
        Store, anything the user did not tick "Add to PATH" for — are findable
        no other way.
        """
        found: list[Path] = []

        def add(path: Path) -> None:
            # Case-insensitively, because the registry and PATH disagree about
            # capitalisation constantly and would otherwise yield duplicates.
            if not any(str(p).lower() == str(path).lower() for p in found):
                found.append(path)

        for prefix in self._registered_prefixes():
            add(prefix)

        import glob
        for pattern in (
            r"~\AppData\Local\Programs\Python\Python*",
            r"~\.pyenv\pyenv-win\versions\*",
            r"~\AppData\Roaming\uv\python\*",
            r"~\AppData\Local\uv\python\*",
            r"C:\Python*",
        ):
            for hit in glob.glob(os.path.expanduser(pattern)):
                add(Path(hit))

        return [p for p in found if p.is_dir()]

    def _registered_prefixes(self) -> list[Path]:
        try:
            import winreg
        except ImportError:      # not Windows, or a Python built without it
            return []
        return _walk_registry(winreg)

    # --- terminal ------------------------------------------------------------

    def enable_ansi(self) -> bool:
        """Switch the console into virtual terminal mode.

        The existing mode is read and the flag OR-ed in, rather than the mode
        being set outright — dropping the other flags is what breaks line
        wrapping, a bug prompt_toolkit itself carries. A console that refuses
        the flag is a down-level one, and the honest answer there is no colour.
        """
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return False

        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        STD_OUTPUT_HANDLE = -11
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        if handle == wintypes.HANDLE(-1).value:
            return False
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(kernel32.SetConsoleMode(
            handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING))


def _walk_registry(winreg) -> list[Path]:  # noqa: ANN001 — the module, or a stand-in
    """Collect every PEP 514 InstallPath under all roots and both views.

    Taken as a module argument rather than imported, so the walk can be tested
    off Windows against a stand-in — the alternative was shipping it untested.

    Both KEY_WOW64_64KEY and KEY_WOW64_32KEY are asked for explicitly. Left to
    itself a 64-bit process reads only the 64-bit view, and a 32-bit one only
    the 32-bit view, so whichever interpreter is running this would decide which
    installs exist.
    """
    views = (getattr(winreg, "KEY_WOW64_64KEY", 0x0100),
             getattr(winreg, "KEY_WOW64_32KEY", 0x0200))
    prefixes: list[Path] = []

    for root_name, subkey in _REGISTRY_ROOTS:
        root = getattr(winreg, root_name)
        for view in views:
            access = winreg.KEY_READ | view
            try:
                companies = winreg.OpenKey(root, subkey, 0, access)
            except OSError:
                continue
            with companies:
                for company in _subkeys(winreg, companies):
                    if company.lower() in _RESERVED_COMPANIES:
                        continue
                    try:
                        tags = winreg.OpenKey(companies, company, 0, access)
                    except OSError:
                        continue
                    with tags:
                        for tag in _subkeys(winreg, tags):
                            prefix = _install_path(winreg, tags, tag, access)
                            if prefix is not None:
                                prefixes.append(prefix)
    return prefixes


def _subkeys(winreg, key) -> list[str]:  # noqa: ANN001
    """Every subkey name, read to the end.

    EnumKey is index-based and signals the end with OSError, which is also what
    it raises when a single key is unreadable — so enumeration stops there
    either way, and the names collected up to that point are still good.
    """
    names: list[str] = []
    index = 0
    while True:
        try:
            names.append(winreg.EnumKey(key, index))
        except OSError:
            return names
        index += 1


def _install_path(winreg, parent, tag: str, access: int) -> Path | None:  # noqa: ANN001
    """The environment's sys.prefix, from <Tag>\\InstallPath's default value.

    PEP 514 makes the default value of InstallPath equal to sys.prefix, and on
    Windows python.exe sits directly in sys.prefix — so a prefix slots straight
    into the directory sweep the rest of pyfind already does. ExecutablePath is
    deliberately not read: it may name an executable that is not called python,
    which the sweep would then reject, and the prefix finds the real one anyway.
    """
    try:
        key = winreg.OpenKey(parent, tag + r"\InstallPath", 0, access)
    except OSError:
        return None                       # InstallPath is required, but absent keys happen
    with key:
        try:
            value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.rstrip("\\/") or value)

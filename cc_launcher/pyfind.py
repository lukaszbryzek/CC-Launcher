"""Find the Python interpreters on this machine, by running them.

Reading the filesystem is not enough and this is not a theoretical worry: on the
machine this was written on, a virtualenv's own pyvenv.cfg claimed 3.14.6 while
the environment actually ran 3.14.7, because Homebrew had replaced the patch
release under a stable symlink. The only trustworthy answer comes from asking
the interpreter itself.

Scanning PATH alone is not enough either. Homebrew keeps the unversioned
python/python3 links of a versioned formula in a keg-only directory that is not
on PATH, so a PATH-only sweep silently under-reports — `uv python list` misses
them for exactly this reason.

Stdlib only, and no imports from the rest of the package beyond the platform
layer, so this can run under whichever interpreter is bootstrapping the install.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .platform import current

PROBE_TIMEOUT = 10.0

# uv's probe, minus -S: isolated mode with bytecode writing off. -S looks safer
# and is not — site initialisation is what populates sys.path for framework,
# venv and conda layouts, so removing it changes the answer.
_PROBE = (
    "import json,sys;"
    "print(json.dumps({"
    "'version': '.'.join(map(str, sys.version_info[:3])),"
    "'impl': sys.implementation.name,"
    "'executable': sys.executable,"
    "'prefix': sys.prefix,"
    "'base_prefix': sys.base_prefix}))"
)

# python3.13-config and friends live beside the interpreters and answer a probe
# with a usage error. Match the interpreter names exactly instead of globbing.
#
# The optional .exe is what makes the Windows sweep find anything at all, and it
# still excludes pythonw.exe — the windowed build, which detaches from the
# console and would return no output to probe.
_INTERPRETER_NAME = re.compile(r"^python(?:\d+(?:\.\d+)?)?(?:\.exe)?$", re.IGNORECASE)

# IO_REPARSE_TAG_APPEXECLINK. Named here rather than taken from stat, which only
# defines it on Windows — this module is imported everywhere.
_APPEXECLINK = 0x8000001B


@dataclass(frozen=True)
class Interpreter:
    path: Path
    version: tuple[int, ...]
    implementation: str
    real: Path          # realpath of sys.executable — the identity used to dedupe
    is_venv: bool

    @property
    def label(self) -> str:
        return ".".join(str(n) for n in self.version)


def _probe(candidate: Path) -> Interpreter | None:
    """Ask a candidate what it is. None when it is not an interpreter at all.

    A timeout is imposed because uv, whose approach this follows, imposes none —
    a candidate on a dead network mount or with an interactive sitecustomize
    would otherwise hang the installer.
    """
    try:
        done = subprocess.run(
            [str(candidate), "-I", "-B", "-c", _PROBE],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not done.stdout.strip():
        # Includes the macOS /usr/bin/python3 trampoline when the Command Line
        # Tools are absent: it fails with an xcrun error rather than running.
        return None
    try:
        data = json.loads(done.stdout)
        version = tuple(int(p) for p in str(data["version"]).split("."))
    except (ValueError, KeyError):
        return None
    return Interpreter(
        path=candidate,
        version=version,
        implementation=str(data.get("impl", "?")),
        real=Path(os.path.realpath(str(data.get("executable") or candidate))),
        is_venv=data.get("prefix") != data.get("base_prefix"),
    )


def _is_store_alias(path: Path) -> bool:
    """True for a Windows App Execution Alias, which must never be run.

    These are the zero-byte python.exe and python3.exe in
    %LOCALAPPDATA%\\Microsoft\\WindowsApps — a directory Windows puts on PATH by
    default, so a PATH sweep hits them first. They are not interpreters but
    reparse points tagged IO_REPARSE_TAG_APPEXECLINK, and running one when the
    Store package is absent opens the Microsoft Store instead of failing. An
    installer that opens a shop is not an acceptable outcome, and the Store
    Python, when it really is installed, is registered under PEP 514 and found
    through the registry anyway.
    """
    try:
        return os.lstat(path).st_reparse_tag == _APPEXECLINK  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        # st_reparse_tag exists only on Windows; everywhere else there is no
        # such thing as one of these, so the answer is no.
        return False


def candidates() -> list[Path]:
    """Every plausible interpreter path, before any of them has been run."""
    found: list[Path] = []

    def add(path: Path) -> None:
        if path in found or _is_store_alias(path):
            return
        found.append(path)

    for directory in current().python_search_dirs():
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if _INTERPRETER_NAME.match(entry.name) and os.access(entry, os.X_OK):
                add(entry)

    # PATH last: it finds nothing the sweep missed on a normal machine, but it
    # covers the layouts nobody enumerated.
    for name in ("python3", "python"):
        for whole in _which_all(name):
            add(whole)
    return found


def _which_all(name: str) -> list[Path]:
    out: list[Path] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        found = shutil.which(name, path=directory)
        if found:
            out.append(Path(found))
    return out


def discover(include_venvs: bool = False) -> list[Interpreter]:
    """Distinct interpreters, newest first.

    Deduplicated by the realpath of sys.executable rather than by the candidate
    path, so the several names Homebrew and the distros hang off one binary
    collapse into a single entry.
    """
    seen: dict[Path, Interpreter] = {}
    for candidate in candidates():
        found = _probe(candidate)
        if found is None:
            continue
        if found.is_venv and not include_venvs:
            continue
        # Keep the shortest, most stable-looking path for a given binary.
        previous = seen.get(found.real)
        if previous is None or len(str(found.path)) < len(str(previous.path)):
            seen[found.real] = found
    return sorted(seen.values(), key=lambda i: i.version, reverse=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    found = discover(include_venvs="--include-venvs" in argv)
    if as_json:
        print(json.dumps([
            {"path": str(i.path), "version": i.label,
             "implementation": i.implementation, "real": str(i.real)}
            for i in found
        ]))
        return 0
    if not found:
        print("no Python interpreters found", file=sys.stderr)
        return 1
    if "--list" in argv:
        # Tab-separated for the installer, which is POSIX sh and has no JSON.
        for i in found:
            print(f"{i.label}\t{i.path}")
        return 0
    for n, i in enumerate(found, 1):
        print(f"{n}) {i.label:<9} {i.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

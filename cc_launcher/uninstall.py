"""Handing off to the uninstaller from outside the directory it deletes."""
from __future__ import annotations
import subprocess
import sys
import tempfile
from pathlib import Path

from .paths import HOME_DIR
from .platform import current

def run_uninstall(purge: bool = False) -> int:
    """Hand off to the platform's uninstaller, from a copy outside the clone.

    The script deletes HOME_DIR, and `sh` reads its script file incrementally —
    running it in place risks the file disappearing halfway through. Copying it
    to a temporary location first removes that hazard completely.
    """
    name = current().shell_script_name("uninstall")
    script = HOME_DIR / "tools" / name
    if not script.is_file():
        print(f"ccl: {script} not found", file=sys.stderr)
        return 1

    copy = None
    try:
        # The suffix has to survive the copy: PowerShell -File refuses anything
        # that is not .ps1, so a generic temporary name would fail on Windows.
        with tempfile.NamedTemporaryFile(
            "wb", suffix=Path(name).suffix, delete=False
        ) as handle:
            handle.write(script.read_bytes())
            copy = Path(handle.name)
        return current().run_shell_script(copy, ("--purge",) if purge else ())
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ccl: could not run the uninstaller ({exc})", file=sys.stderr)
        return 1
    finally:
        if copy is not None:
            copy.unlink(missing_ok=True)

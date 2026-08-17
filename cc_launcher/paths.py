"""Where the install lives. Everything else derives its paths from here."""
from __future__ import annotations
from pathlib import Path

# One level further up than the original: this file now sits inside the
# package, while the value must stay the install directory itself.
HOME_DIR = Path(__file__).resolve().parent.parent

META_FILE = HOME_DIR / "meta.yaml"


def short_path(path: Path) -> str:
    """A path with a leading ~ when it is under home, otherwise unchanged.

    Used both for what the settings file stores and for what the UI shows, so it
    lives here rather than in either of them.
    """
    home = Path.home()
    if path == home:
        # relative_to would answer "." and produce "~/.", which is the same
        # directory spelled badly.
        return "~"
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)

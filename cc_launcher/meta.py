"""meta.yaml is the single source of truth for the version, and the channel
lives in the clone's git config beside it."""
from __future__ import annotations
import functools
import re

try:
    import yaml
except ImportError:  # the version is cosmetic; never fail the launcher over it
    yaml = None

from .paths import META_FILE

def parse_version(text: str) -> str:
    """Pull `version` out of meta.yaml, without trusting the file's shape."""
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            data = None
        if isinstance(data, dict) and data.get("version"):
            return str(data["version"]).strip()
        return "unknown"
    match = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1).strip("\"'") if match else "unknown"

@functools.lru_cache(maxsize=1)
def local_version() -> str:
    """Cached: meta.yaml cannot change under a running process, and the UI asks
    for the version on every redraw."""
    try:
        return parse_version(META_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        # A missing, unreadable or undecodable meta.yaml must not take the
        # launcher down; an unknown version simply disables the update machinery.
        return "unknown"

def version_tuple(text: str) -> tuple[int, ...] | None:
    """`v0.2.0` or `0.2.0` into (0, 2, 0); None when it is not a number triple.

    Matched strictly rather than fed straight to int(), which accepts '-1',
    '+1' and '1_0' -- shapes that survive the filter end up in git argv, where
    a leading dash reads as an option.
    """
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r"[vV]?(\d+(?:\.\d+)*)", text.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))

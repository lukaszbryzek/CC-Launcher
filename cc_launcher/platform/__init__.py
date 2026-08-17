"""Pick the implementation for the machine this is running on."""
from __future__ import annotations

import functools
import sys

from .base import Platform


@functools.lru_cache(maxsize=1)
def current() -> Platform:
    """The platform for this interpreter, resolved once.

    sys.platform rather than os.name, because it distinguishes macOS from Linux
    while os.name calls both 'posix'.
    """
    if sys.platform == "darwin":
        from .macos import MacOS
        return MacOS()
    if sys.platform.startswith("win"):
        from .windows import Windows
        return Windows()
    from .linux import Linux
    return Linux()

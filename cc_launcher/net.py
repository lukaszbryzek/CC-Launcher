"""HTTP against the GitHub API, with the timeout and rate-limit policy."""
from __future__ import annotations
import time
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"

RAW_ROOT = "https://raw.githubusercontent.com"

# The automatic check sits in the startup path, so it gets a tight budget. A
# command the user typed does not: they are waiting on purpose, and a false
# "could not reach GitHub" is worse than a couple of seconds.
NET_TIMEOUT = 3.0

NET_TIMEOUT_EXPLICIT = 15.0

USER_AGENT = "ccl"

_net_timeout = NET_TIMEOUT

_rate_reset = 0.0  # epoch seconds the GitHub rate limit frees up, 0 when not hit

def fetch(url: str, accept: str = "application/vnd.github+json") -> tuple[int | None, str]:
    """(status, body). A status of None means the request never got an answer.

    The distinction matters: a 404 from the releases endpoint means "nothing has
    been released yet", which is a fact worth reporting, while no answer at all
    means the network is down and nothing can be concluded.
    """
    global _rate_reset
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_net_timeout) as response:
            # An answer arrived, so any rate-limit mark from an earlier call is
            # stale news -- left in place, it would blame every later network
            # drop on a limit that has already lifted.
            _rate_reset = 0.0
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        # Unauthenticated callers get 60 requests an hour, and running out looks
        # nothing like a network failure — so do not report it as one.
        if error.code in (403, 429) and error.headers.get("X-RateLimit-Remaining") == "0":
            try:
                _rate_reset = float(error.headers.get("X-RateLimit-Reset") or 0)
            except (TypeError, ValueError):
                _rate_reset = 0.0
        return error.code, ""
    except (urllib.error.URLError, OSError, ValueError):
        return None, ""

def unreachable_reason() -> str:
    # Only a reset instant still ahead of us is a rate limit; one in the past
    # would keep claiming "try again in about 1 min" forever.
    if _rate_reset > time.time():
        minutes = max(1, int((_rate_reset - time.time()) // 60) + 1)
        return f"GitHub rate limit reached — try again in about {minutes} min"
    return "could not reach GitHub"


def network_timeout() -> float:
    """The budget in force, for network work done outside urllib.

    `git ls-remote` is a network round trip like any fetch here, and giving it
    the subprocess default instead let the automatic startup check hang for ten
    times the budget this module promises.
    """
    return _net_timeout


def use_explicit_timeout() -> None:
    """Raise the budget for a command the user typed.

    A setter rather than a cross-module `global`, which cannot work once the
    caller lives in another module.
    """
    global _net_timeout
    _net_timeout = NET_TIMEOUT_EXPLICIT

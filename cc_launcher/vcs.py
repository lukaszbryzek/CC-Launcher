"""Every git call the launcher makes, and nothing else."""
from __future__ import annotations
import functools
import subprocess

from .meta import local_version, version_tuple
from .net import network_timeout
from .paths import HOME_DIR

def git(*args: str, timeout: float = 30.0) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(HOME_DIR), *args],
            # git writes UTF-8 whatever the locale says; decoding with the
            # locale default made a commit message with an accent a latent
            # UnicodeDecodeError on any machine not already running UTF-8.
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None

@functools.lru_cache(maxsize=1)
def origin() -> tuple[str, str] | None:
    """(owner/repo, branch) taken from the clone, or None if this is not one.

    Cached: four subprocesses answer a question whose answer cannot change
    while this process runs -- except across an update, which clears it beside
    local_version for the same reason.
    """
    if git("rev-parse", "--is-inside-work-tree") != "true":
        return None
    branch = git("config", "--local", "ccl.branch") or "main"
    remote = git("config", "--local", "ccl.remote") or "origin"
    url = git("config", f"remote.{remote}.url")
    if not url:
        return None
    for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if url.startswith(prefix):
            return url[len(prefix):].removesuffix(".git"), branch

    # An SSH host alias out of ~/.ssh/config, which is what a per-account key
    # looks like: git@github-shared:owner/repo.git. The alias is whatever its
    # owner called it, so the only honest test is whether they called it after
    # GitHub -- guessing that every alias is GitHub would build links to a host
    # that may not be one.
    import re

    alias = re.match(r"^(?:ssh://)?git@(?P<host>[^:/]+)[:/](?P<path>.+)$", url)
    if alias and "github" in alias.group("host").lower():
        return alias.group("path").removesuffix(".git"), branch
    return None  # not GitHub, or not recognisably so

def remote_tags() -> list[tuple[tuple[int, ...], str, str]] | None:
    """(version, tag, sha) for every version tag on the remote, lowest first.

    None when the remote could not be asked at all -- different news from a
    remote with no tags, and the callers say different things about each.
    Collapsing the two made `--update` claim "no version tags on the remote
    yet" to a user who was merely offline.

    Read with `git ls-remote`, not the GitHub API: no quota, no token, and it
    works against any git host. A release here is a tag and a bumped version in
    meta.yaml — nothing GitHub-specific is involved.

    The timeout follows the network budget net.py already enforces for its own
    calls, with a floor for a healthy-but-slow round trip; the subprocess
    default of 30s let the automatic startup check hang ten times longer than
    the budget it claims.
    """
    # `origin` by name, not the URL: the clone already knows where it came from.
    listing = git("ls-remote", "--tags", "--refs", "origin",
                  timeout=max(5.0, network_timeout()))
    if listing is None:
        return None
    found: list[tuple[tuple[int, ...], str, str]] = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        name = ref.rsplit("/", 1)[-1]
        parsed = version_tuple(name)
        if parsed:
            found.append((parsed, name, sha))
    return sorted(found)

def channel() -> str:
    """`release` or `nightly`, recorded in the clone by whoever put us here."""
    return (git("config", "--local", "ccl.channel") or "").strip() or "release"

def set_channel(name: str) -> None:
    git("config", "--local", "ccl.channel", name)

def describe_version() -> str:
    """`0.1.1` on the release channel, `0.1.1(abc1234)` on nightly.

    The marker follows the channel — a thing the user chose — and not whether
    HEAD happens to sit on a tag. Those two come apart in an entirely ordinary
    case: a project with no releases published yet, where a tag test brands every
    install nightly even though nobody asked for nightly.
    """
    version = local_version()
    if channel() != "nightly":
        return version
    head = git("rev-parse", "--short", "HEAD")
    return f"{version}({head})" if head else version

"""Moving the clone onto a target, and keeping dependencies in step."""
from __future__ import annotations
import hashlib
import re
import subprocess
import sys

from ..meta import local_version
from ..net import API_ROOT, fetch
from ..paths import HOME_DIR
from ..platform import current
from ..term import paint
from ..update.detect import UpdateStatus
from ..update.state import UpdateLock
from ..vcs import describe_version, git, origin, remote_tags, set_channel

def _requirements_digest() -> str:
    try:
        return hashlib.sha256((HOME_DIR / "requirements.txt").read_bytes()).hexdigest()
    except OSError:
        return ""

def _sync_dependencies(before: str) -> tuple[bool, str]:
    """Reinstall only when requirements.txt actually moved, in either direction.

    A downgrade needs this as much as an upgrade: an older revision may pin
    older packages, and leaving the newer ones installed is not "no change".
    """
    if _requirements_digest() == before:
        return True, ""
    pip = current().venv_pip(HOME_DIR / ".venv")
    if not pip.exists():
        return True, ""
    try:
        subprocess.run(
            [str(pip), "install", "--quiet", "--disable-pip-version-check",
             "-r", str(HOME_DIR / "requirements.txt")],
            check=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return False, "dependency install failed"
    return True, "dependencies reinstalled"

def set_version(target: str) -> int:
    """Move the clone onto a release or a commit — downgrades included."""
    # Shape first: a typo should be reported as a typo, whatever the clone is.
    if re.fullmatch(r"\d+(?:\.\d+)+", target):
        refs, kind = [f"v{target}", target], "tag"
    elif re.fullmatch(r"[0-9a-fA-F]{7,40}", target):
        refs, kind = [target], "commit"
    else:
        print(f"ccl: '{target}' is neither a version (x.y.z) nor a commit hash",
              file=sys.stderr)
        return 1

    target_repo = origin()
    if target_repo is None:
        print("ccl: not a git clone, nothing to switch", file=sys.stderr)
        return 1
    repo = target_repo[0]

    # GitHub will not serve an abbreviated SHA to `git fetch` — it answers
    # "couldn't find remote ref" — and an abbreviated SHA is exactly what
    # `--version` prints, so it is exactly what gets pasted back in. Resolve it
    # through the API, which does accept the short form.
    if kind == "commit" and len(target) < 40:
        code, full = fetch(f"{API_ROOT}/repos/{repo}/commits/{target}",
                           accept="application/vnd.github.v3.sha")
        full = full.strip()
        if code != 200 or not re.fullmatch(r"[0-9a-f]{40}", full):
            print(f"ccl: no such commit on the remote: {target}", file=sys.stderr)
            return 1
        refs = [full]

    was = describe_version()
    before = _requirements_digest()

    for ref in refs:
        fetched = (git("fetch", "--quiet", "--depth=1", "origin", "tag", ref)
                   if kind == "tag" else
                   git("fetch", "--quiet", "--depth=1", "origin", ref))
        if fetched is None:
            continue
        with UpdateLock() as lock:
            if not lock.held:
                print(lock.blame or "An update is already running.", file=sys.stderr)
                return 1
            if git("reset", "--quiet", "--hard", ref) is None:
                # The fetch of this ref just succeeded, so the ref exists; what
                # failed was moving onto it. Falling through to the not-found
                # report would send the user hunting for a typo in a ref that
                # is fine.
                print(f"ccl: fetched {ref} but could not check it out",
                      file=sys.stderr)
                return 1
            # Pinning to a release keeps you on releases; pinning to a commit is
            # by definition off them.
            set_channel("release" if kind == "tag" else "nightly")
            ok, detail = _sync_dependencies(before)
        # Both caches read the clone, and the clone just changed under them.
        local_version.cache_clear()
        origin.cache_clear()
        print(f"ccl: {paint(was, 'red')} → {paint(describe_version(), 'green')}"
              + (f" ({detail})" if detail else ""))
        return 0 if ok else 1

    if kind == "commit":
        print(f"ccl: no such commit on the remote: {target}", file=sys.stderr)
        return 1

    # "not found" on its own sends you guessing. Say what does exist — including
    # when the answer is nothing, which is its own useful fact.
    tags = remote_tags()
    if tags is None:
        print(f"ccl: no release {target} fetched — and the remote could not be "
              f"reached to list what exists", file=sys.stderr)
        return 1
    published = [name for _, name, _ in tags]
    if published:
        print(f"ccl: no release {target}. Tagged: {', '.join(published[-10:])}",
              file=sys.stderr)
    else:
        print(f"ccl: no release {target} — the remote has no version tags, "
              f"so only --set-version <commit> can move this install",
              file=sys.stderr)
    return 1

def apply_update(status: UpdateStatus) -> tuple[bool, str]:
    """Move the clone onto the target, reinstalling deps only if they moved.

    Takes the update lock itself. The invariant — the clone is never reset by
    two processes at once — belongs beside the resets, not with whichever
    caller remembers to hold a lock around the call; set_version already works
    that way, and two different contracts for the same mutation is how a new
    caller races an update.

    The target differs by channel and that difference is the whole point of the
    release channel: resetting to the branch tip there would install unreleased
    code under a policy that promises releases only.
    """
    with UpdateLock() as lock:
        if not lock.held:
            return False, lock.blame or "another update is already running"
        return _apply_locked(status)

def _apply_locked(status: UpdateStatus) -> tuple[bool, str]:
    before = _requirements_digest()
    branch = status.branch or "main"

    if status.channel == "release":
        tag = status.ref
        if git("fetch", "--quiet", "--depth=1", "origin", "tag", tag) is None:
            return False, f"could not fetch tag {tag}"
        if git("reset", "--quiet", "--hard", tag) is None:
            return False, f"could not check out {tag}"
    else:
        # --tags keeps the clone's tag refs current, which is what lets
        # `--version` tell a release apart from a commit past it, offline.
        if git("fetch", "--quiet", "--depth=1", "--tags", "origin", branch) is None:
            return False, "fetch failed"
        if git("reset", "--quiet", "--hard", f"origin/{branch}") is None:
            return False, "reset failed"

    # Taking an update from a channel is what puts you on that channel.
    set_channel(status.channel)
    # Both caches read the clone, and the clone just changed under them.
    local_version.cache_clear()
    origin.cache_clear()
    ok, detail = _sync_dependencies(before)
    if not ok:
        return False, f"updated, but {detail}"
    return True, f"updated, {detail}" if detail else "updated"

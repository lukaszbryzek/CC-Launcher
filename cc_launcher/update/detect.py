"""What counts as an update, per channel."""
from __future__ import annotations
import re
from dataclasses import dataclass

from ..changes import Change, fetch_changes
from ..meta import local_version, parse_version, version_tuple
from ..net import API_ROOT, RAW_ROOT, fetch, unreachable_reason
from ..vcs import git, origin, remote_tags

@dataclass(frozen=True)
class UpdateStatus:
    """What a check found. `behind` is the only reason to offer an update."""

    local_version: str
    behind: bool = False
    remote_version: str = ""
    commits: int = 0
    branch: str = ""
    reason: str = ""
    channel: str = "release"
    ref: str = ""  # what to reset to: a tag on the release channel, a branch on nightly
    changes: tuple[Change, ...] = ()

    @property
    def message(self) -> str:
        if not self.behind:
            return f"CC_Launcher {self.local_version}"
        if self.channel == "release":
            return f"CC_Launcher {self.local_version} → {self.remote_version} available"
        # On nightly a commit that does not bump meta.yaml is the common case,
        # and saying "0.1.0 → 0.1.0 available" would be a lie dressed as a release.
        if self.remote_version and self.remote_version != self.local_version:
            return (f"CC_Launcher {self.local_version} → {self.remote_version} "
                    f"on {self.branch} (nightly)")
        plural = "commit" if self.commits == 1 else "commits"
        return (f"CC_Launcher {self.local_version} — {self.commits} new {plural} "
                f"on {self.branch} (nightly)")

def check_release() -> UpdateStatus:
    """The default channel: the highest version tag on the remote."""
    version = local_version()
    target = origin()
    if target is None:
        return UpdateStatus(version, reason="not a git clone")
    repo, branch = target

    tags = remote_tags()
    if tags is None:
        # Not the same news as "no tags": claiming the remote has none while
        # merely offline is a confident falsehood, and it sent users towards
        # --set-version for a problem that was their wifi.
        return UpdateStatus(version, branch=branch, channel="release",
                            reason=unreachable_reason())
    if not tags:
        return UpdateStatus(version, branch=branch, channel="release",
                            reason="no version tags on the remote yet")

    there, tag, _tag_object = tags[-1]
    here = version_tuple(version)
    if here is None or there <= here:
        return UpdateStatus(version, branch=branch, channel="release")

    head = git("rev-parse", "HEAD") or ""
    # No HEAD means no comparison is possible; skip the request rather than
    # spend it on an answer that cannot be used.
    # By name, not by the SHA `ls-remote` gave us. Our tags are annotated, so
    # refs/tags/X points at a tag object rather than a commit, and the compare
    # API answers 404 for one — verified against the live endpoint in all three
    # forms. The name resolves correctly, and so does the peeled commit.
    count, changes, _ = fetch_changes(repo, head, tag) if head else (0, (), "")

    return UpdateStatus(
        local_version=version,
        behind=True,
        remote_version=tag.lstrip("vV"),
        commits=count,
        branch=branch,
        channel="release",
        ref=tag,
        changes=changes,
    )

def check_nightly() -> UpdateStatus:
    """The opt-in channel: the branch tip, exactly as Oh My Zsh compares it."""
    version = local_version()
    target = origin()
    if target is None:
        return UpdateStatus(version, reason="not a GitHub clone")
    repo, branch = target

    head = git("rev-parse", "HEAD")
    if not head:
        return UpdateStatus(version, reason="no local HEAD")

    status, remote_head = fetch(f"{API_ROOT}/repos/{repo}/commits/{branch}",
                                accept="application/vnd.github.v3.sha")
    remote_head = remote_head.strip()
    if status != 200 or not re.fullmatch(r"[0-9a-f]{40}", remote_head):
        return UpdateStatus(version, reason=unreachable_reason())

    if remote_head == head:
        return UpdateStatus(version, branch=branch, channel="nightly")

    # Differing heads are not enough: we might be ahead, or diverged. Ask GitHub
    # rather than `git merge-base`, which cannot answer in a shallow clone —
    # the remote commit is simply not present locally.
    count, changes, compared = fetch_changes(repo, head, remote_head)
    if compared in ("unreachable", "unreadable"):
        return UpdateStatus(version, reason="could not compare")

    # `status` describes head relative to base, and we asked local...remote — so
    # the remote being "ahead" is what means we are the ones behind. Reading it
    # the other way round makes the check silently answer "up to date" forever.
    if compared != "ahead":
        return UpdateStatus(version, branch=branch, channel="nightly")

    _, raw = fetch(f"{RAW_ROOT}/{repo}/{branch}/meta.yaml", accept="text/plain")
    return UpdateStatus(
        local_version=version,
        behind=True,
        remote_version=parse_version(raw) if raw else "",
        commits=count,
        branch=branch,
        channel="nightly",
        ref=f"origin/{branch}",
        changes=changes,
    )

"""Reading the project's own history out of the clone.

From git rather than the GitHub API. The API would work, but it costs a request
every time, spends a rate limit that is 60 an hour without a token, and needs
the network on every look. The clone is already a git repository; the only thing
it lacks is depth, and that is a one-off fetch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .changes import Change, parse_commit
from .term import printable
from .vcs import git

# Unit and record separators: a commit message can contain anything a person can
# type, including every character that would otherwise do as a delimiter.
FIELD = "\x1f"
RECORD = "\x1e"

FORMAT = FIELD.join(["%H", "%ad", "%D", "%B"]) + RECORD


@dataclass(frozen=True)
class Entry:
    """One commit, with the day it landed and any release it carries."""

    date: str            # YYYY-MM-DD, which is what --date=short gives
    change: Change
    tags: tuple[str, ...] = ()


def is_shallow() -> bool:
    return (git("rev-parse", "--is-shallow-repository") or "").strip() == "true"


def deepen() -> str:
    """Fetch the rest of the history. Returns a complaint, or an empty string.

    The install is cloned with --depth=1, so there is exactly one commit until
    this runs. Deepening is safe for the updater, which fetches single tags with
    --depth=1 and resets onto them -- verified against a deepened clone rather
    than assumed.
    """
    # The one fetch here that moves real history, so it gets a real budget:
    # the default 30s fits a tag or a tip, not a whole repository on slow wifi.
    if git("fetch", "--quiet", "--unshallow", "--tags", timeout=300.0) is None:
        return "could not fetch the history"
    return ""


def _tags_from_refs(refs: str) -> tuple[str, ...]:
    """Tag names out of git's ref decoration, ignoring branches and HEAD."""
    return tuple(m.group(1) for m in re.finditer(r"tag:\s*([^,)]+)", refs))


def read(limit: int = 0) -> tuple[Entry, ...]:
    """The history, newest first. Empty when the clone cannot be read."""
    args = ["log", f"--pretty=format:{FORMAT}", "--date=short"]
    if limit:
        args.append(f"-{limit}")
    raw = git(*args)
    if raw is None:
        return ()

    entries = []
    for record in raw.split(RECORD):
        record = record.strip("\n")
        if not record.strip():
            continue
        parts = record.split(FIELD)
        if len(parts) < 4:
            continue
        sha, date, refs, message = parts[0], parts[1], parts[2], FIELD.join(parts[3:])
        entries.append(Entry(date=date.strip(),
                             change=parse_commit(sha.strip(), message),
                             tags=_tags_from_refs(refs)))
    return tuple(entries)


def load(deepen_if_needed: bool = True) -> tuple[tuple[Entry, ...], str]:
    """The history and a note about what had to happen to get it.

    The note is empty on an ordinary read. It says so when the clone had to be
    deepened first, because that is a network round trip the caller may want to
    mention before it happens.
    """
    if deepen_if_needed and is_shallow():
        complaint = deepen()
        if complaint:
            # One commit is still better than nothing, and saying why beats
            # showing a single line with no explanation.
            return read(), complaint
        return read(), ""
    return read(), ""


@dataclass(frozen=True)
class Details:
    """Everything worth knowing about one commit, fetched only when asked for.

    Not carried on Entry: the list holds every commit in the project and almost
    none of them are ever opened, so the body, the author and the diff stat
    would be a hundred reads to serve one.
    """

    sha: str             # the full hash, not the short one
    author: str
    when: str            # ISO-ish, with the time, unlike the list's plain day
    subject: str
    body: str
    files: int
    insertions: int
    deletions: int
    tags: tuple[str, ...] = ()
    url: str = ""


DETAIL_FORMAT = FIELD.join(["%H", "%an", "%ad", "%D", "%B"])


def _stat(sha: str) -> tuple[int, int, int]:
    """Files changed, lines added, lines removed.

    From --numstat rather than --shortstat, which has to be parsed out of a
    sentence that changes with the singular. Binary files report "-" for both
    counts and are counted as changed without adding to either total.
    """
    raw = git("show", "--numstat", "--format=", sha)
    if raw is None:
        return 0, 0, 0
    files = insertions = deletions = 0
    for row in raw.splitlines():
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        added, removed = parts[0], parts[1]
        insertions += int(added) if added.isdigit() else 0
        deletions += int(removed) if removed.isdigit() else 0
    return files, insertions, deletions


def commit_url(sha: str) -> str:
    """The commit's page on GitHub, or empty when the remote is not one."""
    from .vcs import origin

    target = origin()
    return f"https://github.com/{target[0]}/commit/{sha}" if target else ""


def details(sha: str) -> Details | None:
    """One commit in full. None when it cannot be read."""
    raw = git("show", "--no-patch", f"--format={DETAIL_FORMAT}", "--date=iso", sha)
    if raw is None:
        return None
    parts = raw.split(FIELD)
    if len(parts) < 5:
        return None
    full, author, when, refs = (p.strip() for p in parts[:4])
    # The author and message are whatever the remote's commits carry, and the
    # list view already launders its text through parse_commit. Same rule here.
    author = printable(author)
    message = printable(FIELD.join(parts[4:]).strip("\n"))
    lines = message.splitlines()
    files, insertions, deletions = _stat(full)
    return Details(
        sha=full,
        author=author,
        when=when,
        subject=lines[0] if lines else "",
        body="\n".join(lines[1:]).strip("\n"),
        files=files,
        insertions=insertions,
        deletions=deletions,
        tags=_tags_from_refs(refs),
        url=commit_url(full),
    )

"""Conventional Commits in, a grouped changelog out."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass

from .net import API_ROOT, fetch
from .term import colour_enabled, paint, printable

# The Conventional Commit types this project uses. Oh My Zsh recognises ten;
# style, test and ci are absent because nothing here is committed under them,
# and anything unrecognised is grouped under "Other" rather than dropped — so a
# changelog never silently loses a commit.
#
# The order is the order the sections print in, running from what a reader most
# wants to know towards what they least do.
COMMIT_TYPES: tuple[tuple[str, str], ...] = (
    ("feat", "Features"),
    ("fix", "Bug fixes"),
    ("perf", "Performance"),
    # Used from the start and recognised late: four real commits, the vault
    # gates and the CCL rename among them, had been landing in "Other".
    ("refactor", "Refactoring"),
    ("docs", "Documentation"),
    ("chore", "Chore"),
    ("build", "Build system"),
)

SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<subject>.+)$"
)

@dataclass(frozen=True)
class Change:
    """One commit, parsed as a Conventional Commit where it is one."""

    sha: str
    subject: str
    type: str = ""      # "" when the subject is not in Conventional Commit form
    scope: str = ""
    breaking: str = ""  # the breaking-change description, empty when not breaking

def parse_commit(sha: str, message: str) -> Change:
    # The message arrives from the remote and ends up on the terminal -- in
    # front of the update-consent prompt, at its most sensitive. Control
    # characters do not survive the trip: an ESC in a commit subject could
    # repaint the changelog the user is deciding on.
    sha = printable(sha)
    message = printable(message)
    lines = message.splitlines()
    subject = lines[0].strip() if lines else ""
    body = "\n".join(lines[1:])

    breaking = ""
    # Runs to a blank line, the next footer, or the end of the message -- not to
    # the end of the line. `.+$` stopped at the first newline, which quietly
    # dropped everything after it, and a breaking change is precisely the kind
    # of note somebody writes two sentences about.
    marker = re.search(
        r"^BREAKING[ -]CHANGE:\s*(.+?)(?=\n\s*\n|\n[A-Za-z][\w-]*:\s|\Z)",
        body, re.MULTILINE | re.DOTALL)
    if marker:
        # Folded to one line: the changelog prints it as a list item, and a
        # newline in the middle of one breaks the column it sits in.
        breaking = " ".join(marker.group(1).split())

    match = SUBJECT_RE.match(subject)
    if not match:
        return Change(sha=sha[:7], subject=subject, breaking=breaking)

    if match.group("bang") and not breaking:
        breaking = match.group("subject").strip()

    return Change(
        sha=sha[:7],
        subject=match.group("subject").strip(),
        type=match.group("type"),
        scope=(match.group("scope") or "").strip(),
        breaking=breaking,
    )

def render_changelog(changes: "tuple[Change, ...]") -> str:
    """Group changes the way Oh My Zsh does, and align the scope column."""
    if not changes:
        return ""

    known = {name for name, _ in COMMIT_TYPES}
    groups: list[tuple[str, list[Change]]] = []

    breaking = [c for c in changes if c.breaking]
    if breaking:
        groups.append(("BREAKING CHANGES", breaking))
    for name, heading in COMMIT_TYPES:
        picked = [c for c in changes if c.type == name]
        if picked:
            groups.append((heading, picked))
    other = [c for c in changes if c.type not in known]
    if other:
        groups.append(("Other", other))

    # One width for the whole changelog, so the subjects line up across groups.
    width = max((len(c.scope) + 2 for c in changes if c.scope), default=0)

    out: list[str] = []
    for heading, picked in groups:
        style = ("bold", "red") if heading == "BREAKING CHANGES" else ("bold",)
        out.append("\n" + paint(f"{heading}:", *style) + "\n")
        for change in picked:
            scope = f"[{change.scope}]" if change.scope else ""
            if heading == "BREAKING CHANGES":
                # The note gets its own block beneath the reference, wrapped,
                # the way Oh My Zsh writes them. It is the one entry in a
                # changelog that is a paragraph rather than a line, and putting
                # a paragraph in the subject column leaves it running off the
                # right of the terminal with the half that says what to do
                # about it out of sight.
                out.append(f"  - {paint(change.sha, 'yellow')}  {paint(scope, 'red')}")
                out.append("")
                for line in _wrapped(change.breaking):
                    out.append(_paint_issue_refs(line))
                out.append("")
                continue
            # A breaking commit is listed twice, as Oh My Zsh does it: once above
            # with what actually breaks, and once here with its ordinary
            # subject. Showing the breaking note in both would bury the change.
            #
            # Pad before colouring: escape sequences have no width on screen but
            # every bit of length to str.format, so padding a painted string
            # silently shifts the column.
            out.append(f"  - {paint(change.sha, 'yellow')}  "
                       f"{paint(scope, 'red')}{' ' * (width - len(scope))}  "
                       f"{_paint_issue_refs(change.subject)}")
    return "\n".join(out)


def _wrapped(text: str, indent: str = "    ") -> list[str]:
    """A paragraph folded to the terminal, or to something sane without one."""
    import shutil
    import textwrap

    # Capped as well as measured: a very wide terminal makes for lines the eye
    # loses its place on, and the fallback covers a pipe, where there is no
    # width to ask about.
    room = min(shutil.get_terminal_size((80, 24)).columns, 100) - len(indent)
    return textwrap.wrap(text, width=max(30, room),
                         initial_indent=indent, subsequent_indent=indent)

def _paint_issue_refs(text: str) -> str:
    """Pick out `(#123)` the way upstream does, so a PR number stands out."""
    if not colour_enabled():
        return text
    return re.sub(r"\(#(\d+)\)", lambda m: f"({paint('#' + m.group(1), 'green')})", text)

def fetch_changes(repo: str, base: str, head: str) -> tuple[int, "tuple[Change, ...]", str]:
    """(ahead_by, changes, status) from one compare call — the same call that
    decides whether we are behind, so the changelog costs no extra request."""
    code, body = fetch(f"{API_ROOT}/repos/{repo}/compare/{base}...{head}")
    if code != 200:
        return 0, (), "unreachable"
    try:
        data = json.loads(body)
    except ValueError:
        return 0, (), "unreadable"
    # Valid JSON is not yet the expected shape: a scalar, a list, or commits
    # that are not objects would raise out of here and take the update check
    # with them. Anything misshapen degrades to "unreadable" instead.
    if not isinstance(data, dict):
        return 0, (), "unreadable"
    raw = data.get("commits")
    changes = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        commit = item.get("commit")
        message = commit.get("message") if isinstance(commit, dict) else ""
        changes.append(parse_commit(str(item.get("sha") or ""), str(message or "")))
    ahead = data.get("ahead_by")
    return (ahead if isinstance(ahead, int) else 0), tuple(changes), str(data.get("status") or "")

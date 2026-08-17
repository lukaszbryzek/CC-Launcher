#!/bin/sh
#
# Cut a release from meta.yaml.
#
#   sh tools/release.sh            # tag and push
#   sh tools/release.sh --dry-run  # say what it would do, change nothing
#
# The tag is derived from `version` in meta.yaml rather than typed in, which is
# the whole point: one source of truth, so the tag cannot disagree with the file
# the updater reads.

set -e

cd "$(dirname "$0")/.."

command_exists() { command -v "$@" >/dev/null 2>&1; }
die() { printf 'fail %s\n' "$1" >&2; exit 1; }

# The other two scripts die on an unknown flag. The one script whose action is
# an irreversible public push must not be the one that shrugs at a typo:
# `--dryrun` used to tag and push for real, in silence.
DRY_RUN=no
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY_RUN=yes ;;
        *) die "unknown option: $1 (only --dry-run exists)" ;;
    esac
    shift
done

[ -f meta.yaml ] || die "no meta.yaml here"

# Prefer a real YAML parse; fall back to a line match so the script still works
# on a machine without PyYAML.
VERSION=$(python3 - <<'PY' 2>/dev/null || true
import re, sys
text = open("meta.yaml", encoding="utf-8").read()
try:
    import yaml
    data = yaml.safe_load(text)
    version = data.get("version") if isinstance(data, dict) else None
except Exception:
    version = None
if not version:
    m = re.search(r"^version:\s*(\S+)\s*$", text, re.M)
    version = m.group(1).strip("\"'") if m else ""
sys.stdout.write(str(version).strip())
PY
)

[ -n "$VERSION" ] || die "meta.yaml has no readable 'version'"
# The full shape, not just the alphabet: git itself refuses "1." and "1..2",
# but ".1" makes a legal tag v.1 that the installer's grep and the updater's
# parser can never see -- a release pushed successfully and received by nobody.
case "$VERSION" in
    *[!0-9.]*|.*|*.|*..*|'') die "version '$VERSION' is not x.y.z" ;;
esac

TAG="v$VERSION"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

printf 'version   %s\ntag       %s\nbranch    %s\nremote    %s\n\n' "$VERSION" "$TAG" "$BRANCH" "$(git remote get-url origin 2>/dev/null || echo '?')"

[ -z "$(git status --porcelain)" ] || die "working tree is dirty — commit first"

# Failure, "exists" and "does not exist" are three different answers from
# ls-remote (--exit-code: 0, 2, anything else), and only one of them means
# "safe to proceed" -- a network blip must not read as a free version number.
probe_remote_tag() {
    git ls-remote --tags --exit-code origin "refs/tags/$TAG" >/dev/null 2>&1
}

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    if probe_remote_tag; then
        die "$TAG already exists on the remote — bump version in meta.yaml"
    fi
    # A tag that exists locally but not on origin is a failed push, not a used
    # version. Telling the user to bump would skip a number for nothing.
    die "$TAG exists locally but not on origin — a failed push; run: git push origin $TAG   (or drop it: git tag -d $TAG)"
fi
remote_state=0
probe_remote_tag || remote_state=$?
[ "$remote_state" = 0 ] && die "$TAG already exists on the remote — bump version in meta.yaml"
[ "$remote_state" = 2 ] || die "could not ask origin about $TAG — check the network and retry"

if [ "$DRY_RUN" = yes ]; then
    printf 'would tag %s at %s and push it\n' "$TAG" "$(git rev-parse --short HEAD)"
    exit 0
fi

git tag -a "$TAG" -m "CC_Launcher $VERSION"
git push origin "$TAG"
printf '  ok tagged and pushed %s\n' "$TAG"

# Deliberately no `gh release create`. A release here is the tag plus the version
# in meta.yaml — both live in git, so any clone can see them and no GitHub-only
# object has to exist for the updater to work.
printf '\nInstalls tracking the release channel will pick this up.\n'

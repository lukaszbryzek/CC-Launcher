#!/bin/sh
#
# CC_Launcher uninstaller. Reverses exactly what tools/install.sh did:
# the clone, the shim, and the alias block in the shell startup files.
#
#   sh ~/.ccl/tools/uninstall.sh
#
# Flags:
#   --yes     skip the confirmations, taking the safe answer to each
#   --purge   also remove your settings file
#
# Your settings are treated as yours. They are not something this program
# generated and can regenerate -- they are the vault path you chose -- so they
# are kept unless you say otherwise, and a reinstall picks them straight back
# up. The cache is the opposite: an update stamp and a lock, both disposable,
# both always removed.
#
# Overridable: CCL_HOME, CCL_BIN, CCL_CACHE, CCL_CONFIG.

set -e

CCL_HOME=${CCL_HOME:-$HOME/.ccl}
CCL_BIN=${CCL_BIN:-$HOME/.local/bin}
CCL_CACHE=${CCL_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/ccl}
CCL_CONFIG=${CCL_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/ccl}
CONFIG_FILE="$CCL_CONFIG/config.yaml"
SHIM_NAME=ccl
BEGIN_MARK='# >>> ccl >>>'
END_MARK='# <<< ccl <<<'
ASSUME_YES=no
PURGE=no

command_exists() { command -v "$@" >/dev/null 2>&1; }

die() { printf 'fail %s\n' "$1" >&2; exit 1; }

# Only $1 used to be looked at, so `--yes` in second place did nothing and an
# unknown flag was ignored in silence. Both matter more now there are two of them.
while [ $# -gt 0 ]; do
    case $1 in
        --) ;;
        --yes)   ASSUME_YES=yes ;;
        --purge) PURGE=yes ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done

# Every one of these paths is overridable from the environment and ends in an
# rm -rf, so each is sanity-checked before anything at all is removed. A stale
# CCL_HOME=~/Projects left over from an experiment must not aim rm -rf at it.
if [ -d "$CCL_HOME" ] \
    && [ ! -f "$CCL_HOME/ccl.py" ] && [ ! -f "$CCL_HOME/cc-launcher.py" ] \
    && ! git -C "$CCL_HOME" config --local ccl.remote >/dev/null 2>&1; then
    die "$CCL_HOME does not look like a CC_Launcher install — refusing to remove it"
fi
case "$CCL_CACHE" in
    */ccl|*/ccl/cache) ;;
    *) die "CCL_CACHE=$CCL_CACHE does not look like ccl's cache directory — refusing" ;;
esac
case "$CCL_CONFIG" in
    */ccl) ;;
    *) die "CCL_CONFIG=$CCL_CONFIG does not look like ccl's config directory — refusing" ;;
esac

# There is only something to keep if a settings file is actually there. An empty
# config directory holds nothing anyone chose, so it goes without a question.
HAVE_CONFIG=no
[ -f "$CONFIG_FILE" ] && HAVE_CONFIG=yes

if [ -t 1 ] && command_exists tput && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
    GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); BOLD=$(tput bold); RESET=$(tput sgr0)
else
    GREEN=; YELLOW=; BOLD=; RESET=
fi

ok()   { printf '%s  ok%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '%swarn%s %s\n' "$YELLOW" "$RESET" "$1" >&2; }

# Two questions now, so the terminal handling is a function instead of being
# written out twice.
#
# `[ -r /dev/tty ]` is not enough: the device can pass a readability test and
# still fail to open when the process has no controlling terminal. Open it
# first, and only prompt once that succeeded. `command` strips exec of its
# special-builtin status, without which the failure kills a non-interactive
# dash outright.
ask() {  # $1 = prompt. Sets ANSWER. Returns 1 when there is no terminal.
    ANSWER=
    if { command exec 3</dev/tty; } 2>/dev/null; then
        printf '%s' "$1"; read -r ANSWER <&3 || ANSWER=; exec 3<&-
    elif [ -t 0 ]; then
        printf '%s' "$1"; read -r ANSWER || ANSWER=
    else
        return 1
    fi
    return 0
}

printf '%sThis will remove:%s\n' "$BOLD" "$RESET"
printf '  %s\n  %s/%s\n  %s\n  the alias block in any shell rc file under %s\n' \
    "$CCL_HOME" "$CCL_BIN" "$SHIM_NAME" "$CCL_CACHE" "$HOME"
if [ "$HAVE_CONFIG" = yes ]; then
    if [ "$PURGE" = yes ]; then
        printf '  %s%s%s\n' "$BOLD" "$CONFIG_FILE" "$RESET"
    else
        printf '\n%sYour settings at %s are kept%s — pass --purge to remove them too.\n' \
            "$YELLOW" "$CONFIG_FILE" "$RESET"
    fi
fi
printf '\n'

if [ "$ASSUME_YES" != yes ]; then
    if ! ask 'Continue? [y/N] '; then
        warn "no terminal to confirm on — pass --yes if you mean it"
        exit 1
    fi
    case "$ANSWER" in [yY]*) ;; *) printf 'Nothing removed.\n'; exit 0 ;; esac

    # Asked only when there is something to lose and no flag already decided.
    # Defaults to keeping, because the answer is a path you chose rather than
    # anything this program produced.
    if [ "$HAVE_CONFIG" = yes ] && [ "$PURGE" != yes ]; then
        if ask "$(printf 'Remove your settings at %s too? [y/N] ' "$CONFIG_FILE")"; then
            case "$ANSWER" in [yY]*) PURGE=yes ;; esac
        fi
    fi
fi

# A BEGIN with no END means someone edited the file by hand. Stripping would
# delete everything after the marker — the same guard install.sh has, absent
# here until a truncated .zshrc proved it was needed in both places.
block_is_sane() {
    awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
        { line = $0; sub(/^[ \t]+/, "", line); sub(/[ \t]+$/, "", line) }
        line == b { begins++ }
        line == e { ends++ }
        END { exit !(begins == ends && begins <= 1) }
    ' "$1"
}

# The alias block first: if this fails, the install is still intact.
#
# Every candidate is checked rather than just the one $SHELL points at now: the
# shell may have changed since install, and a block left behind would alias a
# command that no longer exists.
removed_any=no
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile" \
          "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/ccl.fish"; do
    [ -f "$rc" ] || continue
    grep -qF "$BEGIN_MARK" "$rc" || continue

    if ! block_is_sane "$rc"; then
        warn "$rc has an unbalanced ccl block — leaving it alone; remove the block by hand"
        continue
    fi

    case "$rc" in
        *.zshrc)                checker=zsh ;;
        *.bashrc|*.bash_profile|*.profile) checker=bash ;;
        *ccl.fish)      checker=fish ;;
        *)                      checker= ;;
    esac

    backup="$rc.ccl-backup-$(date +%Y%m%d-%H%M%S)"
    cp -p "$rc" "$backup"
    tmp="$rc.ccl-tmp.$$"
    awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
        { line = $0; sub(/^[ \t]+/, "", line); sub(/[ \t]+$/, "", line) }
        line == b { skip = 1; next }
        line == e { skip = 0; next }
        skip != 1 { keep[++n] = $0 }
        END { while (n > 0 && keep[n] ~ /^[ \t]*$/) n--
              for (i = 1; i <= n; i++) print keep[i] }
    ' "$rc" > "$tmp"
    # In place, not mv: renaming the temp over the path replaces a symlinked rc
    # file (a dotfiles repo) with a plain file and resets its mode. The backup
    # above covers the non-atomic window.
    if ! cat "$tmp" > "$rc"; then
        cp -p "$backup" "$rc" 2>/dev/null || true
        rm -f "$tmp"
        die "could not rewrite $rc — original restored from $backup"
    fi
    rm -f "$tmp"

    if [ -n "$checker" ] && command_exists "$checker" && ! "$checker" -n "$rc" 2>/dev/null; then
        cp -p "$backup" "$rc"
        printf 'The edited %s failed `%s -n` — restored from %s\n' "$rc" "$checker" "$backup" >&2
        exit 1
    fi
    ok "alias block removed from $rc (previous file kept at $backup)"
    removed_any=yes
done
[ "$removed_any" = yes ] || ok "no alias block found in any shell rc file"

if [ -e "$CCL_BIN/$SHIM_NAME" ]; then
    rm -f "$CCL_BIN/$SHIM_NAME"
    ok "removed $CCL_BIN/$SHIM_NAME"
else
    ok "no shim at $CCL_BIN/$SHIM_NAME"
fi

# The cache is never in question: an update stamp and a lock, both disposable.
if [ -d "$CCL_CACHE" ]; then
    rm -rf "$CCL_CACHE"
    ok "removed $CCL_CACHE"
else
    ok "nothing at $CCL_CACHE"
fi

if [ "$HAVE_CONFIG" = yes ] && [ "$PURGE" != yes ]; then
    ok "kept your settings at $CONFIG_FILE"
elif [ -d "$CCL_CONFIG" ]; then
    if [ "$PURGE" = yes ]; then
        rm -rf "$CCL_CONFIG"
        ok "removed $CCL_CONFIG"
    elif rmdir "$CCL_CONFIG" 2>/dev/null; then
        # No settings file and nothing else either: an empty directory holds
        # nothing anyone chose to keep.
        ok "removed empty $CCL_CONFIG"
    else
        # No settings file, but something else lives there — backups, or files
        # a future version put down. Never listed in the summary above, so not
        # this script's to delete.
        ok "kept $CCL_CONFIG (holds files other than a settings file)"
    fi
else
    ok "nothing at $CCL_CONFIG"
fi

# Last, because it is the directory this script may be running from.
if [ -d "$CCL_HOME" ]; then
    rm -rf "$CCL_HOME"
    ok "removed $CCL_HOME"
else
    ok "no install at $CCL_HOME"
fi

printf '\n%sCC_Launcher removed.%s Your OV vault and codebases were not touched.\n' "$BOLD" "$RESET"
if [ "$HAVE_CONFIG" = yes ] && [ "$PURGE" != yes ]; then
    # Worth repeating at the end: this is the one thing left behind, and a
    # reinstall will silently adopt it, which is a surprise if you forgot.
    printf 'Your settings are still at %s and a reinstall will pick them up.\n' "$CONFIG_FILE"
fi
printf '\n'
# The alias is gone from the file but still lives in every shell started before
# now, where it would point at a shim that no longer exists.
printf 'Reload your shell so the stale alias goes away: %sexec zsh%s\n\n' "$BOLD" "$RESET"

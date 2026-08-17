#!/bin/sh
#
# CC_Launcher installer.
#
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/lukaszbryzek/CC-Launcher/main/tools/install.sh)"
#
# Everything below is overridable from the environment, so the installer can be
# driven from a script as well as by hand:
#
#   REPO      GitHub repository to install from   (lukaszbryzek/CC-Launcher)
#   REMOTE    clone URL                           (https://github.com/$REPO.git)
#   BRANCH    branch to track                     (main)
#   CCL_HOME   install directory                   ($HOME/.ccl)
#   CCL_ALIAS  shell alias to create               (ccl)
#   CCL_BIN    directory for the launcher shim     ($HOME/.local/bin)
#   PYTHON    interpreter used to build the venv  (python3)
#
# Flags: --unattended | --alias NAME | --skip-alias | --dir PATH | --nightly
#
# By default this installs the newest published release. --nightly installs the
# branch tip instead; following the branch is a choice, never a default.
#
# The install directory is a real git clone on purpose: the update mechanism
# depends on it being one. User configuration therefore never lives there — an
# update resets the clone and would wipe it.

set -e

REPO=${REPO:-lukaszbryzek/CC-Launcher}
REMOTE=${REMOTE:-https://github.com/${REPO}.git}
BRANCH=${BRANCH:-main}
CCL_HOME=${CCL_HOME:-$HOME/.ccl}
CCL_ALIAS=${CCL_ALIAS:-ccl}
CCL_BIN=${CCL_BIN:-$HOME/.local/bin}
PYTHON=${PYTHON:-python3}

UNATTENDED=no
SKIP_ALIAS=no
NIGHTLY=no
ALIAS_WRITTEN=no
PYTHON_PINNED=no

ENTRY=ccl.py
SHIM_NAME=ccl
BEGIN_MARK='# >>> ccl >>>'
END_MARK='# <<< ccl <<<'

# A failure anywhere after the clone leaves a partial install, and preflight
# refuses to run over one — so the user had to rm -rf a directory a failed run
# created before they could retry. One EXIT trap cleans up every failure path;
# CLEANUP_HOME is armed by clone_repo and disarmed at the end of main.
CLEANUP_HOME=no
on_exit() {
    status=$?
    if [ "$status" -ne 0 ] && [ "$CLEANUP_HOME" = yes ] && [ -d "$CCL_HOME" ]; then
        rm -rf "$CCL_HOME"
        printf 'warn cleaned up the partial install at %s\n' "$CCL_HOME" >&2
    fi
}
trap on_exit EXIT

# --- output ------------------------------------------------------------------

setup_color() {
    if [ -t 1 ] && command_exists tput && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
        RED=$(tput setaf 1); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3)
        BLUE=$(tput setaf 4); BOLD=$(tput bold); RESET=$(tput sgr0)
    else
        RED=; GREEN=; YELLOW=; BLUE=; BOLD=; RESET=
    fi
}

info()  { printf '%s==>%s %s\n' "$BLUE" "$RESET" "$1"; }
ok()    { printf '%s  ok%s %s\n' "$GREEN" "$RESET" "$1"; }
warn()  { printf '%swarn%s %s\n' "$YELLOW" "$RESET" "$1" >&2; }
die()   { printf '%sfail%s %s\n' "$RED" "$RESET" "$1" >&2; exit 1; }

command_exists() { command -v "$@" >/dev/null 2>&1; }

# --- arguments ---------------------------------------------------------------

usage() {
    cat <<'USAGE'
CC_Launcher installer.

  sh -c "$(curl -fsSL https://raw.githubusercontent.com/lukaszbryzek/CC-Launcher/main/tools/install.sh)"

Flags (note the leading -- when invoked through sh -c):
  --unattended     take every default, ask nothing
  --alias NAME     shell alias to create          (default: ccl)
  --skip-alias     install the shim, no alias
  --dir PATH       install directory              (default: ~/.ccl)
  --nightly        track the branch tip instead of the newest release
  --python PATH    interpreter for the virtualenv, skipping the question

Environment: REPO REMOTE BRANCH CCL_HOME CCL_ALIAS CCL_BIN PYTHON
USAGE
}

parse_args() {
    while [ $# -gt 0 ]; do
        case $1 in
            --) ;;
            --unattended) UNATTENDED=yes ;;
            --skip-alias) SKIP_ALIAS=yes ;;
            --nightly) NIGHTLY=yes ;;
            --python) shift; [ $# -gt 0 ] || die "--python needs a path"; PYTHON=$1; PYTHON_PINNED=yes ;;
            --alias) shift; [ $# -gt 0 ] || die "--alias needs a name"; CCL_ALIAS=$1 ;;
            --dir)   shift; [ $# -gt 0 ] || die "--dir needs a path";   CCL_HOME=$1 ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown option: $1" ;;
        esac
        shift
    done
}

# A relative --dir or CCL_BIN would bake a cwd-relative path into the shim and
# the alias, so the command works only from the directory it was installed
# from. Anchored here, once, before anything reads them.
anchor_paths() {
    case "$CCL_HOME" in
        /*) ;;
        '~'|'~/'*) die "CCL_HOME must be absolute (got '$CCL_HOME' — the ~ was not expanded)" ;;
        *) CCL_HOME="$PWD/$CCL_HOME" ;;
    esac
    case "$CCL_BIN" in
        /*) ;;
        '~'|'~/'*) die "CCL_BIN must be absolute (got '$CCL_BIN' — the ~ was not expanded)" ;;
        *) CCL_BIN="$PWD/$CCL_BIN" ;;
    esac
}

# The character check used to live inside the interactive prompt, so
# --unattended and a CCL_ALIAS from the environment skipped it — on exactly the
# path where nobody is watching what lands in the rc file. The paths get the
# same treatment: they are interpolated into a double-quoted alias line and a
# heredoc shim, where a quote or a dollar changes the meaning of the line.
validate_names() {
    case "$CCL_ALIAS" in
        ''|*[!A-Za-z0-9_-]*) die "'$CCL_ALIAS' is not a usable alias name" ;;
    esac
    case "$CCL_HOME$CCL_BIN" in
        *'"'*|*'$'*|*'\'*|*'`'*)
            die 'CCL_HOME and CCL_BIN must not contain ", $, ` or \' ;;
    esac
}

# --- preflight ---------------------------------------------------------------

# What to tell someone whose Python cannot build a virtualenv. Only Debian and
# its derivatives split ensurepip into a separate package, which is why the old
# hardcoded apt hint was wrong everywhere else.
venv_hint() {
    id=; like=
    if [ -r /etc/os-release ]; then
        id=$(. /etc/os-release 2>/dev/null && printf '%s' "${ID:-}")
        like=$(. /etc/os-release 2>/dev/null && printf '%s' "${ID_LIKE:-}")
    fi
    case " $id $like " in
        *" debian "*|*" ubuntu "*) printf 'install python3-venv: apt install python3-venv' ;;
        *" fedora "*|*" rhel "*|*" centos "*) printf 'install python3: dnf install python3' ;;
        *" alpine "*) printf 'install python3 and pip: apk add python3 py3-pip' ;;
        *" arch "*) printf 'install python: pacman -S python' ;;
        *) printf 'the venv module or ensurepip is missing from this Python' ;;
    esac
}


preflight() {
    command_exists git  || die "git is required"
    command_exists curl || die "curl is required"
    command_exists "$PYTHON" || die "$PYTHON not found — set PYTHON=/path/to/python3"

    # prompt_toolkit needs 3.8; the launcher's own annotations are deferred, so
    # 3.9 is a comfortable floor rather than a hard requirement of the code.
    "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' \
        || die "$PYTHON is $("$PYTHON" -V 2>&1 | cut -d" " -f2) — 3.9 or newer required"

    # mktemp, not a predictable $$-suffixed name: on multi-user Linux a
    # pre-planted entry in shared /tmp turns the probe into a misleading
    # "cannot create a virtualenv" failure.
    venv_probe=$(mktemp -d "${TMPDIR:-/tmp}/ccl-venv-probe.XXXXXX") \
        || die "could not create a temporary directory for the venv probe"
    if ! "$PYTHON" -m venv "$venv_probe/venv" >/dev/null 2>&1; then
        rm -rf "$venv_probe"
        die "$PYTHON cannot create a virtualenv ($(venv_hint))"
    fi
    rm -rf "$venv_probe"

    if [ -e "$CCL_HOME" ]; then
        die "$CCL_HOME already exists — remove it, or reinstall elsewhere with --dir PATH"
    fi

    # Not fatal: the launcher only needs `claude` at the moment it launches a
    # session, which may well be after you install it.
    command_exists claude || warn "\`claude\` is not on PATH yet — CC_Launcher needs it to start a session"
}

# --- the alias ---------------------------------------------------------------

# At `sh -c "$(curl ...)"` time stdin is still the terminal, but under
# `curl | sh` it is the script itself. Read the tty directly so both work.
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

ask_alias() {
    [ "$UNATTENDED" = yes ] && return 0
    [ "$SKIP_ALIAS" = yes ] && return 0

    if ! ask "$(printf 'Shell alias for CC_Launcher [%s]: ' "$CCL_ALIAS")"; then
        warn "no terminal to ask on — keeping the default alias '$CCL_ALIAS'"
        return 0
    fi
    [ -n "$ANSWER" ] && CCL_ALIAS=$ANSWER

    case "$CCL_ALIAS" in
        *[!A-Za-z0-9_-]*) die "'$CCL_ALIAS' is not a usable alias name" ;;
    esac
}

check_alias_collision() {
    [ "$SKIP_ALIAS" = yes ] && return 0
    existing=$(command -v "$CCL_ALIAS" 2>/dev/null || true)
    if [ -n "$existing" ] && [ "$existing" != "$CCL_BIN/$SHIM_NAME" ]; then
        warn "'$CCL_ALIAS' already resolves to $existing — the new alias will shadow it"
    fi
}

# --- install steps -----------------------------------------------------------

# The highest version tag on the remote, or empty when there is none.
#
# A release here is a git tag plus a bumped version in meta.yaml — there is no
# GitHub Release object involved, so this asks git rather than an API. That
# needs no token, spends no rate limit, and works against any host.
#
# Sorted by a zero-padded numeric key rather than `sort -V`, which BSD sort on
# macOS does not reliably provide.
latest_tag() {
    # Failure and "no tags" are different answers, and the exit status carries
    # the difference: a network blip during this listing must not silently turn
    # a release-channel install into the branch tip.
    listing=$(git ls-remote --tags --refs "$REMOTE" 2>/dev/null) || return 1
    printf '%s\n' "$listing" \
        | sed 's#.*refs/tags/##' \
        | grep -E '^v?[0-9]+(\.[0-9]+)*$' \
        | awk '{ v = $0; sub(/^v/, "", v); n = split(v, p, ".");
                 printf "%05d%05d%05d\t%s\n", p[1], (n>1?p[2]:0), (n>2?p[3]:0), $0 }' \
        | sort \
        | tail -1 \
        | cut -f2
    return 0
}

clone_repo() {
    info "Cloning $REPO into $CCL_HOME"
    # From here on a failure exit removes the partial install (see on_exit),
    # so preflight's "already exists" refusal never blocks an honest retry.
    CLEANUP_HOME=yes
    git init --quiet "$CCL_HOME"
    (
        cd "$CCL_HOME"
        git config core.eol lf
        git config core.autocrlf false
        # Read back by the updater, exactly as Oh My Zsh does it.
        git config ccl.remote origin
        git config ccl.branch "$BRANCH"
        # The channel the user picked, not a guess from where HEAD landed. It is
        # what decides whether `--version` carries a commit hash.
        git config ccl.channel "$([ "$NIGHTLY" = yes ] && echo nightly || echo release)"
        git remote add origin "$REMOTE"
        # --tags costs nothing here and is what lets `--version` tell a release
        # apart from a commit past it without going to the network.
        git fetch --quiet --depth=1 --tags origin "$BRANCH"
        git checkout --quiet -b "$BRANCH" "origin/$BRANCH"
    ) || die "clone failed"

    # The branch tip is a nightly state by definition, and the default channel is
    # releases — so land on the newest release unless nightly was asked for.
    if [ "$NIGHTLY" = yes ]; then
        ok "on $BRANCH at $(git -C "$CCL_HOME" rev-parse --short HEAD) (nightly, as requested)"
        return 0
    fi
    if ! TAG=$(latest_tag); then
        die "could not list release tags on $REMOTE — check the network and retry (or choose --nightly deliberately)"
    fi
    if [ -n "$TAG" ]; then
        (
            cd "$CCL_HOME"
            git fetch --quiet --depth=1 origin tag "$TAG"
            git reset --quiet --hard "$TAG"
        ) || die "could not check out release $TAG"
        ok "on release $TAG"
    else
        warn "no version tags on the remote — installing $BRANCH at $(git -C "$CCL_HOME" rev-parse --short HEAD)"
    fi
}

# Which interpreter the virtualenv is built on.
#
# Discovery runs from the freshly cloned package rather than being reimplemented
# in sh, because getting it right means executing every candidate: reading the
# filesystem lies. A virtualenv on this machine reported 3.14.6 in its own
# pyvenv.cfg while running 3.14.7.
choose_python() {
    [ "$PYTHON_PINNED" = yes ] && return 0
    # Nobody to ask, so keep whatever the environment already points at.
    # Silently switching interpreters under a scripted install is worse than
    # using the obvious one; --python is there for a deliberate choice.
    [ "$UNATTENDED" = yes ] && return 0

    list=$(cd "$CCL_HOME" && "$PYTHON" -m cc_launcher.pyfind --list 2>/dev/null) || return 0
    [ -n "$list" ] || return 0
    count=$(printf '%s\n' "$list" | grep -c .)
    [ "$count" -gt 1 ] || return 0

    newest_version=$(printf '%s\n' "$list" | head -1 | cut -f1)
    newest_path=$(printf '%s\n' "$list" | head -1 | cut -f2)

    info "Python interpreters found"
    printf '%s\n' "$list" | awk -F'\t' '{ printf "     %d) %-9s %s%s\n", NR, $1, $2, (NR==1 ? "   (newest)" : "") }'

    if ! ask "$(printf 'Use %s? [Y/n, or a number]: ' "$newest_version")"; then
        warn "no terminal to ask on — keeping $PYTHON"
        return 0
    fi

    case "$ANSWER" in
        ""|[yY]|[yY][eE][sS]) chosen=$newest_path ;;
        *[!0-9]*) ok "keeping $PYTHON"; return 0 ;;
        *)
            # Whole numbers only reach sed: the old [0-9]* arm matched "1w
            # /path" too, and handed it to sed as a write command.
            [ "$ANSWER" -ge 1 ] 2>/dev/null && [ "$ANSWER" -le "$count" ] \
                || die "no interpreter numbered $ANSWER"
            chosen=$(printf '%s\n' "$list" | sed -n "${ANSWER}p" | cut -f2)
            [ -n "$chosen" ] || die "no interpreter numbered $ANSWER" ;;
    esac

    # Verify the pick before committing to it: an interpreter can be present and
    # still be unable to build a virtualenv, which is the normal state on Debian
    # until python3-venv is installed.
    probe=$(mktemp -d "${TMPDIR:-/tmp}/ccl-pick-probe.XXXXXX") \
        || { warn "could not create a temporary directory — keeping $PYTHON"; return 0; }
    if "$chosen" -m venv "$probe/venv" >/dev/null 2>&1; then
        rm -rf "$probe"; PYTHON=$chosen
        ok "using $("$PYTHON" -V 2>&1) at $PYTHON"
    else
        rm -rf "$probe"
        warn "$chosen cannot create a virtualenv — keeping $PYTHON"
    fi
}

build_venv() {
    info "Creating virtualenv"
    "$PYTHON" -m venv "$CCL_HOME/.venv" \
        || die "could not create $CCL_HOME/.venv"
    if [ -f "$CCL_HOME/requirements.txt" ]; then
        "$CCL_HOME/.venv/bin/pip" install --quiet --disable-pip-version-check \
            -r "$CCL_HOME/requirements.txt" \
            || die "dependency install failed"
    fi
    ok "venv ready ($("$CCL_HOME/.venv/bin/python" -V 2>&1))"
}

install_shim() {
    info "Installing shim into $CCL_BIN"
    mkdir -p "$CCL_BIN"
    cat > "$CCL_BIN/$SHIM_NAME" <<EOF
#!/bin/sh
# Generated by the CC_Launcher installer. Safe to delete; see tools/uninstall.sh.
#
# Two names are tried because the entry script was cc-launcher.py before 1.1.0.
# Without the second, --set-version onto anything older leaves this pointing at
# a file that is not in that revision, and the install is dead until reinstalled.
for entry in "$CCL_HOME/$ENTRY" "$CCL_HOME/cc-launcher.py"; do
    [ -f "\$entry" ] && exec "$CCL_HOME/.venv/bin/python" "\$entry" "\$@"
done
echo "ccl: no entry script in $CCL_HOME" >&2
exit 1
EOF
    chmod 755 "$CCL_BIN/$SHIM_NAME"
    ok "$CCL_BIN/$SHIM_NAME"

    case ":$PATH:" in
        *":$CCL_BIN:"*) ;;
        *) warn "$CCL_BIN is not on your PATH — the alias will still work, \`$SHIM_NAME\` alone will not" ;;
    esac
}

# Which file the alias belongs in, and which binary can validate it.
#
# Chosen from $SHELL rather than from whichever rc file happens to exist:
# writing an alias into a file the user's shell never reads is worse than not
# writing one at all, and the previous version always wrote ~/.zshrc — creating
# an empty, dead one on any machine whose login shell is bash.
detect_shell_target() {
    RC_FILE=; RC_CHECK=; RC_KIND=; RC_SHELL=$(basename "${SHELL:-}")
    case "$RC_SHELL" in
        zsh)
            RC_FILE="$HOME/.zshrc"; RC_CHECK=zsh; RC_KIND=posix ;;
        bash)
            # The right file is not the same on both systems, and picking wrong
            # writes an alias the shell never reads.
            if [ "$(uname -s)" = Darwin ]; then
                # macOS terminals start LOGIN shells, which read the first of
                # .bash_profile, .bash_login, .profile and never .bashrc — and
                # macOS ships no bridge between them. Prefer a file that already
                # exists, since creating .bash_profile would shadow .profile.
                if [ -f "$HOME/.bash_profile" ]; then RC_FILE="$HOME/.bash_profile"
                elif [ -f "$HOME/.profile" ]; then RC_FILE="$HOME/.profile"
                else RC_FILE="$HOME/.bash_profile"
                fi
            else
                # A Linux terminal opens a NON-login shell, which reads only
                # .bashrc — and every mainstream distribution sources .bashrc
                # from its login file anyway. Verified on Debian, Ubuntu and
                # Fedora: both `bash -ic` and `bash -lic` see it.
                RC_FILE="$HOME/.bashrc"
            fi
            RC_CHECK=bash; RC_KIND=posix ;;
        fish)
            # fish has no aliases — `alias` generates a function. conf.d runs for
            # non-interactive shells too, hence the interactive guard. XDG is
            # honoured because fish honours it: with XDG_CONFIG_HOME set, a file
            # under ~/.config is one fish never reads — and it is where
            # uninstall.sh already looks.
            RC_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/ccl.fish"
            RC_CHECK=fish; RC_KIND=fish ;;
        sh|ash|dash)
            # busybox ash on Alpine, and dash, have no rc file of their own. A
            # POSIX login shell reads ~/.profile, so that is where this belongs.
            RC_FILE="$HOME/.profile"; RC_CHECK=sh; RC_KIND=posix ;;
    esac
}

# Remove a previously written block, so re-running replaces instead of appending.
#
# Markers are compared after trimming, because an indented marker used to be
# missed entirely and the block duplicated. Trailing blank lines are dropped so
# they cannot accumulate one per install.
strip_block() {
    awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
        { line = $0; sub(/^[ \t]+/, "", line); sub(/[ \t]+$/, "", line) }
        line == b { skip = 1; next }
        line == e { skip = 0; next }
        skip != 1 { keep[++n] = $0 }
        END { while (n > 0 && keep[n] ~ /^[ \t]*$/) n--
              for (i = 1; i <= n; i++) print keep[i] }
    ' "$1"
}

# A BEGIN with no END means someone edited the file by hand. Stripping would
# delete everything after the marker, so refuse instead of destroying content.
block_is_sane() {
    awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
        { line = $0; sub(/^[ \t]+/, "", line); sub(/[ \t]+$/, "", line) }
        line == b { begins++ }
        line == e { ends++ }
        END { exit !(begins == ends && begins <= 1) }
    ' "$1"
}
install_alias() {
    if [ "$SKIP_ALIAS" = yes ]; then
        info "Skipping the shell alias (--skip-alias)"
        return 0
    fi

    detect_shell_target
    if [ -z "$RC_FILE" ]; then
        warn "unrecognised shell '${RC_SHELL:-unknown}' — no alias written; run $CCL_BIN/$SHIM_NAME directly"
        return 0
    fi

    info "Adding alias '$CCL_ALIAS' to $RC_FILE"
    mkdir -p "$(dirname "$RC_FILE")"
    [ -f "$RC_FILE" ] || : > "$RC_FILE"

    block_is_sane "$RC_FILE" || die "$RC_FILE has an unbalanced ccl block — fix it by hand first"

    backup="$RC_FILE.ccl-backup-$(date +%Y%m%d-%H%M%S)"
    cp -p "$RC_FILE" "$backup"

    tmp="$RC_FILE.ccl-tmp.$$"
    strip_block "$RC_FILE" > "$tmp"
    {
        printf '\n%s\n' "$BEGIN_MARK"
        if [ "$RC_KIND" = fish ]; then
            printf 'if status is-interactive\n'
            printf '    function %s --wraps %s/%s\n' "$CCL_ALIAS" "$CCL_BIN" "$SHIM_NAME"
            printf '        %s/%s $argv\n' "$CCL_BIN" "$SHIM_NAME"
            printf '    end\nend\n'
        else
            printf 'alias %s="%s/%s"\n' "$CCL_ALIAS" "$CCL_BIN" "$SHIM_NAME"
        fi
        printf '%s\n' "$END_MARK"
    } >> "$tmp"
    # In place, not mv: renaming the temp over the path replaces a symlinked rc
    # file (a dotfiles repo) with a plain file and resets a chmod-600 mode to
    # umask defaults. The backup above covers the non-atomic window.
    if ! cat "$tmp" > "$RC_FILE"; then
        cp -p "$backup" "$RC_FILE" 2>/dev/null || true
        rm -f "$tmp"
        die "could not rewrite $RC_FILE — original restored from $backup"
    fi
    rm -f "$tmp"

    # Validate with the shell that will actually read the file — bash -n accepts
    # zsh-only syntax and vice versa, so cross-checking proves nothing.
    if command_exists "$RC_CHECK" && ! "$RC_CHECK" -n "$RC_FILE" 2>/dev/null; then
        cp -p "$backup" "$RC_FILE"
        die "the edited $RC_FILE failed \`$RC_CHECK -n\` — restored from $backup"
    fi
    ALIAS_WRITTEN=yes
    ok "alias written, previous file kept at $backup"
}

print_success() {
    printf '\n%sCC_Launcher installed.%s\n\n' "$BOLD$GREEN" "$RESET"
    printf '  launcher   %s\n' "$CCL_HOME"
    printf '  entry      %s/%s\n' "$CCL_BIN" "$SHIM_NAME"
    if [ "$ALIAS_WRITTEN" = yes ]; then
        printf '  alias      %s  (in %s)\n' "$CCL_ALIAS" "$RC_FILE"
        printf '\nOpen a new shell, or run: %sexec %s%s\n' "$BOLD" "$RC_SHELL" "$RESET"
        printf 'Then start it with: %s%s%s\n' "$BOLD" "$CCL_ALIAS" "$RESET"
    else
        printf '  alias      none\n'
        printf '\nStart it with: %s%s/%s%s\n' "$BOLD" "$CCL_BIN" "$SHIM_NAME" "$RESET"
    fi
    printf '\nRemove it again with: %ssh %s/tools/uninstall.sh%s\n\n' "$BOLD" "$CCL_HOME" "$RESET"
}

main() {
    # Under `sh -c "$(curl …)" --flag` the first operand becomes $0, not $1, so
    # the flag was silently dropped. Recover it when it looks like one of ours.
    case "$0" in
        --) ;;                       # the conventional placeholder, not an option
        --*) set -- "$0" "$@" ;;
    esac
    parse_args "$@"
    setup_color
    anchor_paths
    validate_names
    preflight
    ask_alias
    check_alias_collision
    clone_repo
    choose_python
    build_venv
    install_shim
    install_alias
    CLEANUP_HOME=no    # the install is complete; nothing left to roll back
    print_success
}

main "$@"

# CC_Launcher

A full-screen terminal picker over an Obsidian vault that launches Claude Code
in the right codebase, with the right context already mounted.

The vault knows which projects exist, which company each belongs to, where its
code lives and what its environment is. CC_Launcher reads that, grades every
project against a set of readiness gates, and starts a session in the matching
repository with the relevant notes loaded — so you pick a project instead of
remembering a path.

On every launch it regenerates two loader files — a vault-wide `CLAUDE.md` and
a per-project one — then execs `claude` with both directories mounted, so the
vault's house rules and the project's own notes expand into the session at
startup.

---

## Install

### macOS and Linux

```sh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/lukaszbryzek/CC-Launcher/main/tools/install.sh)"
```

### Windows

```powershell
irm https://raw.githubusercontent.com/lukaszbryzek/CC-Launcher/main/tools/install.ps1 | iex
```

`iex` cannot pass arguments. To use flags, run the script as a scriptblock:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/lukaszbryzek/CC-Launcher/main/tools/install.ps1))) -Alias cl -Nightly
```

### What the installer does

1. Checks for `git` and a Python it can build a virtualenv with (3.9+).
2. Asks what to call the alias. Default `ccl`.
3. Clones into `~/.ccl` and checks out **the newest published release**.
4. Lists every Python it can find and offers to build the virtualenv on the
   newest one.
5. Writes a shim and an alias, then reports exactly where both went.

Nothing is silent: every step prints what it did, and the alias block is written
between markers with the previous file kept as a timestamped backup.

### Flags

| POSIX | Windows | Meaning |
| --- | --- | --- |
| `--unattended` | `-Unattended` | Take every default, ask nothing |
| `--alias NAME` | `-Alias NAME` | Alias to create (default `ccl`) |
| `--skip-alias` | `-SkipAlias` | Install the shim, write no alias |
| `--dir PATH` | `-Dir PATH` | Install directory (default `~/.ccl`) |
| `--nightly` | `-Nightly` | Track the branch tip instead of releases |
| `--python PATH` | `-Python PATH` | Interpreter for the virtualenv, skipping the question |

Both installers also read `REPO`, `REMOTE`, `BRANCH`, `CCL_HOME`, `CCL_ALIAS`,
`CCL_BIN` and `PYTHON` from the environment.

---

## Usage

```
ccl                    launch the picker
ccl --changelog        page through the project's history, newest first
ccl --config           open the configurator: vault path, projects path, theme
ccl --set-version REF  switch to a release (x.y.z) or a commit hash
ccl --uninstall        remove everything; --purge takes the settings file too
ccl --update           check for a newer release, show what changed, ask
ccl --update-nightly   the same against the branch tip
ccl -v, --version      print the installed version
```

Command names are never abbreviated: `--uni` is an error, not a silent
`--uninstall`.

In the picker: `↑/↓` move, `⏎` opens the launch modal (`claude`, `claude -c`
to continue, `claude -r` to resume), `r` rescans the vault, `t` flips the
theme, `q` quits.

---

## Configuration

The first run opens a configurator asking for two directories; `ccl --config`
reopens it any time. Both default to the layout the tool grew up in:

- **vault dir** — the Obsidian vault to read (default `~/Projects/OV`)
- **projects dir** — where codebases live (default `~/Projects`)

Settings are written to `~/.config/ccl/config.yaml`, safe to edit by hand, and
deliberately **outside the install directory** — an update resets the clone and
would wipe anything kept there. Every save keeps a timestamped backup beside
the file.

A project shows up READY only when every readiness gate passes: the project
note exists, it names a company, that company has a folder with an `About_Me`,
the codebase directory is where the frontmatter says it should be
(`<projects>/<company>/<project>`), an `Environment.md` is present, and the
vault itself has its `Conventions.md`. Anything short of that lands in the
INCOMPLETE pane with the exact gaps to fix.

---

## Updates

A release here is **a git tag plus the `version` in `meta.yaml`** — there is no
GitHub Release object involved. The updater asks `git ls-remote` rather than an
API, so it needs no token and spends no rate limit.

There are two channels, and the one you are on is recorded in git config rather
than guessed from where `HEAD` happens to sit:

- **release** (default) — only published tags.
- **nightly** — the branch tip. You are on it only if you asked: `--nightly` at
  install time, `--update-nightly`, or pinning to a commit.

`ccl` checks for updates **every 6 days**, at most. It is a file read on every
other run and touches the network only when the interval is up. The automatic
check follows releases; it never follows the branch tip.

**Nothing installs without a yes.** The check prints what changed — grouped by
commit type, Oh-My-Zsh style — *before* asking, so you can see what you are
agreeing to while you decide.

```
ccl --set-version 0.3.0     downgrade to a release
ccl --set-version a1b2c3d   pin to a commit (this puts you on the nightly channel)
```

---

## What it writes

| | POSIX | Windows |
| --- | --- | --- |
| Clone | `~/.ccl` | `%USERPROFILE%\.ccl` |
| Shim | `~/.local/bin/ccl` | `%USERPROFILE%\.local\bin\ccl.cmd` |
| Alias | one startup file, chosen from your shell | `$PROFILE.CurrentUserAllHosts` |
| Cache | `~/.cache/ccl` | `%LOCALAPPDATA%\ccl` |
| Config | `~/.config/ccl` | `%APPDATA%\ccl` |

The install directory is a real git clone, because the updater depends on it
being one — which is also why **your configuration must never live there**. An
update resets the clone and would wipe it.

Where the alias goes is decided by the shell, not by whichever file happens to
exist:

- **zsh** → `~/.zshrc`
- **bash on macOS** → `~/.bash_profile`, or `~/.profile` if that already exists
  (terminals start login shells there, and creating `.bash_profile` would shadow
  `.profile`)
- **bash on Linux** → `~/.bashrc` (terminals start non-login shells, which read
  nothing else)
- **fish** → `$XDG_CONFIG_HOME/fish/conf.d/ccl.fish` (default `~/.config`)
- **sh, ash, dash** → `~/.profile`
- **PowerShell** → the profile of the edition you ran the installer from; 5.1
  and 7 read different files, and the installer says so when both are present

The edited file is validated with the shell that will actually read it
(`zsh -n`, `bash -n`, `fish -n`, PowerShell's own parser) and restored from the
backup if it no longer parses.

---

## Uninstall

```sh
ccl --uninstall
```

Removes the clone, the shim, the cache and the alias block from **every**
candidate startup file — not just the one your current shell uses, since the
shell may have changed since you installed. Your settings file survives unless
you pass `--purge`; your vault and your codebases are never touched either way.

---

## Requirements

- Python 3.9 or newer, able to create a virtualenv
- `git`
- A TTY — the picker is a full-screen terminal application
- `claude` on `PATH` — needed to start a session, not to install, so the
  installer warns rather than refusing
- An Obsidian vault at the configured location (default `~/Projects/OV`), with
  `Conventions.md` and `Templates/About_Me_Shared.md` at its root

Dependencies are floors, not pins: `prompt_toolkit>=3.0.50`, `PyYAML>=6.0`.

### Platform support

| | Installer | Uninstaller | Interpreter discovery | Verified |
| --- | --- | --- | --- | --- |
| macOS | `install.sh` | `uninstall.sh` | PATH + Homebrew keg-only dirs | yes, in use |
| Linux | `install.sh` | `uninstall.sh` | PATH + pyenv + uv + `/opt` | Debian 12, Alpine 3.20, Fedora 41 |
| Windows | `install.ps1` | `uninstall.ps1` | PEP 514 registry + PATH | **not on real hardware — see below** |

---

## Development

```sh
git clone git@github.com:lukaszbryzek/CC-Launcher.git
cd CC-Launcher
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python ccl.py --version
```

`ccl.py` is a ten-line entry point; everything lives in `cc_launcher/`.
Every OS-dependent decision sits behind `cc_launcher/platform/`, so adding a
system means writing one file rather than hunting `sys.platform` checks through
the tree.

Commits follow **Conventional Commits** — the changelog the updater shows is
built from them. Types in use: `feat`, `fix`, `perf`, `refactor`, `docs`,
`chore`, `build`.

### Cutting a release

```sh
# bump `version` in meta.yaml, commit, then:
sh tools/release.sh --dry-run
sh tools/release.sh
```

The tag is derived from `meta.yaml` rather than typed in, so it cannot disagree
with the file the updater reads.

---

## Known gaps

- **Windows has never run this on real hardware.** The scripts are clean under
  PSScriptAnalyzer for both 5.1 and 7.0 and the PEP 514 registry walk is
  exercised against a stand-in; untested for real are the Win32 calls in
  `enable_ansi`, actual `winreg` reads, and the OEM encoding of the shim under
  a non-ASCII username.
- **`--set-version` prints no changelog**, unlike `--update`.
- On a stock Windows client the execution policy is `Restricted`, which blocks
  profiles outright. The installer detects this and offers the one-line
  `CurrentUser` fix, but it cannot be assumed away.

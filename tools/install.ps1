#Requires -Version 5.1
<#
.SYNOPSIS
CC_Launcher installer for Windows. The sibling of tools/install.sh, step for step.

.DESCRIPTION
Without arguments:

  irm https://raw.githubusercontent.com/lukaszbryzek/CC-Launcher/main/tools/install.ps1 | iex

`iex` cannot pass arguments, so with them it has to become a scriptblock:

  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/lukaszbryzek/CC-Launcher/main/tools/install.ps1))) -Alias cl -Nightly

Everything is also overridable from the environment, exactly as in install.sh:
REPO, REMOTE, BRANCH, CCL_HOME, CCL_ALIAS, CCL_BIN, PYTHON.

The install directory is a real git clone on purpose: the update mechanism
depends on it being one. User configuration therefore never lives there -- an
update resets the clone and would wipe it.
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'This is a user-facing installer. Coloured console output is the point, and Write-Host needs no virtual terminal mode, which Windows PowerShell 5.1 does not enable.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseShouldProcessForStateChangingFunctions', '',
    Justification = 'Installing is the state change the caller asked for; -WhatIf on an installer is theatre.')]
[CmdletBinding()]
param(
    # Take every default, ask nothing.
    [switch] $Unattended,
    # Shell alias to create.
    [string] $Alias,
    # Install the shim but write no alias.
    [switch] $SkipAlias,
    # Install directory.
    [string] $Dir,
    # Track the branch tip instead of the newest release.
    [switch] $Nightly,
    # Interpreter for the virtualenv, skipping the question.
    [string] $Python
)

$ErrorActionPreference = 'Stop'

# --- settings ----------------------------------------------------------------

function Get-Setting {
    param([string] $Name, [string] $Value, [string] $Default)
    if ($Value) { return $Value }
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }
    return $Default
}

$Script:Repo    = Get-Setting -Name REPO     -Value ''      -Default 'lukaszbryzek/CC-Launcher'
$Script:Remote  = Get-Setting -Name REMOTE   -Value ''      -Default "https://github.com/$Script:Repo.git"
$Script:Branch  = Get-Setting -Name BRANCH   -Value ''      -Default 'main'
$Script:CclHome  = Get-Setting -Name CCL_HOME  -Value $Dir    -Default (Join-Path $HOME '.ccl')
$Script:CclAlias = Get-Setting -Name CCL_ALIAS -Value $Alias  -Default 'ccl'
$Script:CclBin   = Get-Setting -Name CCL_BIN   -Value ''      -Default (Join-Path $HOME '.local\bin')
$Script:Python  = Get-Setting -Name PYTHON   -Value $Python -Default ''

# The switches are copied into script scope alongside everything else, so that
# every function reads its settings from one place rather than reaching up into
# the parameter block through dynamic scoping.
$Script:Unattended = [bool] $Unattended
$Script:SkipAlias  = [bool] $SkipAlias
$Script:Nightly    = [bool] $Nightly

$Script:PythonPinned = [bool] $Python
$Script:AliasWritten = $false
$Script:RcFile       = ''

$Script:Entry     = 'ccl.py'
$Script:ShimName  = 'ccl.cmd'
$Script:BeginMark = '# >>> ccl >>>'
$Script:EndMark   = '# <<< ccl <<<'

# --- output ------------------------------------------------------------------
#
# Write-Host with -ForegroundColor rather than ANSI escapes: it needs no virtual
# terminal mode, so it is correct on Windows PowerShell 5.1 and on consoles too
# old to render an escape sequence.

function Write-Info { param([string] $Message)
    Write-Host '==> ' -ForegroundColor Blue -NoNewline; Write-Host $Message }
function Write-Ok { param([string] $Message)
    Write-Host '  ok ' -ForegroundColor Green -NoNewline; Write-Host $Message }
function Write-Warn { param([string] $Message)
    Write-Host 'warn ' -ForegroundColor Yellow -NoNewline; Write-Host $Message }

# Fatal errors throw rather than call exit: under `irm | iex` there is no script
# to exit from, and `exit` would close the user's shell.
function Stop-Install { param([string] $Message) throw $Message }

function Test-Command { param([string] $Name)
    [bool] (Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue) }

# --- prompting ---------------------------------------------------------------

# The counterpart of install.sh's ask(). There is no /dev/tty to fall back on,
# so the test is whether this session has a console at all; Read-Host in a
# non-interactive host throws instead of returning, hence the catch.
function Read-Answer {
    param([string] $Prompt)
    if ($Script:Unattended) { return $null }
    if (-not [Environment]::UserInteractive) { return $null }
    try { return (Read-Host -Prompt $Prompt) }
    catch { return $null }
}

# --- preflight ---------------------------------------------------------------

# What to tell someone whose Python cannot build a virtualenv. On Windows
# ensurepip is never a separate package, so unlike the Linux hint there is no
# package manager to name -- a broken venv module means a broken install.
function Get-VenvHint {
    'the venv module is unusable in this Python -- reinstall it from python.org'
}

function Resolve-Python {
    <#
    .SYNOPSIS
    Settle on an interpreter to bootstrap with, before the clone exists.
    #>
    if ($Script:Python) {
        if (-not (Test-Path -LiteralPath $Script:Python)) {
            $found = Get-Command $Script:Python -CommandType Application -ErrorAction SilentlyContinue
            if (-not $found) { Stop-Install "$($Script:Python) not found" }
            $Script:Python = $found.Source
        }
        return
    }
    # py.exe first. It is the documented way to reach an interpreter on Windows
    # and, unlike the bare name, it is never the Microsoft Store stub.
    foreach ($candidate in @(
        @{ Exe = 'py';      Args = @('-3', '-c', 'import sys; print(sys.executable)') },
        @{ Exe = 'python';  Args = @('-c', 'import sys; print(sys.executable)') },
        @{ Exe = 'python3'; Args = @('-c', 'import sys; print(sys.executable)') }
    )) {
        if (-not (Test-Command $candidate.Exe)) { continue }
        try { $out = & $candidate.Exe @($candidate.Args) 2>$null } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $out) {
            $Script:Python = ($out | Select-Object -First 1).Trim()
            return
        }
    }
    Stop-Install 'no Python found -- install it from python.org, or pass -Python <path>'
}

function Invoke-Preflight {
    if (-not (Test-Command git)) { Stop-Install 'git is required' }
    Resolve-Python

    # prompt_toolkit needs 3.8; the launcher's own annotations are deferred, so
    # 3.9 is a comfortable floor rather than a hard requirement of the code.
    & $Script:Python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>$null
    if ($LASTEXITCODE -ne 0) {
        $version = (& $Script:Python -V 2>&1) -join ' '
        Stop-Install "$($Script:Python) is $version -- 3.9 or newer required"
    }

    $probe = Join-Path ([IO.Path]::GetTempPath()) "ccl-venv-probe-$PID"
    Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction SilentlyContinue
    & $Script:Python -m venv $probe 2>$null | Out-Null
    $built = ($LASTEXITCODE -eq 0)
    Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction SilentlyContinue
    if (-not $built) { Stop-Install "$($Script:Python) cannot create a virtualenv ($(Get-VenvHint))" }

    if (Test-Path -LiteralPath $Script:CclHome) {
        Stop-Install "$($Script:CclHome) already exists -- remove it, or reinstall elsewhere with -Dir PATH"
    }

    # Not fatal: the launcher only needs `claude` at the moment it launches a
    # session, which may well be after you install it.
    if (-not (Test-Command claude)) {
        Write-Warn '`claude` is not on PATH yet -- CC_Launcher needs it to start a session'
    }
}

# --- the alias ---------------------------------------------------------------

function Request-Alias {
    if ($Script:Unattended -or $Script:SkipAlias) { return }
    $answer = Read-Answer "Shell alias for CC_Launcher [$($Script:CclAlias)]"
    if ($null -eq $answer) {
        Write-Warn "no console to ask on -- keeping the default alias '$($Script:CclAlias)'"
        return
    }
    if ($answer.Trim()) { $Script:CclAlias = $answer.Trim() }
    if ($Script:CclAlias -notmatch '^[A-Za-z0-9_-]+$') {
        Stop-Install "'$($Script:CclAlias)' is not a usable alias name"
    }
}

function Test-AliasCollision {
    if ($Script:SkipAlias) { return }
    $existing = Get-Command $Script:CclAlias -ErrorAction SilentlyContinue
    if ($existing) {
        $what = if ($existing.Source) { $existing.Source } else { $existing.Name }
        Write-Warn "'$($Script:CclAlias)' already resolves to $what -- the new alias will shadow it"
    }
}

# --- install steps -----------------------------------------------------------

# The highest version tag on the remote, or $null when there is none.
#
# A release here is a git tag plus a bumped version in meta.yaml -- there is no
# GitHub Release object involved, so this asks git rather than an API. That
# needs no token, spends no rate limit, and works against any host.
function Get-LatestTag {
    if ($Script:Nightly) { return $null }
    $lines = & git ls-remote --tags --refs $Script:Remote 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $lines) { return $null }

    $best = $null; $bestName = $null
    foreach ($line in $lines) {
        $name = ($line -split 'refs/tags/', 2)[-1].Trim()
        if ($name -notmatch '^v?[0-9]+(\.[0-9]+)*$') { continue }
        $bare = $name -replace '^v', ''
        # [version] refuses a single component, and "1" is a legal tag.
        if ($bare -notmatch '\.') { $bare = "$bare.0" }
        try { $parsed = [version] $bare } catch { continue }
        if ($null -eq $best -or $parsed -gt $best) { $best = $parsed; $bestName = $name }
    }
    return $bestName
}

function Invoke-Git {
    <# Run git inside the clone, throwing with the real message on failure. #>
    param([Parameter(ValueFromRemainingArguments)] [string[]] $Arguments)
    $output = & git -C $Script:CclHome @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $(($output | Out-String).Trim())"
    }
    return $output
}

function Copy-Repository {
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPositionalParameters', '',
        Justification = 'Invoke-Git is deliberately argv-shaped, so git subcommands read here exactly as they would in a shell.')]
    param()
    Write-Info "Cloning $($Script:Repo) into $($Script:CclHome)"
    try {
        & git init --quiet $Script:CclHome 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'git init failed' }

        # Windows checkouts default to CRLF, which would rewrite every shipped
        # .sh and .py on the way in. The launcher runs from this tree, so it is
        # kept byte-identical to the repository.
        Invoke-Git config core.eol lf | Out-Null
        Invoke-Git config core.autocrlf false | Out-Null
        # Read back by the updater, exactly as Oh My Zsh does it.
        Invoke-Git config ccl.remote origin | Out-Null
        Invoke-Git config ccl.branch $Script:Branch | Out-Null
        # The channel the user picked, not a guess from where HEAD landed. It is
        # what decides whether `--version` carries a commit hash.
        Invoke-Git config ccl.channel $(if ($Script:Nightly) { 'nightly' } else { 'release' }) | Out-Null
        Invoke-Git remote add origin $Script:Remote | Out-Null
        # --tags costs nothing here and is what lets `--version` tell a release
        # apart from a commit past it without going to the network.
        Invoke-Git fetch --quiet --depth=1 --tags origin $Script:Branch | Out-Null
        Invoke-Git checkout --quiet -b $Script:Branch "origin/$($Script:Branch)" | Out-Null
    } catch {
        Remove-Item -LiteralPath $Script:CclHome -Recurse -Force -ErrorAction SilentlyContinue
        Stop-Install "clone failed: $($_.Exception.Message)"
    }

    # The branch tip is a nightly state by definition, and the default channel is
    # releases -- so land on the newest release unless nightly was asked for.
    $tag = Get-LatestTag
    if ($Script:Nightly) {
        Write-Ok "on $($Script:Branch) at $((Invoke-Git rev-parse --short HEAD) -join '') (nightly, as requested)"
    } elseif ($tag) {
        try {
            Invoke-Git fetch --quiet --depth=1 origin tag $tag | Out-Null
            Invoke-Git reset --quiet --hard $tag | Out-Null
        } catch {
            Remove-Item -LiteralPath $Script:CclHome -Recurse -Force -ErrorAction SilentlyContinue
            Stop-Install "could not check out release $tag"
        }
        Write-Ok "on release $tag"
    } else {
        Write-Warn "no version tags on the remote -- installing $($Script:Branch) at $((Invoke-Git rev-parse --short HEAD) -join '')"
    }
}

# Which interpreter the virtualenv is built on.
#
# Discovery runs from the freshly cloned package rather than being reimplemented
# here, because getting it right means executing every candidate: reading the
# filesystem lies. On Windows it also means reading the PEP 514 registry keys,
# which is where an all-users or Store install is the only place it is findable.
function Select-Python {
    if ($Script:PythonPinned) { return }
    # Nobody to ask, so keep whatever was resolved. Silently switching
    # interpreters under a scripted install is worse than using the obvious one;
    # -Python is there for a deliberate choice.
    if ($Script:Unattended) { return }

    Push-Location $Script:CclHome
    try { $listing = & $Script:Python -m cc_launcher.pyfind --list 2>$null }
    catch { $listing = $null }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0 -or -not $listing) { return }

    $found = @()
    foreach ($line in $listing) {
        $parts = $line -split "`t", 2
        if ($parts.Count -eq 2) { $found += , @{ Version = $parts[0]; Path = $parts[1] } }
    }
    if ($found.Count -le 1) { return }

    Write-Info 'Python interpreters found'
    for ($i = 0; $i -lt $found.Count; $i++) {
        $suffix = if ($i -eq 0) { '   (newest)' } else { '' }
        Write-Host ('     {0}) {1,-9} {2}{3}' -f ($i + 1), $found[$i].Version, $found[$i].Path, $suffix)
    }

    $answer = Read-Answer "Use $($found[0].Version)? [Y/n, or a number]"
    if ($null -eq $answer) { Write-Warn "no console to ask on -- keeping $($Script:Python)"; return }

    $answer = $answer.Trim()
    if ($answer -eq '' -or $answer -match '^(y|yes)$') {
        $chosen = $found[0].Path
    } elseif ($answer -match '^[0-9]+$') {
        $index = [int] $answer - 1
        if ($index -lt 0 -or $index -ge $found.Count) { Stop-Install "no interpreter numbered $answer" }
        $chosen = $found[$index].Path
    } else {
        Write-Ok "keeping $($Script:Python)"; return
    }

    # Verify the pick before committing to it: an interpreter can be present and
    # still be unable to build a virtualenv.
    $probe = Join-Path ([IO.Path]::GetTempPath()) "ccl-pick-probe-$PID"
    Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction SilentlyContinue
    & $chosen -m venv $probe 2>$null | Out-Null
    $built = ($LASTEXITCODE -eq 0)
    Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction SilentlyContinue
    if ($built) {
        $Script:Python = $chosen
        Write-Ok "using $((& $Script:Python -V 2>&1) -join ' ') at $chosen"
    } else {
        Write-Warn "$chosen cannot create a virtualenv -- keeping $($Script:Python)"
    }
}

function New-Venv {
    Write-Info 'Creating virtualenv'
    $venv = Join-Path $Script:CclHome '.venv'
    & $Script:Python -m venv $venv 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $Script:CclHome -Recurse -Force -ErrorAction SilentlyContinue
        Stop-Install "could not create $venv"
    }
    $requirements = Join-Path $Script:CclHome 'requirements.txt'
    if (Test-Path -LiteralPath $requirements) {
        & (Join-Path $venv 'Scripts\pip.exe') install --quiet --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $Script:CclHome -Recurse -Force -ErrorAction SilentlyContinue
            Stop-Install 'dependency install failed'
        }
    }
    Write-Ok "venv ready ($((& (Join-Path $venv 'Scripts\python.exe') -V 2>&1) -join ' '))"
}

# cmd.exe decodes a batch file in the console's OEM code page, not UTF-8 -- so a
# home directory whose own name is not ASCII turns into a path that does not
# exist. ASCII content is written as ASCII and the question never arises;
# anything else is written in the code page cmd.exe will actually use.
function Write-BatchFile {
    param([string] $Path, [string] $Text)
    $encoding = [Text.Encoding]::ASCII
    if ($Text -match '[^\u0000-\u007F]') {
        try {
            $provider = 'System.Text.CodePagesEncodingProvider' -as [type]
            if ($provider) { [Text.Encoding]::RegisterProvider($provider::Instance) }
            $oem = [System.Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage
            if ($oem -gt 0) { $encoding = [Text.Encoding]::GetEncoding($oem) }
        } catch {
            Write-Warn "could not resolve the OEM code page ($($_.Exception.Message)) -- writing the shim as UTF-8"
            $encoding = [Text.UTF8Encoding]::new($false)
        }
    }
    [IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Install-Shim {
    Write-Info "Installing shim into $($Script:CclBin)"
    New-Item -ItemType Directory -Path $Script:CclBin -Force | Out-Null
    $shim = Join-Path $Script:CclBin $Script:ShimName

    # A .cmd rather than a .ps1: cmd.exe cannot run a .ps1 at all, and a .ps1 is
    # blocked outright under the Restricted execution policy that a stock
    # Windows client still ships with. A batch file is subject to neither.
    # Two names are tried because the entry script was cc-launcher.py before
    # 1.1.0. Without the second, --set-version onto anything older leaves this
    # pointing at a file that revision does not contain.
    $python = Join-Path $Script:CclHome '.venv\Scripts\python.exe'
    Write-BatchFile $shim (@(
        '@echo off',
        'rem Generated by the CC_Launcher installer. Safe to delete; see tools/uninstall.ps1.',
        ('if exist "{0}" "{1}" "{0}" %*' -f (Join-Path $Script:CclHome $Script:Entry), $python),
        ('if exist "{0}" "{1}" "{0}" %*' -f (Join-Path $Script:CclHome 'cc-launcher.py'), $python)
    ) -join "`r`n")

    # Run it. Encoding, quoting and the venv layout are all only claims until
    # the thing actually answers, and a shim that silently does not work is the
    # worst outcome of the whole install.
    $reported = (& $shim --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $reported) {
        Stop-Install "the shim at $shim does not run: $reported"
    }
    Write-Ok "$shim (answers $reported)"

    $onPath = ($env:PATH -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -ieq $Script:CclBin.TrimEnd('\') })
    if (-not $onPath) {
        Write-Warn "$($Script:CclBin) is not on your PATH -- the alias will still work, ``ccl`` alone will not"
    }
}

# Which profile the alias belongs in.
#
# CurrentUserAllHosts, so the alias exists in the console, in VS Code and in the
# ISE alike. The path is taken from $PROFILE rather than built by hand, because
# it differs between PowerShell 7 (Documents\PowerShell) and Windows PowerShell
# 5.1 (Documents\WindowsPowerShell) and moves again when OneDrive redirects the
# Documents folder -- $PROFILE already accounts for all three.
function Get-ProfileTarget {
    # Tested for null rather than for truth: $PROFILE is a string carrying the
    # other paths as note properties, and an empty one is falsy while still
    # holding a perfectly good CurrentUserAllHosts.
    if ($null -eq $PROFILE) { return $null }
    if (-not $PROFILE.CurrentUserAllHosts) { return $null }
    return $PROFILE.CurrentUserAllHosts
}

# Remove a previously written block, so re-running replaces instead of appending.
#
# Markers are compared after trimming, and trailing blank lines are dropped so
# they cannot accumulate one per install.
function Get-WithoutBlock {
    param([string[]] $Lines)
    $kept = New-Object System.Collections.Generic.List[string]
    $skip = $false
    foreach ($line in $Lines) {
        $trimmed = $line.Trim()
        if ($trimmed -eq $Script:BeginMark) { $skip = $true; continue }
        if ($trimmed -eq $Script:EndMark) { $skip = $false; continue }
        if (-not $skip) { $kept.Add($line) }
    }
    while ($kept.Count -gt 0 -and -not $kept[$kept.Count - 1].Trim()) { $kept.RemoveAt($kept.Count - 1) }
    return $kept.ToArray()
}

# A BEGIN with no END means someone edited the file by hand. Stripping would
# delete everything after the marker, so refuse instead of destroying content.
function Test-BlockSane {
    param([string[]] $Lines)
    $begins = @($Lines | Where-Object { $_.Trim() -eq $Script:BeginMark }).Count
    $ends = @($Lines | Where-Object { $_.Trim() -eq $Script:EndMark }).Count
    return ($begins -eq $ends -and $begins -le 1)
}

function Install-Alias {
    if ($Script:SkipAlias) { Write-Info 'Skipping the shell alias (-SkipAlias)'; return }

    $rc = Get-ProfileTarget
    if (-not $rc) {
        Write-Warn "this host exposes no profile path -- no alias written; run $(Join-Path $Script:CclBin $Script:ShimName) directly"
        return
    }
    $Script:RcFile = $rc
    Write-Info "Adding alias '$($Script:CclAlias)' to $rc"

    New-Item -ItemType Directory -Path (Split-Path -Parent $rc) -Force | Out-Null
    if (-not (Test-Path -LiteralPath $rc)) { New-Item -ItemType File -Path $rc -Force | Out-Null }

    # Read and write with this edition's own defaults. PowerShell 7 reads and
    # writes UTF-8; 5.1 reads and writes the ANSI code page. Each round-trips
    # its own profile correctly, and this only ever touches the profile of the
    # edition it is running under.
    $lines = @(Get-Content -LiteralPath $rc)
    if (-not (Test-BlockSane $lines)) {
        Stop-Install "$rc has an unbalanced ccl block -- fix it by hand first"
    }

    $backup = "$rc.ccl-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item -LiteralPath $rc -Destination $backup -Force

    # A function, not Set-Alias: a PowerShell alias is a name for a command and
    # cannot carry the interpreter and the script path that this needs.
    $block = @(
        '',
        $Script:BeginMark,
        ('function {0} {{ & "{1}" "{2}" @args }}' -f
            $Script:CclAlias,
            (Join-Path $Script:CclHome '.venv\Scripts\python.exe'),
            (Join-Path $Script:CclHome $Script:Entry)),
        $Script:EndMark
    )
    Set-Content -LiteralPath $rc -Value (@(Get-WithoutBlock $lines) + $block)

    # Validate with PowerShell's own parser -- the counterpart of `zsh -n`. A
    # profile that does not parse is not merely broken here: it fails on every
    # shell start from now on, which is far worse than a missing alias.
    $errors = $null
    [void] [System.Management.Automation.Language.Parser]::ParseFile($rc, [ref] $null, [ref] $errors)
    if ($errors -and $errors.Count -gt 0) {
        Copy-Item -LiteralPath $backup -Destination $rc -Force
        Stop-Install "the edited $rc does not parse ($($errors[0].Message)) -- restored from $backup"
    }

    $Script:AliasWritten = $true
    Write-Ok "alias written, previous file kept at $backup"
}

# A profile is a script, and Restricted blocks every script -- so the alias would
# be written correctly and still never load. Say so, and offer the one-line fix
# that does not need an administrator.
function Test-ExecutionPolicy {
    if (-not $Script:AliasWritten) { return }
    $effective = Get-ExecutionPolicy
    if ($effective -notin @('Restricted', 'AllSigned')) { return }

    Write-Warn "the execution policy is $effective, so PowerShell will not load your profile and the alias will not exist"
    $answer = Read-Answer 'Set it to RemoteSigned for your user only? [y/N]'
    if ($answer -and $answer.Trim() -match '^(y|yes)$') {
        try {
            Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
            Write-Ok 'execution policy for CurrentUser set to RemoteSigned'
        } catch {
            Write-Warn "could not change it ($($_.Exception.Message)) -- run: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser"
        }
    } else {
        Write-Warn 'run this yourself when you want the alias: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser'
    }
}

# The two PowerShell editions read different profile directories, so an alias
# installed from one is genuinely absent in the other. Say which one was written
# rather than letting it be discovered later.
function Test-OtherEdition {
    if (-not $Script:AliasWritten) { return }
    if ($PSVersionTable.PSEdition -eq 'Core') {
        if (Test-Command powershell) {
            Write-Warn 'Windows PowerShell 5.1 is also installed and reads a different profile -- rerun this from there to get the alias in both'
        }
    } elseif (Test-Command pwsh) {
        Write-Warn 'PowerShell 7 is also installed and reads a different profile -- rerun this from there to get the alias in both'
    }
}

function Write-Success {
    Write-Host ''
    Write-Host 'CC_Launcher installed.' -ForegroundColor Green
    Write-Host ''
    Write-Host "  launcher   $($Script:CclHome)"
    Write-Host "  entry      $(Join-Path $Script:CclBin $Script:ShimName)"
    if ($Script:AliasWritten) {
        Write-Host "  alias      $($Script:CclAlias)  (in $($Script:RcFile))"
        Write-Host ''
        Write-Host 'Open a new shell, or reload the profile with: ' -NoNewline
        Write-Host ". `$PROFILE.CurrentUserAllHosts" -ForegroundColor White
        Write-Host 'Then start it with: ' -NoNewline
        Write-Host $Script:CclAlias -ForegroundColor White
    } else {
        Write-Host '  alias      none'
        Write-Host ''
        Write-Host 'Start it with: ' -NoNewline
        Write-Host (Join-Path $Script:CclBin $Script:ShimName) -ForegroundColor White
    }
    Write-Host ''
    Write-Host 'Remove it again with: ' -NoNewline
    Write-Host "$(Join-Path $Script:CclHome 'tools\uninstall.ps1')" -ForegroundColor White
    Write-Host ''
}

function Invoke-Main {
    Invoke-Preflight
    Request-Alias
    Test-AliasCollision
    Copy-Repository
    Select-Python
    New-Venv
    Install-Shim
    Install-Alias
    Test-ExecutionPolicy
    Test-OtherEdition
    Write-Success
}

try {
    Invoke-Main
} catch {
    Write-Host 'fail ' -ForegroundColor Red -NoNewline
    Write-Host $_.Exception.Message
    # Signals failure to a caller without killing an interactive session, which
    # is what `exit` would do under `irm | iex`.
    $global:LASTEXITCODE = 1
}

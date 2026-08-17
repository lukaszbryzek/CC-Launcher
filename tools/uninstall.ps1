#Requires -Version 5.1
<#
.SYNOPSIS
CC_Launcher uninstaller for Windows. Reverses exactly what tools/install.ps1 did.

.DESCRIPTION
  & "$HOME\.ccl\tools\uninstall.ps1"

Flags:
  -Yes     skip the confirmations, taking the safe answer to each
  -Purge   also remove your settings file

Your settings are treated as yours. They are not something this program
generated and can regenerate -- they are the vault path you chose -- so they are
kept unless you say otherwise, and a reinstall picks them straight back up. The
cache is the opposite: an update stamp and a lock, both disposable, both always
removed.

Overridable from the environment: CCL_HOME, CCL_BIN. `ccl --uninstall` runs this
from a copy taken outside the clone, because the clone is one of the things it
deletes.
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'User-facing script. Coloured console output is the point, and Write-Host needs no virtual terminal mode.')]
[CmdletBinding()]
param(
    # Skip the confirmations, taking the safe answer to each.
    [switch] $Yes,
    # Also remove the settings file, which is otherwise kept.
    [switch] $Purge
)

$ErrorActionPreference = 'Stop'

function Get-Setting {
    param([string] $Name, [string] $Default)
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }
    return $Default
}

# Copied into script scope so every function reads its settings from one
# place, rather than reaching up into the parameter block.
$Script:AssumeYes = [bool] $Yes
$Script:Purge     = [bool] $Purge

$CclHome   = Get-Setting -Name CCL_HOME -Default (Join-Path $HOME '.ccl')
$CclBin    = Get-Setting -Name CCL_BIN  -Default (Join-Path $HOME '.local\bin')
$ShimName = 'ccl.cmd'
# Where the Windows platform layer puts throw-away state and config. Spelled out
# with if rather than ?? because ?? is PowerShell 7 syntax and this has to parse
# under Windows PowerShell 5.1, which is the edition a stock Windows ships with.
$LocalAppData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME 'AppData\Local' }
$RoamingAppData = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $HOME 'AppData\Roaming' }
$CclCache  = Join-Path $LocalAppData 'ccl'
$CclConfig = Join-Path $RoamingAppData 'ccl'
$ConfigFile = Join-Path $CclConfig 'config.yaml'

# There is only something to keep if a settings file is actually there. An empty
# config directory holds nothing anyone chose, so it goes without a question.
$Script:HaveConfig = Test-Path -LiteralPath $ConfigFile

$BeginMark = '# >>> ccl >>>'
$EndMark   = '# <<< ccl <<<'

function Write-Ok { param([string] $Message)
    Write-Host '  ok ' -ForegroundColor Green -NoNewline; Write-Host $Message }
function Write-Warn { param([string] $Message)
    Write-Host 'warn ' -ForegroundColor Yellow -NoNewline; Write-Host $Message }

# Two questions now, so the console handling is a function instead of being
# written out twice. UserInteractive stays true under -NonInteractive, where
# Read-Host throws rather than returning, so both have to be handled.
function Read-Answer {
    param([string] $Prompt)
    if (-not [Environment]::UserInteractive) { return $null }
    try { return (Read-Host -Prompt $Prompt) } catch { return $null }
}

# Every profile that could hold the block, not just the one this edition reads.
#
# The install may have been done from the other PowerShell edition, or from
# both, and a block left behind would define an alias pointing at a launcher
# that no longer exists -- which is a worse state than never having installed.
function Get-CandidateProfile {
    $paths = New-Object System.Collections.Generic.List[string]
    if ($null -ne $PROFILE) {
        foreach ($name in 'CurrentUserAllHosts', 'CurrentUserCurrentHost') {
            if ($PROFILE.$name) { $paths.Add($PROFILE.$name) }
        }
    }
    # The other edition's directory, which $PROFILE never points at. Both
    # spellings are listed because whichever edition is running, the other one
    # is the one being missed.
    foreach ($documents in @(
        [Environment]::GetFolderPath('MyDocuments'),
        (Join-Path $HOME 'Documents'),
        (Join-Path $HOME 'OneDrive\Documents')
    )) {
        if (-not $documents) { continue }
        foreach ($dir in 'PowerShell', 'WindowsPowerShell') {
            foreach ($file in 'Profile.ps1', 'Microsoft.PowerShell_profile.ps1') {
                $paths.Add((Join-Path $documents (Join-Path $dir $file)))
            }
        }
    }
    return ($paths | Sort-Object -Unique)
}

function Get-WithoutBlock {
    param([string[]] $Lines)
    $kept = New-Object System.Collections.Generic.List[string]
    $skip = $false
    foreach ($line in $Lines) {
        $trimmed = $line.Trim()
        if ($trimmed -eq $BeginMark) { $skip = $true; continue }
        if ($trimmed -eq $EndMark) { $skip = $false; continue }
        if (-not $skip) { $kept.Add($line) }
    }
    while ($kept.Count -gt 0 -and -not $kept[$kept.Count - 1].Trim()) { $kept.RemoveAt($kept.Count - 1) }
    return $kept.ToArray()
}

function Invoke-Uninstall {
    Write-Host 'This will remove:'
    foreach ($item in @($CclHome, (Join-Path $CclBin $ShimName), $CclCache)) {
        Write-Host "  $item"
    }
    Write-Host "  the alias block in any PowerShell profile under $HOME"
    if ($Script:HaveConfig) {
        if ($Script:Purge) {
            Write-Host "  $ConfigFile"
        } else {
            Write-Host ''
            Write-Host "Your settings at $ConfigFile are kept" -ForegroundColor Yellow -NoNewline
            Write-Host ' -- pass -Purge to remove them too.'
        }
    }
    Write-Host ''

    if (-not $Script:AssumeYes) {
        $answer = Read-Answer 'Continue? [y/N]'
        if ($null -eq $answer) {
            Write-Warn 'no console to confirm on -- pass -Yes if you mean it'
            $global:LASTEXITCODE = 1
            return
        }
        if ($answer -notmatch '^(y|yes)$') { Write-Host 'Nothing removed.'; return }

        # Asked only when there is something to lose and no flag already decided.
        # Defaults to keeping, because the answer is a path you chose rather than
        # anything this program produced.
        if ($Script:HaveConfig -and -not $Script:Purge) {
            $keep = Read-Answer "Remove your settings at $ConfigFile too? [y/N]"
            if ($keep -and $keep -match '^(y|yes)$') { $Script:Purge = $true }
        }
    }

    # The alias block first: if this fails, the install is still intact.
    $removedAny = $false
    foreach ($rc in @(Get-CandidateProfile)) {
        if (-not (Test-Path -LiteralPath $rc)) { continue }
        $lines = @(Get-Content -LiteralPath $rc)
        if (-not ($lines | Where-Object { $_.Trim() -eq $BeginMark })) { continue }

        $backup = "$rc.ccl-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item -LiteralPath $rc -Destination $backup -Force
        Set-Content -LiteralPath $rc -Value @(Get-WithoutBlock $lines)

        # A profile that no longer parses breaks every future shell start, so it
        # is put back rather than left in that state.
        $errors = $null
        [void] [System.Management.Automation.Language.Parser]::ParseFile($rc, [ref] $null, [ref] $errors)
        if ($errors -and $errors.Count -gt 0) {
            Copy-Item -LiteralPath $backup -Destination $rc -Force
            Write-Host "The edited $rc no longer parses ($($errors[0].Message)) -- restored from $backup"
            $global:LASTEXITCODE = 1
            return
        }
        Write-Ok "alias block removed from $rc (previous file kept at $backup)"
        $removedAny = $true
    }
    if (-not $removedAny) { Write-Ok 'no alias block found in any PowerShell profile' }

    $shim = Join-Path $CclBin $ShimName
    if (Test-Path -LiteralPath $shim) {
        Remove-Item -LiteralPath $shim -Force
        Write-Ok "removed $shim"
    } else {
        Write-Ok "no shim at $shim"
    }

    # The cache is never in question: an update stamp and a lock, both disposable.
    if (Test-Path -LiteralPath $CclCache) {
        Remove-Item -LiteralPath $CclCache -Recurse -Force
        Write-Ok "removed $CclCache"
    } else {
        Write-Ok "nothing at $CclCache"
    }

    if ($Script:HaveConfig -and -not $Script:Purge) {
        Write-Ok "kept your settings at $ConfigFile"
    } elseif (Test-Path -LiteralPath $CclConfig) {
        # Either purging, or the directory holds no settings file and so holds
        # nothing anyone chose to keep.
        Remove-Item -LiteralPath $CclConfig -Recurse -Force
        Write-Ok "removed $CclConfig"
    } else {
        Write-Ok "nothing at $CclConfig"
    }

    # Last, because it is the directory this script may have been copied from.
    if (Test-Path -LiteralPath $CclHome) {
        Remove-Item -LiteralPath $CclHome -Recurse -Force
        Write-Ok "removed $CclHome"
    } else {
        Write-Ok "no install at $CclHome"
    }

    Write-Host ''
    Write-Host 'CC_Launcher removed.' -ForegroundColor Green -NoNewline
    Write-Host ' Your OV vault and codebases were not touched.'
    if ($Script:HaveConfig -and -not $Script:Purge) {
        # Worth repeating at the end: this is the one thing left behind, and a
        # reinstall will silently adopt it, which is a surprise if you forgot.
        Write-Host "Your settings are still at $ConfigFile and a reinstall will pick them up."
    }
    Write-Host ''
    # The function is gone from the profile but still defined in every session
    # started before now, where it would call a launcher that no longer exists.
    Write-Host 'Open a new shell so the stale alias goes away.'
    Write-Host ''
}

try {
    Invoke-Uninstall
} catch {
    Write-Host 'fail ' -ForegroundColor Red -NoNewline
    Write-Host $_.Exception.Message
    $global:LASTEXITCODE = 1
}

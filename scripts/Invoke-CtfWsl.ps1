#requires -Version 5.1

[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Distribution,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CtfArguments
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent $PSScriptRoot
if (-not $Distribution) {
    $config = Get-Content -LiteralPath (Join-Path $workspaceRoot '.ctf\config.json') -Raw | ConvertFrom-Json
    $Distribution = [string]$config.linux_environment
}
if ([string]::IsNullOrWhiteSpace($Distribution)) {
    throw 'A WSL distribution is required.'
}

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) {
    throw 'wsl.exe was not found.'
}

$resolvedWorkspace = [System.IO.Path]::GetFullPath($workspaceRoot)
if ($resolvedWorkspace -notmatch '^([A-Za-z]):[\\/]*(.*)$') {
    throw "The workspace is not on a drive that can be mapped into WSL: $resolvedWorkspace"
}
$drive = $Matches[1].ToLowerInvariant()
$tail = $Matches[2].Replace('\', '/').TrimStart('/')
$wslRoot = "/mnt/$drive/$tail".TrimEnd('/')

$wslHome = (& $wsl.Source -d $Distribution -- sh -lc 'printf "%s" "$HOME"' | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($wslHome)) {
    throw "Unable to resolve the default user's home in $Distribution."
}
$python = "$wslHome/.ctf-tools/venv/bin/python"
& $wsl.Source -d $Distribution -- test -x $python
if ($LASTEXITCODE -ne 0) {
    throw "CTF virtualenv not found; run scripts\Install-CtfWsl.ps1 first."
}

$forwarded = @(
    foreach ($argument in $CtfArguments) {
        if ($argument -match '^([A-Za-z]):[\\/]*(.*)$') {
            $argumentDrive = $Matches[1].ToLowerInvariant()
            $argumentTail = $Matches[2].Replace('\', '/').TrimStart('/')
            "/mnt/$argumentDrive/$argumentTail"
        }
        elseif ($argument -match '^(?:\.\\)?c\\') {
            $argument.Replace('\', '/')
        }
        else {
            $argument
        }
    }
)

& $wsl.Source -d $Distribution -- $python "$wslRoot/scripts/ctf.py" @forwarded
exit $LASTEXITCODE

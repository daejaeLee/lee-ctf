#requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Distribution,
    [switch]$SkipAptRefresh
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $workspaceRoot '.ctf\config.json'

if (-not $Distribution) {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $Distribution = [string]$config.linux_environment
}
if ([string]::IsNullOrWhiteSpace($Distribution)) {
    throw 'A WSL distribution is required.'
}

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) {
    throw 'wsl.exe was not found.'
}

function Invoke-CheckedWsl {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [switch]$AllowFailure
    )

    Write-Host "[RUN ] $Label"
    & $wsl.Source @Arguments
    if ($LASTEXITCODE -ne 0) {
        if ($AllowFailure) {
            Write-Warning "$Label reported exit code $LASTEXITCODE; the final verifier will decide whether required tools are complete."
            return
        }
        throw "$Label failed with exit code $LASTEXITCODE."
    }
    Write-Host "[PASS] $Label"
}

$resolvedWorkspace = [System.IO.Path]::GetFullPath($workspaceRoot)
if ($resolvedWorkspace -match '^([A-Za-z]):[\\/]*(.*)$') {
    $drive = $Matches[1].ToLowerInvariant()
    $tail = $Matches[2].Replace('\', '/').TrimStart('/')
    $wslRoot = "/mnt/$drive/$tail".TrimEnd('/')
}
else {
    $wslRoot = (& $wsl.Source -d $Distribution -- wslpath -a $resolvedWorkspace | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($wslRoot)) {
        throw "Unable to map the workspace into WSL distribution $Distribution."
    }
}
$installer = "$wslRoot/scripts/install_ctf_tools.sh"

if (-not $SkipAptRefresh) {
    Invoke-CheckedWsl `
        -Arguments @('-d', $Distribution, '-u', 'root', '--', 'timeout', '900s', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'update', '-q') `
        -Label 'Kali package index'
}

$buildDependencies = @(
    'python3-venv',
    'python3-dev',
    'libssl-dev',
    'libgmp-dev',
    'build-essential',
    'rustc',
    'cargo',
    'ruby-full',
    'golang-go',
    'ffuf'
)
Invoke-CheckedWsl `
    -Arguments (@('-d', $Distribution, '-u', 'root', '--', 'timeout', '1800s', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y') + $buildDependencies) `
    -Label 'Kali build and language dependencies'

Invoke-CheckedWsl `
    -Arguments @('-d', $Distribution, '-u', 'root', '--', 'timeout', '3600s', 'bash', $installer, 'apt') `
    -Label 'Pinned apt CTF tools' `
    -AllowFailure
Invoke-CheckedWsl `
    -Arguments @('-d', $Distribution, '--', 'timeout', '3600s', 'bash', $installer, 'python') `
    -Label 'Pinned Python CTF tools and compatibility overlay'
Invoke-CheckedWsl `
    -Arguments @('-d', $Distribution, '-u', 'root', '--', 'timeout', '1800s', 'bash', $installer, 'gems') `
    -Label 'Pinned Ruby CTF tools'
Invoke-CheckedWsl `
    -Arguments @('-d', $Distribution, '--', 'timeout', '300s', 'bash', $installer, '--verify') `
    -Label 'Kali 58-item CTF tool verification'

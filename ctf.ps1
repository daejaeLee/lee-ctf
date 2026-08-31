#requires -Version 5.1

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error 'Python 3 is required. Install it, then run .\ctf.ps1 doctor.'
    exit 1
}

& $python.Source (Join-Path $PSScriptRoot 'scripts\ctf.py') @args
exit $LASTEXITCODE

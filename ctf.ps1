#requires -Version 5.1

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$python = Get-Command py -ErrorAction SilentlyContinue
$pythonPrefix = @()
if ($python) {
    $pythonPrefix = @('-3')
}
else {
    $python = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error 'Python 3 is required. Install it, then run .\ctf.ps1 doctor.'
    exit 1
}

& $python.Source @pythonPrefix -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Python 3.10 or newer is required.'
    exit 1
}

& $python.Source @pythonPrefix (Join-Path $PSScriptRoot 'scripts\ctf.py') @args
exit $LASTEXITCODE

#requires -Version 5.1
<#
.SYNOPSIS
Runs a WMux browser command through its installed Node CLI.

.DESCRIPTION
WMux's bundled PowerShell shim eventually invokes a cmd.exe shim.  That can
reinterpret browser-eval JavaScript containing cmd metacharacters.  This
wrapper resolves the installed WMux package and runs resources\cli\wmux.js
directly with Node, preserving each PowerShell argument as a single CLI
argument.

Use a surface ID discovered for the current WMux session.  Supplying
--surface explicitly prevents an action from falling back to an unrelated
browser panel.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$BrowserArgs
)

$ErrorActionPreference = 'Stop'

function Resolve-WmuxCli {
    $wmux = Get-Command wmux -ErrorAction SilentlyContinue
    if (-not $wmux -or -not $wmux.Source) {
        throw 'WMux was not found on PATH. Install WMux or add its cli-bin-ps directory to PATH.'
    }

    $shimPath = $wmux.Source
    if ($shimPath -notmatch '\\resources\\cli-bin-ps\\wmux\.ps1$') {
        throw "Unsupported WMux command path: $shimPath"
    }

    $installRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $shimPath))
    $cliPath = Join-Path $installRoot 'resources\cli\wmux.js'
    if (-not (Test-Path -LiteralPath $cliPath -PathType Leaf)) {
        throw "WMux CLI was not found at $cliPath"
    }

    return $cliPath
}

$node = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $node) { $node = Get-Command node -ErrorAction Stop }

& $node.Source (Resolve-WmuxCli) 'browser' @BrowserArgs
exit $LASTEXITCODE

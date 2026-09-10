[CmdletBinding()]
param(
    [int]$StartupTimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
$cdpVersionUrl = 'http://127.0.0.1:9222/json/version'

function Test-WmuxCdpProxy {
    try {
        $request = [System.Net.WebRequest]::Create($cdpVersionUrl)
        $request.Method = 'GET'
        $request.Timeout = 1000
        $request.ReadWriteTimeout = 1000
        $response = $request.GetResponse()
        try { return ([int]$response.StatusCode -eq 200) }
        finally { $response.Close() }
    }
    catch { return $false }
}

function Resolve-WmuxExecutable {
    if ($env:WMUX_EXE -and (Test-Path -LiteralPath $env:WMUX_EXE -PathType Leaf)) {
        return $env:WMUX_EXE
    }

    $wmux = Get-Command wmux -ErrorAction SilentlyContinue
    if (-not $wmux -or -not $wmux.Source) {
        throw 'WMux was not found. Set WMUX_EXE to the full path of wmux.exe.'
    }

    if ($wmux.Source -match '\\resources\\cli-bin-ps\\wmux\.ps1$') {
        $root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $wmux.Source))
        $candidate = Join-Path $root 'wmux.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }

    throw 'Could not derive wmux.exe from the wmux CLI. Set WMUX_EXE to its full path.'
}

if (-not (Test-WmuxCdpProxy)) {
    Start-Process -FilePath (Resolve-WmuxExecutable) | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 250
        if (Test-WmuxCdpProxy) { break }
    } while ([DateTime]::UtcNow -lt $deadline)

    if (-not (Test-WmuxCdpProxy)) {
        throw "WMux did not expose its CDP proxy at $cdpVersionUrl within $StartupTimeoutSeconds seconds."
    }
}

$npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
if (-not $npx) { $npx = Get-Command npx -ErrorAction Stop }

# Keep stdin/stdout attached: they carry the MCP JSON-RPC transport.
& $npx.Source '-y' 'chrome-devtools-mcp@latest' '--browser-url=http://127.0.0.1:9222'
exit $LASTEXITCODE

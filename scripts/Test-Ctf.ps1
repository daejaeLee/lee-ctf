[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExecutable = 'py'
    $pythonPrefix = @('-3')
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExecutable = 'python'
    $pythonPrefix = @()
}
else {
    throw 'Python 3 was not found on PATH.'
}

function Invoke-CheckedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$PythonArguments,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    Write-Host "[RUN ] $Label"
    $allArguments = @($pythonPrefix) + $PythonArguments
    & $pythonExecutable @allArguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
    Write-Host "[PASS] $Label"
}

function Invoke-CheckedPowerShellFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [string[]]$ScriptArguments = @(),
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    Write-Host "[RUN ] $Label"
    & (Join-Path $PSHOME 'powershell.exe') -NoProfile -ExecutionPolicy Bypass -File $Path @ScriptArguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
    Write-Host "[PASS] $Label"
}

Push-Location $workspaceRoot
try {
    $powerShellFiles = @(
        Get-ChildItem -LiteralPath $workspaceRoot -Filter '*.ps1' -File
        Get-ChildItem -LiteralPath (Join-Path $workspaceRoot 'scripts') -Filter '*.ps1' -File
    )
    foreach ($powerShellFile in $powerShellFiles) {
        [void][scriptblock]::Create(
            [System.IO.File]::ReadAllText($powerShellFile.FullName)
        )
    }
    Write-Host "[PASS] PowerShell 5.1 syntax ($($powerShellFiles.Count) files)"

    Invoke-CheckedPowerShellFile `
        -Path (Join-Path $workspaceRoot 'ctf.ps1') `
        -ScriptArguments @('--help') `
        -Label 'PowerShell CLI entrypoint'

    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    $configPath = Join-Path $workspaceRoot '.ctf\config.json'
    if ($wsl -and (Test-Path -LiteralPath $configPath)) {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $distribution = [string]$config.linux_environment
        if (-not [string]::IsNullOrWhiteSpace($distribution)) {
            $resolvedWorkspace = [System.IO.Path]::GetFullPath($workspaceRoot)
            if ($resolvedWorkspace -notmatch '^([A-Za-z]):[\\/]*(.*)$') {
                throw "Cannot map workspace path into WSL: $resolvedWorkspace"
            }
            $drive = $Matches[1].ToLowerInvariant()
            $tail = $Matches[2].Replace('\', '/').TrimStart('/')
            $wslRoot = "/mnt/$drive/$tail".TrimEnd('/')
            & $wsl.Source -d $distribution -- bash -n "$wslRoot/scripts/install_ctf_tools.sh"
            if ($LASTEXITCODE -ne 0) {
                throw "Bash installer syntax failed with exit code $LASTEXITCODE."
            }
            Write-Host '[PASS] Bash installer syntax'

            $savedErrorActionPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'SilentlyContinue'
                & $wsl.Source -d $distribution -- bash "$wslRoot/scripts/install_ctf_tools.sh" python all 2>&1 | Out-Null
                $argumentGuardExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $savedErrorActionPreference
            }
            if ($argumentGuardExitCode -ne 2) {
                throw "Bash installer argument guard returned $argumentGuardExitCode instead of 2."
            }
            Write-Host '[PASS] Bash installer argument guard'

            Invoke-CheckedPowerShellFile `
                -Path (Join-Path $workspaceRoot 'scripts\Invoke-CtfWsl.ps1') `
                -ScriptArguments @('--help') `
                -Label 'WSL CLI entrypoint'
        }
    }

    $pythonFiles = @(
        Get-ChildItem -LiteralPath (Join-Path $workspaceRoot 'scripts') -Filter '*.py' -File -Recurse
        Get-ChildItem -LiteralPath (Join-Path $workspaceRoot 'tests') -Filter '*.py' -File -Recurse
    )
    if ($pythonFiles.Count -eq 0) {
        throw 'No Python scripts or tests were found.'
    }
    $compileArguments = @('-m', 'py_compile') + @($pythonFiles.FullName)
    Invoke-CheckedPython -PythonArguments $compileArguments -Label 'Python syntax'

    Invoke-CheckedPython `
        -PythonArguments @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v') `
        -Label 'Unit tests'

    Invoke-CheckedPython -PythonArguments @('scripts/ctf.py', '--help') -Label 'CLI help'

    $doctorHelpArguments = @($pythonPrefix) + @('scripts/ctf.py', 'doctor', '--help')
    $doctorHelp = (& $pythonExecutable @doctorHelpArguments 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Doctor help probe failed with exit code $LASTEXITCODE."
    }
    if ($doctorHelp -match '(?m)--project-only\b') {
        Invoke-CheckedPython `
            -PythonArguments @('scripts/ctf.py', 'doctor', '--project-only') `
            -Label 'Project doctor'
    }
    else {
        Write-Host '[INFO] doctor --project-only is unavailable; running the compatible full doctor.'
        Invoke-CheckedPython -PythonArguments @('scripts/ctf.py', 'doctor') -Label 'Project doctor'
    }

    Write-Host '[PASS] CTF workspace smoke test completed.'
}
finally {
    Pop-Location
}

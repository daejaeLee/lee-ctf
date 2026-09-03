#requires -Version 5.1
<#
.SYNOPSIS
Starts Codex with the CTF-focused plugin profile for this invocation only.

.DESCRIPTION
Codex 0.153.0 persists plugin state globally and exposes no skill-level
disable control.  This wrapper leaves the user's global configuration and
plugin installations untouched, while preventing non-CTF plugins (including
the all-or-nothing ECC bundle) from being loaded into this session.
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CodexArgs
)

$ErrorActionPreference = 'Stop'

$codex = Get-Command codex -ErrorAction SilentlyContinue
if (-not $codex) {
    throw 'codex was not found on PATH.'
}

# Browser stays enabled for authenticated CTF web flows. The project CTF
# skills remain available independently of these plugin overrides.
$disabledPlugins = @(
    'ecc@ecc',
    'documents@openai-primary-runtime',
    'pdf@openai-primary-runtime',
    'spreadsheets@openai-primary-runtime',
    'presentations@openai-primary-runtime',
    'template-creator@openai-primary-runtime',
    'sites@openai-bundled',
    'computer-use@openai-bundled',
    'visualize@openai-bundled'
)

# In Codex 0.153.0, plugin-management, openai-templates, and
# deep-research-work have the INSTALLED_BY_DEFAULT policy. The CLI reports
# them enabled even with a per-invocation `enabled=false` override, so they
# are intentionally not represented here as disabled.

$invokeArgs = @()
foreach ($plugin in $disabledPlugins) {
    $invokeArgs += '-c'
    $invokeArgs += ('plugins."{0}".enabled=false' -f $plugin)
}
$invokeArgs += $CodexArgs

& $codex.Source @invokeArgs
exit $LASTEXITCODE

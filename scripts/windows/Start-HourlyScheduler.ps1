<#
.SYNOPSIS
  Start the DayTrade RTH hourly orchestrator (Node) on Windows.

.DESCRIPTION
  Loads keys from %USERPROFILE%\.daytrade\alpaca.env (APCA_* + CURSOR_API_KEY),
  then runs @daytrade/orchestrator in a loop (10:00-15:00 America/New_York).

  Default mode: prep (Python news + packs) -> SDK local fan-out -> settle (dry-run).
  Pass -Submit only when you intentionally want paper orders.

  Falls back to Python hourly_scheduler.py if Node/services are missing.
#>
param(
    [string]$StoreRoot = $(if ($env:DAYTRADE_STORE) { $env:DAYTRADE_STORE } else { "" }),
    [string]$Node = $(if ($env:DAYTRADE_NODE) { $env:DAYTRADE_NODE } else { "node" }),
    [string]$Python = $(if ($env:DAYTRADE_PYTHON) { $env:DAYTRADE_PYTHON } else { "py" }),
    [ValidateSet("prep", "fanout", "settle", "full", "prep-then-settle")]
    [string]$Phase = "prep-then-settle",
    [int]$ProposalWaitMinutes = 20,
    [switch]$Submit,
    [switch]$CatchUp,
    [switch]$Once,
    [string]$Hour,
    [switch]$UsePythonFallback
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here "Load-AlpacaEnv.ps1")

if (-not $StoreRoot) {
    $StoreRoot = (Resolve-Path (Join-Path $here "..\..")).Path
}

$services = Join-Path $StoreRoot "services"
$orchPkg = Join-Path $services "orchestrator"
$cliTs = Join-Path $orchPkg "src\cli.ts"
$cliJs = Join-Path $orchPkg "dist\cli.js"
$envFile = Join-Path $env:USERPROFILE ".daytrade\alpaca.env"

function Test-NodeOk {
    try {
        & $Node -v | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

$useNode = -not $UsePythonFallback -and (Test-Path -LiteralPath $orchPkg) -and (Test-NodeOk)

if ($useNode) {
    $env:DAYTRADE_STORE = $StoreRoot
    Set-Location -LiteralPath $services
    $extra = @("--phase", $Phase, "--proposal-wait-minutes", "$ProposalWaitMinutes", "--env-file", $envFile)
    if ($Submit) { $extra += "--submit" }
    if ($CatchUp) { $extra += "--catch-up" }
    if ($Hour) { $extra += @("--hour", $Hour) }

    if ($Once -or $Hour) {
        if (-not $Hour) { $extra += "--once" }
        Write-Host "Store: $StoreRoot"
        if (Test-Path -LiteralPath $cliJs) {
            Write-Host "Starting: $Node $cliJs $($extra -join ' ')"
            & $Node $cliJs @extra
        } else {
            Write-Host "Starting: npx tsx $cliTs $($extra -join ' ')"
            & npx --yes tsx $cliTs @extra
        }
    } else {
        $extra = @("--loop") + $extra
        Write-Host "Store: $StoreRoot"
        if (Test-Path -LiteralPath $cliJs) {
            Write-Host "Starting: $Node $cliJs $($extra -join ' ')"
            & $Node $cliJs @extra
        } else {
            Write-Host "Starting: npx tsx $cliTs $($extra -join ' ')"
            & npx --yes tsx $cliTs @extra
        }
    }
    exit $LASTEXITCODE
}

# --- Python fallback ---
Write-Host "Node orchestrator unavailable; falling back to hourly_scheduler.py" -ForegroundColor Yellow
$scripts = Join-Path $StoreRoot "scripts"
$scheduler = Join-Path $scripts "hourly_scheduler.py"
if (-not (Test-Path -LiteralPath $scheduler)) {
    Write-Error "hourly_scheduler.py not found at $scheduler. Set -StoreRoot or DAYTRADE_STORE."
}

$pyArgs = @("-3", $scheduler)
$pyCmd = $Python
try {
    & $pyCmd -3 -c "import sys" | Out-Null
} catch {
    $pyCmd = "python"
    $pyArgs = @($scheduler)
}

$extra = @("--phase", $Phase, "--proposal-wait-minutes", "$ProposalWaitMinutes", "--env-file", $envFile)
if ($Submit) { $extra += "--submit" }
if ($CatchUp) { $extra += "--catch-up" }
if ($Once) { $extra += "--once" }
if ($Hour) { $extra += @("--hour", $Hour) }

Set-Location -LiteralPath $scripts
Write-Host "Store: $StoreRoot"
Write-Host "Starting: $pyCmd $($pyArgs + $extra -join ' ')"
& $pyCmd @pyArgs @extra
exit $LASTEXITCODE

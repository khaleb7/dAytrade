# ASCII-only PowerShell (Windows PowerShell 5.1 safe). No em-dashes or smart punctuation.
# One-shot Windows installer for DayTrade Alpaca hourly consensus scheduler.
#
# Example:
#   powershell -ExecutionPolicy Bypass -File .\Install-DayTrade.ps1
#   .\Install-DayTrade.ps1 -StoreRoot "D:\daytrade-store" -StartNow -SkipEnvEdit
[CmdletBinding()]
param(
    [string]$StoreRoot = "",
    [string]$Python = "",
    [switch]$SkipEnvEdit,
    [switch]$SkipTask,
    [switch]$StartNow,
    [switch]$Submit,
    [switch]$DryRun,
    [switch]$VerifyOnly,
    [switch]$ForceReinstallDeps
)

$ErrorActionPreference = "Stop"
$TaskName = "DayTradeHourlyConsensus"
$taskRegistered = $false
$startupFallback = $false

function Write-Step([string]$Msg) { Write-Host ""; Write-Host ("==> " + $Msg) -ForegroundColor Cyan }
function Write-Ok([string]$Msg) { Write-Host ("    OK: " + $Msg) -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host ("    WARN: " + $Msg) -ForegroundColor Yellow }

# --- Resolve store root ---
if (-not $StoreRoot) {
    if ($env:DAYTRADE_STORE -and (Test-Path -LiteralPath $env:DAYTRADE_STORE)) {
        $StoreRoot = $env:DAYTRADE_STORE
    } else {
        # scripts/windows -> store root (two levels up)
        $StoreRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    }
}
$StoreRoot = (Resolve-Path -LiteralPath $StoreRoot).Path
$ScriptsDir = Join-Path $StoreRoot "scripts"
$WinDir = Join-Path $ScriptsDir "windows"
$ReqFile = Join-Path $ScriptsDir "requirements.txt"
$SchedulerPy = Join-Path $ScriptsDir "hourly_scheduler.py"
$ServicesDir = Join-Path $StoreRoot "services"
$OrchPkg = Join-Path $ServicesDir "orchestrator"
$ExampleEnv = Join-Path $WinDir "alpaca.env.example"
$SmokePy = Join-Path $WinDir "smoke_imports.py"

if (-not (Test-Path -LiteralPath $SchedulerPy) -and -not (Test-Path -LiteralPath $OrchPkg)) {
    throw ("Store does not look like DayTrade Project store (missing orchestrator / hourly_scheduler.py): " + $StoreRoot)
}

Write-Step "DayTrade Windows installer"
Write-Host ("    StoreRoot = " + $StoreRoot)

# --- Resolve Python ---
function Find-Python {
    param([string]$Preferred)
    $candidates = @()
    if ($Preferred) { $candidates += $Preferred }
    if ($env:DAYTRADE_PYTHON) { $candidates += $env:DAYTRADE_PYTHON }
    $candidates += @("py", "python", "python3")
    foreach ($c in $candidates) {
        try {
            if ($c -eq "py") {
                $ver = & py -3 -c "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    return @{ Cmd = "py"; Args = @("-3"); Version = ([string]$ver).Trim() }
                }
            } else {
                $ver = & $c -c "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    return @{ Cmd = $c; Args = @(); Version = ([string]$ver).Trim() }
                }
            }
        } catch { }
    }
    return $null
}

$py = Find-Python -Preferred $Python
if (-not $py) {
    throw "Python 3.9+ not found. Install from https://www.python.org/downloads/ (check Add python.exe to PATH), then re-run this installer."
}
$parts = $py.Version.Split(".")
$major = [int]$parts[0]
$minor = [int]$parts[1]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
    throw ("Need Python 3.9+, found " + $py.Version)
}
Write-Ok ("Python " + $py.Version + " via " + $py.Cmd)

function Invoke-Python([string[]]$PyArgs) {
    $all = @()
    if ($py.Args) { $all += $py.Args }
    $all += $PyArgs
    & $py.Cmd @all
    if ($LASTEXITCODE -ne 0) {
        throw ("Python exited " + $LASTEXITCODE + ": " + ($PyArgs -join " "))
    }
}

# --- User config dir (OUTSIDE store) ---
$DayTradeHome = Join-Path $env:USERPROFILE ".daytrade"
$EnvFile = Join-Path $DayTradeHome "alpaca.env"
$LogDir = Join-Path $DayTradeHome "logs"
$LocalConfig = Join-Path $DayTradeHome "config.json"
New-Item -ItemType Directory -Force -Path $DayTradeHome, $LogDir | Out-Null

$envResolved = $EnvFile
$storeResolved = $StoreRoot
if ($envResolved.StartsWith($storeResolved, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw ("Refusing to place alpaca.env inside the Project store. Use " + $DayTradeHome + "\alpaca.env")
}

Write-Step ("User config -> " + $DayTradeHome)
if (-not (Test-Path -LiteralPath $EnvFile)) {
    if (-not (Test-Path -LiteralPath $ExampleEnv)) {
        throw ("Missing example env: " + $ExampleEnv)
    }
    Copy-Item -LiteralPath $ExampleEnv -Destination $EnvFile
    Write-Ok ("Created " + $EnvFile + " from example")
} else {
    Write-Ok ("Existing env file kept: " + $EnvFile)
}

# Persist local install metadata (no secrets)
@{
    store_root = $StoreRoot
    installed_at = (Get-Date).ToString("o")
    task_name = $TaskName
    env_file = $EnvFile
    python = ("{0} {1}" -f $py.Cmd, ($py.Args -join " ")).Trim()
    submit_default = -not [bool]$DryRun
} | ConvertTo-Json | Set-Content -LiteralPath $LocalConfig -Encoding ASCII
Write-Ok ("Wrote " + $LocalConfig)

[Environment]::SetEnvironmentVariable("DAYTRADE_STORE", $StoreRoot, "User")
[Environment]::SetEnvironmentVariable("DAYTRADE_ENV_FILE", $EnvFile, "User")
$env:DAYTRADE_STORE = $StoreRoot
$env:DAYTRADE_ENV_FILE = $EnvFile
Write-Ok "User env DAYTRADE_STORE / DAYTRADE_ENV_FILE set"

if (-not $SkipEnvEdit -and -not $VerifyOnly) {
    $raw = Get-Content -LiteralPath $EnvFile -Raw
    if ($raw -match "YOUR_PAPER_KEY_ID|YOUR_PAPER_SECRET") {
        Write-Warn "alpaca.env still has placeholders - opening in notepad. Save and close when done."
        Start-Process notepad.exe -ArgumentList $EnvFile -Wait
    }
}

# Load env into this process
. (Join-Path $WinDir "Load-AlpacaEnv.ps1") -EnvFile $EnvFile

if ($VerifyOnly) {
    Write-Step "Verify-only mode"
}

# --- pip deps ---
if (-not $VerifyOnly) {
    Write-Step "Installing Python packages (news-bridge worker)"
    $pipArgs = @("-m", "pip", "install", "--user")
    if ($ForceReinstallDeps) { $pipArgs += "--force-reinstall" }
    $pipArgs += @("-r", $ReqFile)
    Invoke-Python $pipArgs
    Invoke-Python @("-m", "pip", "install", "--user", "tzdata")
    Write-Ok "requirements + tzdata installed"
}

# --- Node services (primary orchestrator) ---
$nodeOk = $false
if (-not $VerifyOnly -and (Test-Path -LiteralPath $ServicesDir)) {
    Write-Step "Installing Node control plane (services/)"
    $nodeCmd = $null
    foreach ($c in @($env:DAYTRADE_NODE, "node")) {
        if (-not $c) { continue }
        try {
            $ver = & $c -v 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver) { $nodeCmd = $c; break }
        } catch { }
    }
    if ($nodeCmd) {
        Write-Ok ("Node " + (& $nodeCmd -v) + " via " + $nodeCmd)
        Push-Location $ServicesDir
            # Always include devDependencies (@types/node, typescript, tsx).
            # Windows Agent Store installs sometimes omit them under production-ish npm config.
            & npm install --include=dev --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
            if (-not (Test-Path -LiteralPath (Join-Path $ServicesDir "node_modules\@types\node"))) {
                Write-Warn "@types/node missing after install; installing explicitly"
                & npm install -D "@types/node@22.10.0" --no-audit --no-fund
            }
            & npm run build
            if ($LASTEXITCODE -ne 0) {
                Write-Warn "npm run build failed once; installing typescript/@types/node and retrying"
                & npm install -D "typescript@5.7.2" "@types/node@22.10.0" "tsx@4.19.2" --no-audit --no-fund
                & npm run build
            }
            if ($LASTEXITCODE -ne 0) {
                Write-Warn "npm run build failed; Start-HourlyScheduler will use npx tsx (runtime OK)"
            } else {
                Write-Ok "services built"
            }
            $nodeOk = $true
        } catch {
            Write-Warn ("Node services install issue: " + $_)
            Write-Warn "Scheduler will fall back to Python hourly_scheduler.py"
        } finally {
            Pop-Location
        }
    } else {
        Write-Warn "Node not found on PATH. Install Node 22+ from https://nodejs.org for the TS orchestrator."
        Write-Warn "Python hourly_scheduler.py remains as fallback."
    }
}

# --- Import / timezone smoke (external .py avoids PS parsing of Python syntax) ---
Write-Step "Smoke imports"
Push-Location $ScriptsDir
try {
    if (-not (Test-Path -LiteralPath $SmokePy)) {
        throw ("Missing " + $SmokePy)
    }
    Invoke-Python @($SmokePy)
    Write-Ok "zoneinfo + scheduler OK"
} finally {
    Pop-Location
}

if ($nodeOk) {
    Write-Step "Node orchestrator smoke (next-tick)"
    Push-Location $ServicesDir
    try {
        # Call tsx directly. Do NOT use "npm run ... -- --flag" on Windows PowerShell;
        # npm treats dashed args as config and drops them.
        $cliTs = Join-Path $OrchPkg "src\cli.ts"
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & npx --yes tsx $cliTs --next-tick
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prev
        if ($code -eq 0) { Write-Ok "orchestrator next-tick OK" }
        else { Write-Warn ("orchestrator next-tick failed (exit " + $code + "); tsx still usable at runtime") }
    } catch {
        Write-Warn ("orchestrator smoke: " + $_)
    } finally {
        Pop-Location
    }
}

# --- Alpaca account check (if keys look real) ---
$envText = Get-Content -LiteralPath $EnvFile -Raw
$keysReady = ($envText -notmatch "YOUR_PAPER_KEY_ID|YOUR_PAPER_SECRET") -and $env:APCA_API_KEY_ID -and $env:APCA_API_SECRET_KEY
if ($keysReady) {
    Write-Step "Alpaca paper account check"
    Push-Location $ScriptsDir
    try {
        Invoke-Python @("alpaca_client.py", "account")
        Write-Ok "Alpaca reachable"
    } catch {
        Write-Warn ("Alpaca account check failed: " + $_)
        Write-Warn ("Fix keys in " + $EnvFile + " then re-run with -VerifyOnly")
    } finally {
        Pop-Location
    }
} else {
    Write-Warn ("Paper keys not filled yet - edit " + $EnvFile + " then re-run: .\Install-DayTrade.ps1 -VerifyOnly")
}

if ($VerifyOnly) {
    Write-Host ""
    Write-Host "Verify complete." -ForegroundColor Green
    exit 0
}

# --- Scheduled task (current user; Startup fallback if Access Denied) ---
if (-not $SkipTask) {
    Write-Step ("Register autostart (" + $TaskName + ")")
    $reg = Join-Path $WinDir "Register-DayTradeHourly.ps1"
    try {
        $regArgs = @{
            Mode = "Loop"
            StoreRoot = $StoreRoot
            TaskName = $TaskName
        }
        if ($DryRun -and -not $Submit) { $regArgs["DryRun"] = $true }
        elseif ($Submit) { $regArgs["Submit"] = $true }
        & $reg @regArgs
        # Detect whether task exists now
        $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($existing) {
            $taskRegistered = $true
            Write-Ok ("Registered logon task '" + $TaskName + "' for current user")
        } else {
            $startupFallback = $true
            Write-Ok "Using Startup-folder shortcut (Task Scheduler unavailable or denied)"
        }
    } catch {
        Write-Warn ("Autostart registration issue: " + $_)
        Write-Warn "You can still run .\Start-HourlyScheduler.ps1 -CatchUp in the foreground"
    }

    if ($StartNow -and $taskRegistered) {
        Write-Step "Starting task now"
        try {
            Start-ScheduledTask -TaskName $TaskName
            Start-Sleep -Seconds 2
            $info = Get-ScheduledTaskInfo -TaskName $TaskName
            Write-Ok ("LastTaskResult=" + $info.LastTaskResult + " LastRunTime=" + $info.LastRunTime)
        } catch {
            Write-Warn ("Could not start task: " + $_)
            Write-Host "    Start foreground instead: .\Start-HourlyScheduler.ps1 -CatchUp"
        }
    } elseif ($StartNow -and -not $taskRegistered) {
        Write-Step "Starting scheduler in a new window (Startup fallback / no task)"
        $starter = Join-Path $WinDir "Start-HourlyScheduler.ps1"
        Start-Process powershell.exe -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", $starter,
            "-StoreRoot", $StoreRoot,
            "-CatchUp"
        )
        Write-Ok "Launched Start-HourlyScheduler.ps1"
    } else {
        if ($taskRegistered) {
            Write-Host ("    Start when ready: Start-ScheduledTask -TaskName '" + $TaskName + "'")
        }
        Write-Host "    Or foreground:   .\Start-HourlyScheduler.ps1 -CatchUp"
    }
} else {
    Write-Warn "Skipped task registration (-SkipTask)"
}

# --- Shortcut ---
Write-Step "Desktop shortcut (optional)"
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnkPath = Join-Path $desktop "DayTrade Hourly Scheduler.lnk"
    $starter = Join-Path $WinDir "Start-HourlyScheduler.ps1"
    $w = New-Object -ComObject WScript.Shell
    $sc = $w.CreateShortcut($lnkPath)
    $sc.TargetPath = "powershell.exe"
    $sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$starter`" -StoreRoot `"$StoreRoot`" -CatchUp"
    $sc.WorkingDirectory = $ScriptsDir
    $sc.Description = "DayTrade Alpaca hourly consensus (foreground)"
    $sc.Save()
    Write-Ok ("Shortcut: " + $lnkPath)
} catch {
    Write-Warn ("Could not create desktop shortcut: " + $_)
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Install complete" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host (" Store:   " + $StoreRoot)
Write-Host (" Env:     " + $EnvFile + "   (secrets stay outside store)")
Write-Host (" Logs:    " + $LogDir)
Write-Host (" Config:  " + $LocalConfig)
Write-Host (" Task:    " + $TaskName + " (current-user logon task, or Startup shortcut fallback)")
Write-Host (" Status:  " + $StoreRoot + "\state\scheduler\status.json")
Write-Host ""
Write-Host " Next:"
Write-Host "  1) Confirm keys in alpaca.env"
if ($taskRegistered) {
    Write-Host ("  2) Start-ScheduledTask -TaskName " + $TaskName)
} else {
    Write-Host "  2) .\Start-HourlyScheduler.ps1 -CatchUp   (or log off/on if Startup shortcut was installed)"
}
Write-Host "  3) Paper submit is ON by default. Pass -DryRun on Start/Install to opt out."
Write-Host (" Docs: " + $StoreRoot + "\docs\windows-scheduler.md")
Write-Host (" Control plane: " + $StoreRoot + "\docs\control-plane.md")
$envCheck = Get-Content -LiteralPath $EnvFile -Raw -ErrorAction SilentlyContinue
if ($envCheck -match "YOUR_CURSOR_API_KEY|YOUR_PAPER_KEY") {
    Write-Host " Reminder: fill APCA_* and CURSOR_API_KEY in alpaca.env (fixtures used if CURSOR_API_KEY unset)."
}

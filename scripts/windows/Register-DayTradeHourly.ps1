# ASCII-only. Register DayTrade hourly scheduler for the CURRENT Windows user
# without requiring Administrator. Falls back to Startup-folder shortcut on denial.
param(
    [string]$StoreRoot = $(if ($env:DAYTRADE_STORE) { $env:DAYTRADE_STORE } else { (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }),
    [ValidateSet("Loop", "PerHour")]
    [string]$Mode = "Loop",
    [string]$TaskName = "DayTradeHourlyConsensus",
    [switch]$Submit,
    [switch]$DryRun,
    [switch]$Unregister,
    [switch]$StartupFallback
)

$ErrorActionPreference = "Stop"
$StoreRoot = (Resolve-Path -LiteralPath $StoreRoot).Path
$scriptsWin = Join-Path $StoreRoot "scripts\windows"
$starter = Join-Path $scriptsWin "Start-HourlyScheduler.ps1"
$scriptsDir = Join-Path $StoreRoot "scripts"

if (-not (Test-Path -LiteralPath $starter)) {
    throw ("Missing " + $starter)
}

function Get-StarterArgs([string[]]$Extra) {
    $list = @("-StoreRoot", ("`"{0}`"" -f $StoreRoot))
    $list += $Extra
    # Paper submit is default; only pass -DryRun when opting out. -Submit kept for compatibility.
    if ($DryRun -and -not $Submit) { $list += "-DryRun" }
    elseif ($Submit) { $list += "-Submit" }
    return $list
}

function New-DayTradeAction([string[]]$ArgumentList) {
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$starter`" " + ($ArgumentList -join " ")
    return New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $scriptsDir
}

function Get-CurrentUserPrincipal {
    # Interactive current user, Limited = no admin elevation required to register
    $uid = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    return New-ScheduledTaskPrincipal -UserId $uid -LogonType Interactive -RunLevel Limited
}

function Install-StartupShortcut {
    param([string[]]$ExtraArgs, [string]$LinkName = "DayTradeHourlyConsensus.lnk")
    $startup = [Environment]::GetFolderPath("Startup")
    if (-not $startup) { throw "Could not resolve Startup folder" }
    $lnkPath = Join-Path $startup $LinkName
    $argList = Get-StarterArgs $ExtraArgs
    $w = New-Object -ComObject WScript.Shell
    $sc = $w.CreateShortcut($lnkPath)
    $sc.TargetPath = "powershell.exe"
    $sc.Arguments = "-NoProfile -WindowStyle Minimized -ExecutionPolicy Bypass -File `"$starter`" " + ($argList -join " ")
    $sc.WorkingDirectory = $scriptsDir
    $sc.Description = "DayTrade hourly consensus (Startup fallback)"
    $sc.Save()
    Write-Host ("Startup shortcut installed (no admin needed): " + $lnkPath)
    Write-Host "It will start at the next Windows logon. To start now:"
    Write-Host ("  powershell -ExecutionPolicy Bypass -File `"$starter`" -StoreRoot `"$StoreRoot`" -CatchUp")
    return $lnkPath
}

function Remove-StartupShortcut([string]$LinkName = "DayTradeHourlyConsensus.lnk") {
    $startup = [Environment]::GetFolderPath("Startup")
    if (-not $startup) { return }
    $lnkPath = Join-Path $startup $LinkName
    if (Test-Path -LiteralPath $lnkPath) {
        Remove-Item -LiteralPath $lnkPath -Force
        Write-Host ("Removed Startup shortcut " + $lnkPath)
    }
}

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    10..15 | ForEach-Object {
        Unregister-ScheduledTask -TaskName ($TaskName + "-" + $_) -Confirm:$false -ErrorAction SilentlyContinue
    }
    Remove-StartupShortcut
    Write-Host ("Unregistered " + $TaskName + "* and Startup fallback")
    exit 0
}

$principal = Get-CurrentUserPrincipal

if ($Mode -eq "Loop") {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $extra = @("-CatchUp")
    $action = New-DayTradeAction (Get-StarterArgs $extra)
    # Scope AtLogOn to this user (avoids admin requirement for "any user" logon tasks)
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)

    try {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Description "DayTrade Alpaca paper hourly consensus loop (10-15 ET)" `
            -Force | Out-Null
        Write-Host ("Registered logon task '" + $TaskName + "' for user " + $env:USERNAME + " (no admin).")
        Write-Host ("Start now: Start-ScheduledTask -TaskName '" + $TaskName + "'")
    } catch {
        Write-Host ("Task Scheduler register failed: " + $_.Exception.Message) -ForegroundColor Yellow
        Write-Host "Falling back to per-user Startup folder shortcut..." -ForegroundColor Yellow
        Install-StartupShortcut -ExtraArgs @("-CatchUp") | Out-Null
        if (-not $StartupFallback) {
            # still success path for installer
        }
    }
} else {
    $anyOk = $false
    foreach ($h in 10..15) {
        $name = $TaskName + "-" + $h
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
        $extra = @("-Once", "-Phase", "prep-then-settle")
        $action = New-DayTradeAction (Get-StarterArgs $extra)
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At ("{0}:00" -f $h)
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable
        try {
            Register-ScheduledTask `
                -TaskName $name `
                -Action $action `
                -Trigger $trigger `
                -Settings $settings `
                -Principal $principal `
                -Description ("DayTrade hour " + $h + " tick") `
                -Force | Out-Null
            Write-Host ("Registered " + $name + " at " + $h + ":00 local time")
            $anyOk = $true
        } catch {
            Write-Host ("Failed " + $name + ": " + $_.Exception.Message) -ForegroundColor Yellow
        }
    }
    if (-not $anyOk) {
        Write-Host "PerHour tasks failed; installing Startup-folder loop instead." -ForegroundColor Yellow
        Install-StartupShortcut -ExtraArgs @("-CatchUp") | Out-Null
    } else {
        Write-Host "Note: PerHour uses machine local clock. Prefer -Mode Loop if PC is not on Eastern time."
    }
}

Write-Host "Done. Ensure %USERPROFILE%\.daytrade\alpaca.env exists with paper keys."
exit 0

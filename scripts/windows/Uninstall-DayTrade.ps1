<#
.SYNOPSIS
  Uninstall DayTrade Windows scheduler (tasks + optional local config).
  Does NOT delete the Project store or alpaca.env unless -RemoveEnv is set.
#>
[CmdletBinding()]
param(
    [string]$StoreRoot = $(if ($env:DAYTRADE_STORE) { $env:DAYTRADE_STORE } else { (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }),
    [string]$TaskName = "DayTradeHourlyConsensus",
    [switch]$RemoveEnv,
    [switch]$RemoveUserEnvVars
)

$ErrorActionPreference = "Stop"
$reg = Join-Path $PSScriptRoot "Register-DayTradeHourly.ps1"
& $reg -Unregister -TaskName $TaskName -StoreRoot $StoreRoot

$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "DayTrade Hourly Scheduler.lnk"
if (Test-Path -LiteralPath $lnk) {
    Remove-Item -LiteralPath $lnk -Force
    Write-Host "Removed shortcut $lnk"
}

if ($RemoveUserEnvVars) {
    [Environment]::SetEnvironmentVariable("DAYTRADE_STORE", $null, "User")
    [Environment]::SetEnvironmentVariable("DAYTRADE_ENV_FILE", $null, "User")
    Write-Host "Cleared user DAYTRADE_STORE / DAYTRADE_ENV_FILE"
}

$homeDir = Join-Path $env:USERPROFILE ".daytrade"
if ($RemoveEnv) {
    $envFile = Join-Path $homeDir "alpaca.env"
    if (Test-Path -LiteralPath $envFile) {
        Remove-Item -LiteralPath $envFile -Force
        Write-Host "Removed $envFile"
    }
}

$config = Join-Path $homeDir "config.json"
if (Test-Path -LiteralPath $config) {
    Remove-Item -LiteralPath $config -Force
    Write-Host "Removed $config"
}

Write-Host "Uninstall done. Store left intact at $StoreRoot"

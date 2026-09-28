# Load Alpaca env from a file OUTSIDE the Project store into this process.
# Default: $env:USERPROFILE\.daytrade\alpaca.env
param(
    [string]$EnvFile = $(if ($env:DAYTRADE_ENV_FILE) { $env:DAYTRADE_ENV_FILE } else { Join-Path $env:USERPROFILE ".daytrade\alpaca.env" })
)

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Error "Env file not found: $EnvFile`nCopy scripts\windows\alpaca.env.example -> $EnvFile and fill paper keys."
    exit 1
}

Get-Content -LiteralPath $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $i = $line.IndexOf("=")
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim().Trim("'").Trim('"')
    if ($k -match '^(APCA_|DAYTRADE_|CURSOR_)') {
        Set-Item -Path "Env:$k" -Value $v
    }
}

Write-Host "Loaded env from $EnvFile"

@echo off
REM DayTrade Windows installer launcher (double-click friendly)
REM ASCII-only. Uses Windows PowerShell 5.1 or pwsh 7+.
setlocal
cd /d "%~dp0"

echo DayTrade - Windows installer
echo Store will be detected from this folder's parent chain.
echo.

where pwsh >nul 2>&1
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-DayTrade.ps1" %*
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-DayTrade.ps1" %*
)

set EXITCODE=%ERRORLEVEL%
echo.
if not %EXITCODE%==0 (
  echo Installer exited with code %EXITCODE%.
)
pause
exit /b %EXITCODE%
endlocal

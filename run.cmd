@echo off
setlocal

set "REPO_ROOT=%~dp0"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

"%POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%run.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo OKai launcher failed with exit code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%

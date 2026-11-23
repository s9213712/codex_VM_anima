@echo off
cd /d "%~dp0"
where gh >nul 2>nul
if errorlevel 1 (
 echo Install GitHub CLI from https://cli.github.com/ then reopen this launcher.
 pause
 exit /b 2
)
gh auth status --hostname github.com >nul 2>nul
if errorlevel 1 gh auth login --hostname github.com --git-protocol https --web --scopes repo
if errorlevel 1 (
 echo GitHub login failed. Nothing was submitted.
 pause
 exit /b 2
)
where py >nul 2>nul
if not errorlevel 1 (
 py -3 dashboard.py
) else (
 python dashboard.py
)
pause

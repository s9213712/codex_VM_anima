@echo off
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
 echo Install Git for Windows: https://git-scm.com/download/win
 pause
 exit /b 2
)
node scripts\git-update.cjs
pause

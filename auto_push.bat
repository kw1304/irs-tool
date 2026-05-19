@echo off
cd /d "%~dp0"

echo [auto_push] Starting in: %CD%
git --version
echo [auto_push] Checking every 5 seconds.
echo.

:loop
echo [auto_push] --- Checking ---
echo [auto_push] git status:
git status --porcelain
echo [auto_push] (end of status)

git status --porcelain | findstr /r "." >nul 2>&1
if not errorlevel 1 (
    echo [auto_push] Changes detected. Pushing...
    git add .
    git commit -m "auto update"
    git push
    echo [auto_push] Push done.
) else (
    echo [auto_push] No changes.
)

echo [auto_push] Waiting 5 seconds...
echo.
timeout /t 5 /nobreak >nul
goto :loop

@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo [auto_push] Starting in: %CD%
echo [auto_push] Checking every 5 seconds.
echo.

:loop
echo [auto_push] Checking git status...

set CHANGED=0
for /f "usebackq tokens=*" %%i in (`git status --porcelain`) do (
    set CHANGED=1
)

echo [auto_push] CHANGED=!CHANGED!

if "!CHANGED!"=="1" (
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

@echo off
cd /d "%~dp0"

echo [auto_push] Started. Checking every 5 seconds.
echo [auto_push] Close this window to stop.
echo.

:loop
git status --porcelain > .tmp_status 2>&1
for %%A in (.tmp_status) do if %%~zA gtr 0 goto :push
del .tmp_status
timeout /t 5 /nobreak >nul
goto :loop

:push
del .tmp_status
git add .
git commit -m "auto update"
git push
echo [auto_push] Pushed.
echo.
timeout /t 5 /nobreak >nul
goto :loop

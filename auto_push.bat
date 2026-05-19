@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [auto_push] 시작 - 5초마다 변경사항 체크
echo [auto_push] 종료하려면 이 창을 닫으세요.
echo.

:loop
for /f "tokens=*" %%i in ('git status --porcelain') do (
    goto :has_changes
)
goto :no_changes

:has_changes
for /f "tokens=1-2 delims=T" %%a in ("%date%T%time%") do (
    set DATESTAMP=%%a
    set TIMESTAMP=%%b
)
set TIMESTAMP=%TIMESTAMP:~0,8%
set DATETIME=%DATESTAMP% %TIMESTAMP%

git add .
git commit -m "자동 업데이트 %DATETIME%"
git push
echo [auto_push] 푸시 완료: %DATETIME%
echo.

:no_changes
timeout /t 5 /nobreak >nul
goto :loop

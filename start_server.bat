@echo off
cd /d C:\Users\kw130\irs-tool

REM 이미 5000 포트가 사용 중인지 확인
netstat -ano | findstr ":5000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    start "" http://localhost:5000
    exit /b 0
)

REM Flask 서버 백그라운드 실행
start "" /B python server.py

REM 서버 기동 대기 (최대 10초)
set /a tries=0
:wait_loop
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":5000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto server_ready
set /a tries+=1
if %tries% lss 10 goto wait_loop

:server_ready
start "" http://localhost:5000

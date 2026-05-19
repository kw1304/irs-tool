' IRS 평가툴 서버 시작 (터미널 창 없이 백그라운드 실행)
Set WshShell = CreateObject("WScript.Shell")

' 0 = 창 완전히 숨김, False = 비동기 실행
WshShell.Run "cmd /c C:\Users\kw130\irs-tool\start_server.bat", 0, False

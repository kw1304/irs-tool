Dim WshShell
Dim scriptDir
Dim batPath

Set WshShell = CreateObject("WScript.Shell")

' Get the directory where this vbs file is located
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
batPath = scriptDir & "auto_push.bat"

' Run bat file hidden (0 = no window, False = don't wait)
WshShell.Run "cmd /c """ & batPath & """", 0, False

Set WshShell = Nothing

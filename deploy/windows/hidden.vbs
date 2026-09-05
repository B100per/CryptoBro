' Run a .cmd with no console window. Task Scheduler cannot hide a console
' program by itself, and a black window popping up at every logon is not a
' service. Usage: wscript hidden.vbs "C:\path\to\script.cmd"
Set sh = CreateObject("WScript.Shell")
sh.Run "cmd.exe /c """ & WScript.Arguments(0) & """", 0, False

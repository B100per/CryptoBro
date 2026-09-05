' Run a .cmd with no console window. Task Scheduler cannot hide a console
' program by itself, and a black window popping up at every logon is not a
' service. Usage: wscript hidden.vbs "C:\path\to\script.cmd"
'
' Waits for the script and exits with its code, so the task shows Running
' while the program lives and Task Scheduler's restart-on-failure applies.
' (Detached, the task "finished" the moment it started and a crashed
' collector would have stayed dead.)
Set sh = CreateObject("WScript.Shell")
WScript.Quit sh.Run("cmd.exe /c """ & WScript.Arguments(0) & """", 0, True)

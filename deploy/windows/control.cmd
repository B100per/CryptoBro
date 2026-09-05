@echo off
rem The control panel and both paper books, on http://127.0.0.1:8787.
rem control.py reads CONTROL_TOKEN from the environment only, never from .env,
rem so it is lifted out of .env here. Nothing else in .env is exported.
cd /d "%~dp0..\.."
for /f "tokens=1,* delims==" %%a in ('findstr /b /c:"CONTROL_TOKEN=" .env') do set "CONTROL_TOKEN=%%b"
py -3 -u control.py >> logs\control.log 2>&1

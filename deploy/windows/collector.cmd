@echo off
rem The collector, forever. Task Scheduler restarts it if it dies (see install.ps1).
cd /d "%~dp0..\.."
py -3 -u collector.py >> logs\collector.log 2>&1

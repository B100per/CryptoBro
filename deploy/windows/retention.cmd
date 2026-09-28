@echo off
rem Daily 04:30: roll 5-minute bars older than a year up to hourly, then VACUUM.
rem The window lives in retention.py; do not pass --days here, or the two drift.
cd /d "%~dp0..\.."
py -3 -u retention.py >> logs\retention.log 2>&1

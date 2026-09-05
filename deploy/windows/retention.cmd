@echo off
rem Daily 04:30: roll 5-minute bars older than 45 days up to hourly, then VACUUM.
cd /d "%~dp0..\.."
py -3 -u retention.py --days 45 >> logs\retention.log 2>&1

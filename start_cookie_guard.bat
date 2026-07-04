@echo off
cd /d "%~dp0"
echo Starting Cookie Guard... (close this window or press Ctrl+C to stop)
python cookie_guard.py --browser brave
pause

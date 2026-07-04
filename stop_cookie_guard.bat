@echo off
echo Stopping Cookie Guard (background)...
taskkill /f /im pythonw.exe >nul 2>&1
echo Done. (Note: this stops all hidden Python background programs.)
pause

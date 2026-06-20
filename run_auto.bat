@echo off
REM Auto-collect eBay every 4 hours. Close this window to stop.
REM To change interval, edit the number below (seconds): 7200=2h  14400=4h  21600=6h
cd /d C:\psa-tool
echo Auto-collecting every 4 hours. Close this window to stop.
.venv\Scripts\python.exe run_loop.py 14400
pause

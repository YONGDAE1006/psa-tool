@echo off
REM 1시간마다 자동으로 eBay 수집 (이 창을 닫으면 중지)
cd /d C:\psa-tool
echo Auto-collecting every 1 hour. Close this window to stop.
.venv\Scripts\python.exe run_loop.py 3600
pause

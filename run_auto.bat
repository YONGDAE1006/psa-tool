@echo off
REM 4시간마다 자동으로 eBay 수집 (이 창을 닫으면 중지)
REM 주기 변경: 아래 14400(초)을 바꾸세요. 7200=2시간, 14400=4시간, 21600=6시간
cd /d C:\psa-tool
echo Auto-collecting every 4 hours. Close this window to stop.
.venv\Scripts\python.exe run_loop.py 14400
pause

@echo off
REM 올인원: 자동수집 + 텔레그램 명령(/status /top /run) + 생존신호 + 에러알림
REM 이 창을 닫으면 중지됩니다. (텔레그램 설정 필요)
cd /d C:\psa-tool
.venv\Scripts\python.exe agent.py
pause

@echo off
REM 대시보드 실행 (브라우저에서 http://localhost:8501)
cd /d C:\psa-tool
.venv\Scripts\python.exe -m streamlit run dashboard.py
pause

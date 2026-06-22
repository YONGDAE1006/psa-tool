@echo off
REM 대시보드 실행 (브라우저에서 http://localhost:8501)
cd /d C:\psa-tool
echo [PSA] 기존 8501 대시보드 정리 중...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
echo [PSA] 대시보드 시작... 브라우저에서 http://localhost:8501 접속하세요.
.venv\Scripts\python.exe -m streamlit run dashboard.py --server.port 8501
pause

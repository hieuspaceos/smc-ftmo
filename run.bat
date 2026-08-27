@echo off
echo Clearing cache...
rd /s /q src\__pycache__ 2>nul
rd /s /q __pycache__ 2>nul

echo Setting PYTHONPATH=src...
set PYTHONPATH=src

echo Starting SMC FTMO App...
streamlit run app.py --server.port=8501

echo.
echo App should be running at http://localhost:8501
echo Press Ctrl+C in this window to stop.
pause

@echo off
chcp 65001 >nul
title GLM Bourse - Stock Analyzer
cd /d "%~dp0"

echo ============================================
echo   GLM Bourse - 4-Agent Stock Scoring System
echo   http://127.0.0.1:5001
echo ============================================
echo.

rem ---- check python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ first.
    pause
    exit /b 1
)

rem ---- first run: install dependencies ----
python -c "import flask, pandas, requests" >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing dependencies, please wait...
    pip install -r requirements.txt
    echo.
)

rem ---- open browser after server starts ----
start "" /min cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5001"

echo [INFO] Server starting... browser will open automatically.
echo [INFO] To stop the app, close this window or press Ctrl+C.
echo.
python app.py

echo.
echo [INFO] Server stopped.
pause

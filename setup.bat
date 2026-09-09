@echo off
chcp 65001 >nul
title GLM Bourse - First Time Setup
cd /d "%~dp0"

echo ============================================
echo   GLM Bourse - نصب برنامه (فقط بار اول)
echo ============================================
echo.

rem ---- check python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [خطا] پایتون نصب نیست!
    echo.
    echo ۱. برو به:  https://www.python.org/downloads/
    echo ۲. آخرین نسخه Python 3 را دانلود و نصب کن
    echo ۳. موقع نصب حتماً تیک "Add Python to PATH" را بزن
    echo ۴. بعد از نصب، این فایل را دوباره اجرا کن
    echo.
    pause
    start https://www.python.org/downloads/
    exit /b 1
)

echo [۱/۲] پایتون پیدا شد:
python --version
echo.
echo [۲/۲] نصب کتابخانه‌های مورد نیاز...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [خطا] نصب کتابخانه‌ها ناموفق بود. اتصال اینترنت را چک کن و دوباره اجرا کن.
    pause
    exit /b 1
)
echo.
echo ============================================
echo   نصب کامل شد!
echo   حالا روی فایل start.bat دابل‌کلیک کن
echo ============================================
echo.
pause

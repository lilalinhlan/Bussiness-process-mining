@echo off
rem ============================================================
rem  Process Dashboard - khoi dong nhanh (double-click file nay)
rem  Mo trinh duyet tai http://127.0.0.1:5000
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay "python" trong PATH.
    echo Hay cai Python 3.11 hoac chay: py -3.11 app.py
    pause
    exit /b 1
)

echo Dang kiem tra thu vien...
python -c "import flask, pandas, networkx" 2>nul
if errorlevel 1 (
    echo Thieu thu vien, dang cai dat...
    python -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo   Process Dashboard: http://127.0.0.1:5000
echo   De tat: dong cua so nay hoac nhan Ctrl+C
echo ============================================================
echo.

python app.py
pause

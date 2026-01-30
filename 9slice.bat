@echo off
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo Failed to launch. Make sure Python and Pillow are installed:
    echo   pip install Pillow
    pause
)

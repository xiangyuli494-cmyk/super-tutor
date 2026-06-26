@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

set CONFIG_DIR=%USERPROFILE%\.super-tutor
set CONFIG_FILE=%CONFIG_DIR%\settings.json

if exist "%CONFIG_FILE%" goto :launch

echo.
echo ========================================================
echo   Super Tutor - First Run Setup
echo ========================================================
echo.
echo   Configure your LLM API.
echo   Press Enter to accept default values in [brackets].
echo.

set API_KEY=
set /p API_KEY="  API Key: "
if "!API_KEY!"=="" (
    echo   API Key is required!
    pause
    exit /b 1
)

set API_BASE=https://api.deepseek.com
set MODEL=deepseek-chat

set INPUT=
set /p INPUT="  API Base URL [%API_BASE%]: "
if not "!INPUT!"=="" set API_BASE=!INPUT!

set INPUT=
set /p INPUT="  Model [%MODEL%]: "
if not "!INPUT!"=="" set MODEL=!INPUT!

if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"

echo {"api_key": "!API_KEY!","api_base_url": "!API_BASE!","model": "!MODEL!"} > "!CONFIG_FILE!"

echo.
echo   Config saved.
echo.

:launch
echo Starting Super Tutor...
echo Open http://localhost:8501 in your browser.
echo Press Ctrl+C to stop.
echo.

cd /d "%~dp0"
streamlit run app.py
pause

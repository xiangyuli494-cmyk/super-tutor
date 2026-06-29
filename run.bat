@echo off
REM ===========================================================================
REM Super Tutor — Windows 一键启动脚本
REM
REM 【功能说明】
REM 1. 首次运行：交互式配置 API Key / Base URL / Model → 写入
REM    %USERPROFILE%\.super-tutor\settings.json
REM 2. 后续运行：跳过配置，直接启动 Streamlit 前端（app.py）
REM
REM 【耦合关系】
REM - 启动 app.py（Streamlit 单页应用）
REM - 配置写入 config.py 读取的 settings.json
REM - 端口：Streamlit 默认 8501
REM ===========================================================================
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

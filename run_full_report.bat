@echo off
title Portfolio Analysis - Full Report
cd /d "%~dp0"

REM Public-API runs can exceed the 900s default deadline (network-heavy
REM stages + provider fallbacks). Keep the report complete instead of PARTIAL.
REM External values win: set these before launching if a longer run is needed.
if not defined RUN_DEADLINE_SECONDS set RUN_DEADLINE_SECONDS=1800
if not defined RUN_WATCHDOG_SECONDS set RUN_WATCHDOG_SECONDS=2100

echo Running full portfolio analysis...
py -3.12 portfolio_ai_assistant.py --config portfolio_config.json --investment-engine --generate-full-report

if errorlevel 1 (
    echo.
    echo [ERROR] Portfolio analysis failed. Check the messages above.
    pause
    exit /b 1
)

echo.
echo Report generation finished. See Python output above for the actual saved paths.
pause

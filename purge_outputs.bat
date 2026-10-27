@echo off
REM ============================================================
REM Portfolio AI Assistant - FULL OUTPUT PURGE
REM ============================================================
REM IRREVERSIBLE: Deletes ALL files under reports\ and logs\
REM Requires explicit confirmation by typing exactly: PURGE
REM
REM This is a SEPARATE operation from cleanup.bat (which does
REM retention-based cleanup by default).
REM ============================================================

setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ==========================================
echo Portfolio AI Assistant - FULL OUTPUT PURGE
echo ==========================================
echo.
echo WARNING: This will DELETE ALL FILES AND FOLDERS under:
echo   reports\
echo   logs\
echo.
echo Protected (NOT deleted):
echo   - Source code (*.py)
echo   - portfolio_config.json
echo   - agent_data\
echo   - data\
echo   - docs\
echo.

if "%~1"=="--confirm" (
    set "CONFIRM=%~2"
) else (
    set "CONFIRM="
    set /p "CONFIRM=Type exactly PURGE to confirm: "
)

if /I not "%CONFIRM%"=="PURGE" (
    echo.
    echo Aborted - confirmation did not match 'PURGE'.
    goto end
)

echo.
echo Purging...
py -3.12 -m scripts.purge_outputs --confirm PURGE

:end
endlocal
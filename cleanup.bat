@echo off
REM ============================================================
REM Portfolio AI Assistant - Retention-based Cleanup
REM ============================================================
REM Default: DRY-RUN only (lists what would be removed)
REM --apply : Apply retention policy (keeps recent/active/protected)
REM --dry-run : Explicit dry-run (same as default)
REM
REM Never touched: source code, portfolio_config.json, agent_data\,
REM data\, docs\
REM
REM For FULL IRREVERSIBLE purge of ALL reports/logs, use:
REM   purge_outputs.bat
REM ============================================================

setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "MODE=dry"
if /I "%~1"=="--apply" set "MODE=apply"
if /I "%~1"=="--dry-run" set "MODE=dry"

echo ==========================================
echo Portfolio AI Assistant - Retention Cleanup
echo ==========================================
echo.

if "%MODE%"=="apply" (
    echo Applying retention policy...
    py -3.12 -m scripts.cleanup_outputs --apply
) else (
    echo Dry-run mode (no changes will be made)...
    echo Use --apply to execute the retention policy.
    echo.
    py -3.12 -m scripts.cleanup_outputs --dry-run
)

echo.
echo ==========================================
echo Note: for FULL IRREVERSIBLE purge of ALL outputs,
echo run: purge_outputs.bat
echo ==========================================

endlocal
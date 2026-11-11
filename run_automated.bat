@echo off
cd /d "%~dp0"

REM Task Scheduler variant: no pause, and Python owns logs\latest_run.log.
REM Usage: run_automated.bat [auto|public|locals]  (default: auto)
REM   auto   = full chain, locals first (LM Studio -> Pi -> public APIs)
REM   public = public APIs only (locals never touched)
REM   locals = local endpoints only + deterministic fallback
REM Models are stage-routed; every stage currently uses nvidia-nemotron-3.5-bolt-e4b
REM (benchmarked ~45-50 tok/s with full format compliance on this machine).
REM Change the model ids in portfolio_config.json + custom_rules.json to reroute.
set MODE=%1
if "%MODE%"=="" set MODE=auto

REM Same budget as run_full_report.bat: network-heavy stages can exceed 900s.
REM External values win (scheduled tasks may set their own).
if not defined RUN_DEADLINE_SECONDS set RUN_DEADLINE_SECONDS=1800
if not defined RUN_WATCHDOG_SECONDS set RUN_WATCHDOG_SECONDS=2100

REM Both branches in one run: live (read-only recommendations) + demo (orders).
REM Demo orders are deduped by the order ledger: one per symbol and side per
REM New York trading day, no matter how many times the task fires.
py -3.12 portfolio_ai_assistant.py --config portfolio_config.json --investment-engine --generate-full-report --execution-mode %MODE% --branches both --day-trader --day-trader-plan --day-trader-allow-orders
exit /b %ERRORLEVEL%

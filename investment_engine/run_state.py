"""Process-wide run state shared across engine modules.

These containers are mutated during a run and read by reporting/attribution
code. Keeping them in a neutral module avoids importing ``main`` just to reach
a mutable list.
"""

from __future__ import annotations

from datetime import datetime

from investment_engine import liveness as _lv

FALLBACK_EVENTS: list[str] = []
STAGE_ATTRIBUTION: dict[str, dict] = {}


def build_run_budget(start_time, report_dt, duration_s, budget_s) -> dict:
    """Assemble the run-budget manifest block.

    ``started_at`` is the wall-clock start of the run, not the moment the
    report is finalized (the old duplicate dict used report_dt).
    """
    started_at = ""
    try:
        if start_time is not None:
            started_at = datetime.fromtimestamp(
                float(start_time), tz=report_dt.tzinfo).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        started_at = ""
    try:
        duration = float(duration_s or 0.0)
        budget = float(budget_s or 900.0)
    except (TypeError, ValueError):
        duration, budget = 0.0, 900.0
    return {
        "started_at": started_at,
        "budget_s": budget,
        "duration_s": duration,
        "exceeded": bool(duration > budget),
    }

def _run_deadline_exceeded() -> bool:
    """Compatibility wrapper - now uses monotonic budget."""
    return _lv.RUN_BUDGET.exceeded()

def _reset_run_budget() -> None:
    """Initialize the run budget from env (monotonic)."""
    _lv.RUN_BUDGET.start(_lv.resolve_run_deadline_seconds())

run_deadline_exceeded = _run_deadline_exceeded
reset_run_budget = _reset_run_budget


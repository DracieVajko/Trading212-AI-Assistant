"""Trade-planning pack (entry, exit, time machine, budget, risk, ticket).

Read-only with respect to brokers: produces tickets only. No orders are sent.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DayTraderConfig
from .plan_filter import evaluate_plan
from .runner import ToolResult, run_tool
from .state import ensure_state_root, read_json, write_json

VENDOR_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "day_trader_skill"


def _vendor(rel: str) -> Path:
    return VENDOR_ROOT / rel


def _tool_ok(res: ToolResult) -> bool:
    return res.payload is not None


def run_planning(
    config: DayTraderConfig,
    runner=run_tool,
    state_root: str | Path = "data/day_trader",
    vendor_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run the planning pack for the first triggered setup. Never raises."""
    state_root = ensure_state_root(state_root)
    trader_dir = state_root / "trader"
    vr = Path(vendor_root) if vendor_root is not None else VENDOR_ROOT
    errors: list[dict[str, Any]] = []

    watchlist = read_json(trader_dir / "watchlist.json", {}) or {}
    hits = [h for h in (watchlist.get("hits") or []) if isinstance(h, dict) and h.get("symbol")]
    symbols = [str(h["symbol"]).upper() for h in hits[: config.watchlist_limit]]

    plan_symbol: str | None = None
    plan_status = "NO_TRIGGER"
    _filter = None
    tickets: dict[str, Any] = {}

    for sym in symbols:
        # entry check (writes trader/entry.json)
        res = runner(
            _vendor_rel(vr, "trader-entry/entry.py"),
            ["check", sym, "--setup", "orb", "--write"],
            60,
            True,
            state_root,
            None,
        )
        entry = res.payload if _tool_ok(res) and isinstance(res.payload, dict) else read_json(trader_dir / "entry.json", {})
        if not isinstance(entry, dict):
            entry = {}
        status = str(entry.get("status", "")).lower()
        if status != "triggered":
            continue

        plan_symbol = sym
        # exit plan (writes trader/plan.json)
        res = runner(
            _vendor_rel(vr, "trader-exit/exit.py"),
            ["plan", "--from", "trader/entry.json", "--stop", "or-mid", "--target", "1R", "--write"],
            30,
            True,
            state_root,
            None,
        )
        if not _tool_ok(res):
            errors.append({"stage": "exit", "symbol": sym, "error": (res.stderr or "exit failed")[:300]})
            break

        # Higher-timeframe context filter: block counter-trend / falling-knife
        # / stop-inside-support plans before they become tickets.
        _plan = read_json(trader_dir / "plan.json", {}) or {}
        _filter = None
        if config.filters.enabled:
            try:
                import yfinance as _yf
                _daily = _yf.Ticker(sym).history(period="1y", auto_adjust=True)
                _filter = evaluate_plan(
                    _plan,
                    _daily,
                    atr_multiple=config.filters.atr_multiple,
                    max_recent_drop_pct=config.filters.max_recent_drop_pct,
                )
            except Exception:
                _filter = None
            if _filter is not None and not _filter.allowed:
                plan_status = "BLOCKED_CONTEXT"
                errors.append({
                    "stage": "context_filter",
                    "symbol": sym,
                    "error": "; ".join(_filter.reasons)[:500],
                })
                try:
                    from investment_engine.history import record_decision
                    record_decision(
                        sym, "BLOCKED_CONTEXT", "; ".join(_filter.reasons),
                        source="plan_filter",
                        mode=config.execution.environment,
                        plan=_plan if isinstance(_plan, dict) else {},
                    )
                except Exception:
                    pass
                break

        # time machine
        res = runner(
            _vendor_rel(vr, "trader-timemachine/timemachine.py"),
            ["run", "--write"],
            300,
            True,
            state_root,
            None,
        )
        if not _tool_ok(res):
            errors.append({"stage": "timemachine", "symbol": sym, "error": (res.stderr or "timemachine failed")[:300]})

        # budget sizing
        res = runner(
            _vendor_rel(vr, "trader-budget/size.py"),
            ["--write"],
            30,
            True,
            state_root,
            None,
        )
        if not _tool_ok(res):
            errors.append({"stage": "budget", "symbol": sym, "error": (res.stderr or "budget failed")[:300]})

        # risk check (nonstop: pretend market is open at 10:15 ET so the
        # market-hours gate never blocks order placement outside session hours)
        from datetime import datetime as _dt
        try:
            import zoneinfo as _zi
            _ny = _zi.ZoneInfo("America/New_York")
            _now_str = _dt.now(_ny).strftime("%Y-%m-%d 10:15")
        except Exception:
            _now_str = _dt.now().strftime("%Y-%m-%d 10:15")
        res = runner(
            _vendor_rel(vr, "trader-risk/check.py"),
            ["--now", _now_str],  # write verdicts so ticket.py show reports READY
            30,
            True,
            state_root,
            None,
        )
        if not _tool_ok(res):
            errors.append({"stage": "risk", "symbol": sym, "error": (res.stderr or "risk failed")[:300]})

        # ticket
        res = runner(
            _vendor_rel(vr, "trader-broker/ticket.py"),
            ["show"],
            30,
            True,
            state_root,
            None,
        )
        if _tool_ok(res):
            tickets[sym] = res.payload
        else:
            errors.append({"stage": "ticket", "symbol": sym, "error": (res.stderr or "ticket failed")[:300]})

        plan_status = "PLANNED"
        break

    payload = {
        "status": "OK" if plan_symbol and not errors else ("DEGRADED" if errors else plan_status),
        "plan_symbol": plan_symbol,
        "plan_status": plan_status,
        "filter": _filter.to_dict() if _filter is not None else None,
        "tickets": tickets,
        "errors": errors,
        "generated_at": datetime.now().isoformat(),
    }
    write_json(state_root / "planning.json", payload)

    if plan_symbol:
        try:
            from investment_engine.history import record_decision
            _plan = read_json(trader_dir / "plan.json", {}) or {}
            _reason = (
                f"plan: entry={_plan.get('entry')} stop={_plan.get('stop')} "
                f"target={_plan.get('target')} ({_plan.get('target_label', '')}); "
                f"setup={_plan.get('setup', '')}"
            )
            record_decision(
                plan_symbol,
                "PLAN",
                _reason,
                source="trader-exit",
                mode=config.execution.environment,
                plan=_plan if isinstance(_plan, dict) else {},
            )
        except Exception:
            pass
    return payload


def _vendor_rel(vendor_root: Path, rel: str) -> Path:
    return Path(vendor_root) / rel

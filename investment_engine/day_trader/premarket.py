"""Premarket read-only pack for the day-trader integration."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DayTraderConfig
from .runner import ToolResult, run_tool
from .state import ensure_state_root, read_json, write_json
from .universe_builder import build_universe_symbols, write_universe_file


VENDOR_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "day_trader_skill"


def _vendor(script_rel: str) -> Path:
    return VENDOR_ROOT / script_rel


def _sec_user_agent() -> str:
    return os.getenv("SEC_USER_AGENT", "PortfolioAI_Assistant contact@example.com")


def run_premarket(
    config: DayTraderConfig,
    runner=run_tool,
    state_root: str | Path = "data/day_trader",
    vendor_root: str | Path | None = None,
    portfolio_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Run the premarket read-only pack. Never raises."""
    state_root = ensure_state_root(state_root)
    trader_dir = state_root / "trader"
    vr = Path(vendor_root) if vendor_root is not None else VENDOR_ROOT

    # Generate the config the vendored tools expect.
    write_json(
        trader_dir / "config.json",
        {
            "budget": config.budget.account_value,
            "cash_buffer_pct": config.budget.cash_buffer_pct,
            "max_position_pct": config.budget.max_position_pct,
            "max_order_usd": 100000,
            "min_order_usd": 5,
            "max_loss_per_trade_usd": config.budget.max_loss_per_trade,
            "max_daily_loss_usd": config.budget.max_daily_loss,
            "max_trades_per_day": config.budget.max_trades_per_day,
            "min_reward_risk": 1.0,
            # Nonstop trading: no entry window restriction.
            "no_entries_before": "00:00",
            "no_entries_after": "23:59",
            "flat_by": "23:59",
            "fractional": False,
            "broker": "trading212",
            "paper": True,
            "blocked": [],
            "allow_options": False,
            "allow_margin": False,
            "allow_short": True,
            "pdt_guard": False,
            "sec_user_agent": _sec_user_agent(),
        },
    )

    errors: list[dict[str, Any]] = []

    # 0. multi-market universe (S&P 500 + portfolio + EU/China extras)
    universe_path = trader_dir / "universe.txt"
    try:
        symbols_list = build_universe_symbols(config, portfolio_symbols=portfolio_symbols)
        write_universe_file(symbols_list, universe_path)
    except Exception as exc:
        errors.append({"stage": "universe", "error": f"{type(exc).__name__}: {exc}"[:300]})
        symbols_list = []

    # 1. scanner daily
    res = runner(
        _vendor_rel(vr, "trader-scanner/scan.py"),
        ["daily", "--limit", str(config.universe_limit), "--universe", "trader/universe.txt"],
        900,
        True,
        state_root,
        None,
    )
    watchlist: dict[str, Any] = {}
    if isinstance(res.payload, dict):
        watchlist = res.payload
        write_json(trader_dir / "watchlist.json", watchlist)
    else:
        errors.append({"stage": "scanner_daily", "error": (res.stderr or "scanner failed")[:300]})

    hits = [h for h in (watchlist.get("hits") or []) if isinstance(h, dict) and h.get("symbol")]
    symbols = [str(h["symbol"]).upper() for h in hits[: config.watchlist_limit]]

    # 2. news
    news: dict[str, Any] = {}
    if symbols:
        res = runner(
            _vendor_rel(vr, "trader-news/news.py"),
            ["--tickers", ",".join(symbols), "--hours", "24"],
            120,
            True,
            state_root,
            None,
        )
        if isinstance(res.payload, dict):
            news = res.payload
        else:
            errors.append({"stage": "news", "error": (res.stderr or "news failed")[:300]})

    # 3. analyst (SEC facts)
    analyst: dict[str, Any] = {}
    if symbols:
        res = runner(
            _vendor_rel(vr, "trader-analyst/facts.py"),
            symbols + [],
            120,
            True,
            state_root,
            None,
        )
        # facts.py expects tickers as positional then --json; runner appends --json
        if isinstance(res.payload, (dict, list)):
            analyst = res.payload
        else:
            errors.append({"stage": "analyst", "error": (res.stderr or "analyst failed")[:300]})

    # 4. pelosi tracker
    pelosi: dict[str, Any] = {}
    if config.report.include_pelosi:
        res = runner(
            _vendor_rel(vr, "trader-pelosi/ptr.py"),
            ["index", "--year", str(datetime.now().year)],
            120,
            True,
            state_root,
            None,
        )
        if isinstance(res.payload, (dict, list)):
            pelosi = res.payload
        else:
            errors.append({"stage": "pelosi", "error": (res.stderr or "pelosi failed")[:300]})

    status = "OK" if not errors else "DEGRADED"
    payload = {
        "status": status,
        "universe": len(symbols_list),
        "watchlist": watchlist,
        "symbols": symbols,
        "news": news,
        "analyst": analyst,
        "pelosi": pelosi,
        "errors": errors,
        "generated_at": datetime.now().isoformat(),
    }
    write_json(state_root / "premarket.json", payload)
    return payload


def _vendor_rel(vendor_root: Path, rel: str) -> Path:
    return Path(vendor_root) / rel

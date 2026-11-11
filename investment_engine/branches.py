"""Live and demo branches of one run.

A scheduled run analyses **both** accounts:

* **live** — the real account. Read-only: it produces recommendations and never
  places an order (three independent guards keep live execution disabled).
* **demo** — the paper account. It has its own portfolio snapshot, its own AI
  context and it is the only branch allowed to place orders.

What is shared, and what is not:

===============  ==========================================================
shared           asset universe, market data (OHLCV/technicals), news corpus
isolated         portfolio snapshot, prompt context, AI provider instance,
                 run state, decisions, orders, report folder
===============  ==========================================================

Sharing the expensive market/news fetches is why both branches can run in one
process at acceptable cost; keeping the portfolio context isolated is what stops
the demo branch from "remembering" live holdings (and vice versa).
"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from typing import Any

from investment_engine.config.settings import EngineSettings
from investment_engine.schemas.context import AssetInput

logger = logging.getLogger(__name__)

VALID_ENVIRONMENTS = ("live", "demo")


def _demo_client():
    """Demo T212 client (paper account). Never live."""
    from investment_engine.day_trader.broker.t212_orders import T212OrderClient

    key = os.getenv("T212_DEMO_API_KEY", "")
    secret = os.getenv("T212_DEMO_API_SECRET", "")
    if not key:
        raise RuntimeError("T212_DEMO_API_KEY is not configured")
    return T212OrderClient("demo", key, secret)


def _position_rows(payload: Any) -> list[dict[str, Any]]:
    items = payload.get("items") if isinstance(payload, dict) else payload
    return [row for row in (items or []) if isinstance(row, dict)]


def demo_snapshot() -> dict[str, Any]:
    """Build the canonical snapshot shape from the demo account.

    The engine expects ``status``, ``account_summary``, ``cash`` and
    ``all_positions`` (see ``portfolio/t212_view.py``). Values are in EUR, taken
    from the broker's own ``walletImpact`` block so no FX guesswork is added.
    """
    client = _demo_client()
    positions = _position_rows(client.get_positions())
    summary = client.get_account_summary() or {}
    if isinstance(summary, dict) and summary.get("status") in ("error", "network_error"):
        raise RuntimeError(f"demo account summary failed: {summary.get('error')}")

    rows: list[dict[str, Any]] = []
    for pos in positions:
        instrument = pos.get("instrument") or {}
        ticker = str(instrument.get("ticker") or "")
        quantity = float(pos.get("quantity") or 0)
        if not ticker or quantity == 0:
            continue
        wallet = pos.get("walletImpact") or {}
        value_eur = float(wallet.get("currentValue") or 0.0)
        cost_eur = float(wallet.get("totalCost") or 0.0)
        pnl_eur = float(wallet.get("unrealizedProfitLoss") or 0.0)
        currency = str(instrument.get("currency") or "EUR")
        avg_price = float(pos.get("averagePricePaid") or 0.0)
        last_price = float(pos.get("currentPrice") or 0.0)
        rows.append({
            "symbol": ticker.split("_")[0],
            "broker_symbol": ticker,
            "quantity": quantity,
            "value_eur": value_eur,
            "pnl_eur": pnl_eur,
            "pnl_pct": (pnl_eur / cost_eur * 100.0) if cost_eur else 0.0,
            "average_price_eur": avg_price,
            "current_price_eur": last_price,
            "quote_currency": currency,
            "price_unit": currency,
        })

    cash_block = summary.get("cash") or {}
    invest_block = summary.get("investments") or {}
    cash = float(cash_block.get("availableToTrade") or 0.0)
    invested = float(invest_block.get("currentValue") or 0.0)
    total_equity = float(summary.get("totalValue") or (cash + invested))

    return {
        "status": "ok",
        "reconciliation_ok": True,
        "source": "t212_demo",
        "account_id": summary.get("id"),
        "account_summary": {
            "total_equity": total_equity,
            "cash_free": cash,
            "cash": cash,
            "invested": invested,
            "positions_count": len(rows),
            "positions": rows,
            "all_positions": rows,
            "currency": summary.get("currency") or "EUR",
        },
        "cash": {"free": cash, "invested": invested},
        "all_positions": rows,
        "positions": rows,
        "reconciliation": {
            "status": "PASS",
            "detail": "demo snapshot derived from /equity/portfolio and account summary",
        },
    }


def run_branch(
    mode: str,
    assets: list[AssetInput],
    settings: EngineSettings,
    *,
    run_id: str | None = None,
    language: str = "English",
    reuse_market_data: bool = False,
) -> dict[str, Any]:
    """Run one branch end to end and return its engine result.

    ``mode="live"`` fetches the live account itself (read-only).
    ``mode="demo"`` injects its own demo snapshot through the settings override,
    so the pipeline never touches the live account in that branch.
    """
    if mode not in VALID_ENVIRONMENTS:
        raise ValueError(f"unknown branch: {mode}")

    from investment_engine.main import run_engine

    branch_settings = settings
    if mode == "demo":
        branch_settings = replace(settings, t212_snapshot_override=demo_snapshot())
    elif settings.t212_snapshot_override:
        # Live branch must never inherit a stale override from another branch.
        branch_settings = replace(settings, t212_snapshot_override=None)

    context = {
        "mode": mode,
        "branch": mode,
        "language": language,
        "reuse_market_data": reuse_market_data,
    }
    if run_id:
        context["run_id"] = run_id

    logger.info("Branch %s: starting", mode)
    result = run_engine(assets, portfolio_context=context, settings=branch_settings)
    logger.info("Branch %s: finished (status=%s)", mode, result.get("status"))
    return result


def report_subdir(mode: str) -> str:
    """Where a branch publishes its reports inside ``reports/``."""
    return f"current/{mode}"

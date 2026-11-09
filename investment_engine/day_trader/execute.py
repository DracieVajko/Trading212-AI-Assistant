"""Demo-only execution of day-trader tickets.

Places orders on the T212 demo account only. Never live: the guard and the
client-level interlock both refuse live placement.
"""

from __future__ import annotations

import os
from typing import Any


def execute_demo_plan(
    config: Any,
    ticket: dict[str, Any],
    client: Any,
    env: dict[str, str] | None = None,
    *,
    db_path: str = "data/day_trader/audit.db",
    history_mode: str = "demo",
) -> dict[str, Any]:
    from investment_engine.day_trader.broker.guard import evaluate
    from investment_engine.history import record_trade

    env = dict(env or os.environ)
    symbol = str(ticket.get("ticker") or ticket.get("symbol") or "").upper()
    side = str(ticket.get("side", "BUY")).upper()
    qty = float(ticket.get("quantity", 0) or 0)
    if not symbol or qty <= 0:
        return {"status": "FAILED", "error": "missing symbol or quantity", "order": None, "reasons": []}

    intent = {
        "symbol": symbol,
        "side": side,
        "notional": float(ticket.get("notional", 0) or 0),
        "manual_approval": True,
    }
    decision = evaluate(
        intent,
        config,
        env,
        recon_status=str(ticket.get("recon_status", "PASS")),
        account_currency=str(ticket.get("account_currency", "EUR")),
        kill_switch_path=ticket.get("kill_switch_path"),
    )
    if not decision.allowed:
        return {"status": "BLOCKED", "order": None, "reasons": decision.reasons}

    if getattr(client, "environment", "") != "demo":
        return {"status": "BLOCKED", "order": None, "reasons": ["client is not demo"]}

    signed_qty = qty if side == "BUY" else -abs(qty)
    try:
        order = client.place_market_order(symbol, signed_qty)
    except Exception as exc:  # fail closed, never crash the run
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "order": None, "reasons": []}

    oid = order.get("id") if isinstance(order, dict) else None
    if oid is None:
        return {"status": "FAILED", "error": "order rejected", "order": order, "reasons": []}

    try:
        record_trade(
            symbol, side, qty, order_id=str(oid), status="PLACED",
            reason=str(ticket.get("reason", "demo execution")),
            source="execute_demo_plan", mode=history_mode, db_path=db_path,
        )
    except Exception:
        pass

    return {"status": "PLACED", "order": order, "reasons": []}

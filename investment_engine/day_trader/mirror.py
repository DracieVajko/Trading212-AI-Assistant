"""Mirror a live Trading 212 account into the demo account (paper)."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any

from .broker.audit import record_event, record_intent, update_intent_status
from .broker.guard import evaluate
from .broker.t212_orders import T212OrderClient


def _positions_map(client: T212OrderClient) -> dict[str, float]:
    res = client.get_positions()
    if not isinstance(res, list):
        return {}
    out: dict[str, float] = {}
    for p in res:
        if not isinstance(p, dict):
            continue
        ticker = (p.get("instrument") or {}).get("ticker")
        if not ticker:
            continue
        try:
            out[str(ticker)] = float(p.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            out[str(ticker)] = 0.0
    return out


def compute_mirror_plan(live_client: T212OrderClient, demo_client: T212OrderClient) -> list[dict[str, Any]]:
    live_map = _positions_map(live_client)
    demo_map = _positions_map(demo_client)
    actions: list[dict[str, Any]] = []
    for ticker in sorted(set(live_map) | set(demo_map)):
        live_qty = live_map.get(ticker, 0.0)
        demo_qty = demo_map.get(ticker, 0.0)
        delta = live_qty - demo_qty
        if abs(delta) < 1e-9:
            continue
        actions.append({
            "ticker": ticker,
            "live_qty": live_qty,
            "demo_qty": demo_qty,
            "delta": delta,
            "side": "BUY" if delta > 0 else "SELL",
            "quantity": abs(delta),
        })
    return actions


def mirror_to_demo(
    live_client: T212OrderClient,
    demo_client: T212OrderClient,
    config: Any,
    *,
    execute: bool = False,
    db_path: str = "data/day_trader/audit.db",
    kill_switch_path: str | None = None,
) -> dict[str, Any]:
    actions = compute_mirror_plan(live_client, demo_client)
    if not execute:
        return {"mode": "dry-run", "actions": actions, "executed": [], "blocked": []}
    if getattr(demo_client, "environment", None) is not None and getattr(demo_client, "environment", "") != "demo":
        return {"mode": "blocked", "actions": actions, "executed": [], "blocked": [{"reason": "demo client is not demo"}]}

    env = {
        "T212_ORDER_ENABLED": "1",
        "T212_ORDER_ENV": "demo",
    }
    allowed = {a["ticker"] for a in actions}
    executed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    daily_orders = 0
    daily_loss = 0.0

    for a in actions:
        intent = {
            "symbol": a["ticker"],
            "side": a["side"],
            "notional": a["quantity"] * 1.0,
            "manual_approval": True,
        }
        decision = evaluate(
            intent,
            config,
            env,
            recon_status="PASS",
            account_currency="EUR",
            kill_switch_path=kill_switch_path,
            daily_orders=daily_orders,
            daily_loss=daily_loss,
            allowed_symbols=allowed,
        )
        if not decision.allowed:
            blocked.append({"action": a, "reasons": decision.reasons})
            continue
        qty = a["quantity"] if a["side"] == "BUY" else -a["quantity"]
        fp = hashlib.sha256(
            f"mirror|{a['ticker']}|{a['side']}|{a['quantity']}".encode()
        ).hexdigest()
        iid = record_intent(
            datetime.now().date().isoformat(),
            a["ticker"],
            a["side"],
            a["quantity"],
            "market",
            fp,
            db_path=db_path,
        )
        order = demo_client.place_market_order(a["ticker"], qty)
        oid = order.get("id") if isinstance(order, dict) else None
        if oid is not None:
            update_intent_status(iid, "PLACED", broker_order_id=str(oid), db_path=db_path)
            record_event(iid, "placed", broker_order_id=str(oid), payload=order, db_path=db_path)
            try:
                from investment_engine.history import record_trade
                record_trade(
                    a["ticker"], a["side"], a["quantity"], order_id=str(oid),
                    status="PLACED", reason="demo mirror of live account",
                    source="mirror_to_demo", mode="demo",
                )
            except Exception:
                pass
            daily_orders += 1
        else:
            update_intent_status(iid, "FAILED", db_path=db_path)
            record_event(iid, "failed", payload=order, db_path=db_path)
        executed.append({"action": a, "order": order})

    return {"mode": "executed", "actions": actions, "executed": executed, "blocked": blocked}

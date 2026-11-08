"""Bracket emulation for Trading 212 (no native OCO)."""

from __future__ import annotations

import time
from typing import Any


def place_entry(client: Any, intent: dict[str, Any]) -> dict[str, Any]:
    side = str(intent.get("side", "BUY")).upper()
    qty = float(intent.get("quantity", 0) or 0)
    if side == "SELL":
        qty = -abs(qty)
    order_type = str(intent.get("order_type", "market")).lower()
    if order_type == "limit":
        return client.place_limit_order(intent["ticker"], qty, float(intent["limit_price"]))
    if order_type == "stop":
        return client.place_stop_order(intent["ticker"], qty, float(intent["stop_price"]))
    if order_type == "stop_limit":
        return client.place_stop_limit_order(
            intent["ticker"], qty, float(intent["stop_price"]), float(intent["limit_price"])
        )
    return client.place_market_order(intent["ticker"], qty)


def wait_for_fill(client: Any, order_id: Any, timeout_s: int = 120, poll_s: float = 2.0) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        res = client.get_order(order_id)
        status = str(res.get("status", "")).upper()
        if status in ("FILLED", "PARTIALLY_FILLED", "CANCELLED", "REJECTED"):
            return status
        time.sleep(poll_s)
    return "TIMEOUT"


def place_exits(client: Any, intent: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    ticker = intent["ticker"]
    qty = float(intent.get("quantity", 0) or 0)
    sell_qty = -abs(qty)
    stop_order = client.place_stop_order(ticker, sell_qty, float(intent["stop_price"]))
    target_order = client.place_limit_order(ticker, sell_qty, float(intent["target_price"]))
    return stop_order, target_order


def manage_exits(client: Any, stop_id: Any, target_id: Any, timeout_s: int = 300, poll_s: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        stop = client.get_order(stop_id)
        target = client.get_order(target_id)
        stop_status = str(stop.get("status", "")).upper()
        target_status = str(target.get("status", "")).upper()
        if stop_status in ("FILLED", "CANCELLED", "REJECTED"):
            try:
                client.cancel_order(target_id)
            except Exception:
                pass
            return {"filled": "stop", "stop_status": stop_status, "target_status": target_status}
        if target_status in ("FILLED", "CANCELLED", "REJECTED"):
            try:
                client.cancel_order(stop_id)
            except Exception:
                pass
            return {"filled": "target", "stop_status": stop_status, "target_status": target_status}
        time.sleep(poll_s)
    return {"filled": "none", "stop_status": "TIMEOUT", "target_status": "TIMEOUT"}


def run_bracket(client: Any, intent: dict[str, Any], guard_decision: Any) -> dict[str, Any]:
    if not getattr(guard_decision, "allowed", False):
        return {"status": "BLOCKED", "reasons": list(getattr(guard_decision, "reasons", []))}
    entry = place_entry(client, intent)
    entry_id = entry.get("id")
    if entry_id is None:
        return {"status": "ENTRY_FAILED", "entry": entry}
    entry_status = wait_for_fill(client, entry_id, int(intent.get("entry_timeout_s", 120)))
    if entry_status not in ("FILLED", "PARTIALLY_FILLED"):
        try:
            client.cancel_order(entry_id)
        except Exception:
            pass
        return {"status": "ENTRY_NOT_FILLED", "entry": entry, "entry_status": entry_status}
    stop_order, target_order = place_exits(client, intent)
    stop_id = stop_order.get("id")
    target_id = target_order.get("id")
    exit_result = manage_exits(client, stop_id, target_id, int(intent.get("exit_timeout_s", 300)))
    result = {
        "status": "COMPLETED",
        "entry": entry,
        "stop": stop_order,
        "target": target_order,
        "exit": exit_result,
    }
    try:
        from investment_engine.history import record_trade
        record_trade(
            intent.get("ticker", "?"), "BUY", float(intent.get("quantity", 0) or 0),
            price=float(intent.get("limit_price") or intent.get("entry") or 0) or None,
            order_id=str(entry_id), status="FILLED",
            reason=f"bracket entry; stop={intent.get('stop_price')} target={intent.get('target_price')}",
            source="bracket", mode=str(intent.get("mode", "demo")),
            plan={k: intent.get(k) for k in ("entry", "stop_price", "target_price", "order_type")},
        )
    except Exception:
        pass
    return result

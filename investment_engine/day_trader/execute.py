"""Demo-only execution of day-trader tickets.

Places orders on the T212 demo account only. Never live: the guard and the
client-level interlock both refuse live placement.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import date
from typing import Any

DEFAULT_REASON = "demo execution from day-trader plan"


def _today_iso() -> str:
    return date.today().isoformat()


def normalize_ticket(
    sym: str,
    ticket: Any,
    known_instruments: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Normalize a vendored ticket (dict or list, fields possibly under tool_input).

    Returns a dict ready for ``execute_demo_plan`` or None when the ticket
    cannot be mapped to a T212 instrument safely.
    """
    if isinstance(ticket, list):
        ticket = ticket[0] if ticket else None
    if not isinstance(ticket, dict):
        return None
    tool_input = ticket.get("tool_input")
    if isinstance(tool_input, dict):
        raw = {**ticket, **tool_input}
    else:
        raw = dict(ticket)

    side = str(raw.get("side") or "").upper()
    if side not in ("BUY", "SELL"):
        return None

    try:
        qty = float(raw.get("quantity", raw.get("qty", 0)) or 0)
    except (TypeError, ValueError):
        return None

    symbol = str(raw.get("symbol") or raw.get("ticker") or sym or "").upper()
    if not symbol:
        return None

    known = {str(k).upper(): v for k, v in (known_instruments or {}).items()}
    if symbol in known:
        instrument = str(known[symbol])
    elif "_" in symbol:
        instrument = symbol
    elif "." in symbol:
        # EU/HK Yahoo suffix: cannot infer the T212 instrument safely.
        return None
    else:
        instrument = f"{symbol}_US_EQ"

    return {
        "ticker": instrument,
        "side": side,
        "quantity": qty,
        "notional": raw.get("notional", 0),
        "reason": raw.get("reason") or DEFAULT_REASON,
    }


def _count_placed_today(db_path: str | os.PathLike[str], session_date: str) -> int:
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM order_intents WHERE session_date = ? AND status = 'PLACED'",
                (session_date,),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def execute_demo_plan(
    config: Any,
    ticket: dict[str, Any],
    client: Any,
    env: dict[str, str] | None = None,
    *,
    db_path: str = "data/day_trader/audit.db",
    history_mode: str = "demo",
) -> dict[str, Any]:
    from investment_engine.day_trader.broker.audit import (
        record_intent,
        update_intent_status,
    )
    from investment_engine.day_trader.broker.guard import evaluate
    from investment_engine.history import record_trade

    env = dict(env or os.environ)
    if history_mode not in ("demo", "live"):
        history_mode = "demo"
    symbol = str(ticket.get("ticker") or ticket.get("symbol") or "").upper()
    side = str(ticket.get("side", "BUY")).upper()
    try:
        qty = float(ticket.get("quantity", 0) or 0)
        notional = float(ticket.get("notional", 0) or 0)
    except (TypeError, ValueError):
        return {"status": "FAILED", "error": "invalid quantity/notional", "order": None, "reasons": []}
    if not symbol or qty <= 0:
        return {"status": "FAILED", "error": "missing symbol or quantity", "order": None, "reasons": []}
    if side not in ("BUY", "SELL"):
        return {"status": "FAILED", "error": f"invalid side: {side}", "order": None, "reasons": []}
    try:
        daily_orders = int(ticket.get("daily_orders", 0) or 0)
        daily_loss = float(ticket.get("daily_loss", 0.0) or 0.0)
    except (TypeError, ValueError):
        return {"status": "FAILED", "error": "invalid daily_orders/daily_loss", "order": None, "reasons": []}

    session_date = _today_iso()
    reason = str(ticket.get("reason") or DEFAULT_REASON)
    fp = hashlib.sha256(
        f"{session_date}|{symbol}|{side}|{qty:.8f}|{reason}".encode("utf-8")
    ).hexdigest()
    try:
        intent_id = record_intent(
            session_date, symbol, side, qty, "MARKET", fp, db_path=db_path,
        )
    except sqlite3.IntegrityError:
        return {"status": "BLOCKED", "order": None, "reasons": ["duplicate intent"]}
    except Exception as exc:  # fail closed: no audited intent, no order
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "order": None, "reasons": []}

    if not daily_orders:
        daily_orders = _count_placed_today(db_path, session_date)

    def _mark(status: str, broker_order_id: str | None = None) -> None:
        try:
            update_intent_status(intent_id, status, broker_order_id=broker_order_id, db_path=db_path)
        except Exception:
            pass

    intent = {
        "symbol": symbol,
        "side": side,
        "notional": notional,
        "manual_approval": True,
        "daily_orders": daily_orders,
    }
    decision = evaluate(
        intent,
        config,
        env,
        recon_status=str(ticket.get("recon_status", "PASS")),
        account_currency=str(ticket.get("account_currency", "EUR")),
        kill_switch_path=ticket.get("kill_switch_path"),
        daily_orders=daily_orders,
        daily_loss=daily_loss,
        allowed_symbols=ticket.get("allowed_symbols"),
    )
    if not decision.allowed:
        _mark("FAILED")
        return {"status": "BLOCKED", "order": None, "reasons": decision.reasons}

    if getattr(client, "environment", "") != "demo":
        _mark("FAILED")
        return {"status": "BLOCKED", "order": None, "reasons": ["client is not demo"]}

    signed_qty = qty if side == "BUY" else -abs(qty)
    try:
        order = client.place_market_order(symbol, signed_qty)
    except Exception as exc:  # fail closed, never crash the run
        _mark("FAILED")
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "order": None, "reasons": []}

    oid = order.get("id") if isinstance(order, dict) else None
    if oid is None:
        _mark("FAILED")
        return {"status": "FAILED", "error": "order rejected", "order": order, "reasons": []}

    _mark("PLACED", broker_order_id=str(oid))

    try:
        record_trade(
            symbol, side, qty, order_id=str(oid), status="PLACED",
            reason=reason,
            source="execute_demo_plan", mode=history_mode, db_path=db_path,
        )
    except Exception:
        pass

    return {"status": "PLACED", "order": order, "reasons": []}

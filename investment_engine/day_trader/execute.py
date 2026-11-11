"""Demo-only execution of day-trader tickets.

Places market entries plus optional stop/target exits (emulated bracket) on the
T212 demo account only. Never live: the guard and the client-level interlock
both refuse live placement.

Reconciliation: demo paper trading may opt in to unverified recon because
reconciliation of the live account is not available in the day-trader phase.
Set ``T212_DEMO_ALLOW_UNVERIFIED_RECON=1`` to treat a missing ``recon_status``
as PASS; otherwise a missing status is reported as UNKNOWN and the guard blocks.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from datetime import date
from typing import Any

DEFAULT_REASON = "demo execution from day-trader plan"

logger = logging.getLogger(__name__)


def _today_iso() -> str:
    return date.today().isoformat()


def normalize_ticket(
    sym: str,
    ticket: Any,
    known_instruments: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Normalize a vendored ticket (dict or list, fields possibly under tool_input).

    Returns a dict ready for ``execute_demo_plan`` or None when the ticket is
    not ready or cannot be mapped to a T212 instrument safely.
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

    if raw.get("ready") is False:
        return None
    status = raw.get("status")
    if isinstance(status, str) and status.strip().lower() in {"blocked", "not_ready", "rejected"}:
        return None

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
        "stop_price": raw.get("stop_price") or raw.get("stop_loss_stop_price") or raw.get("stop"),
        "target_price": raw.get("target_price") or raw.get("take_profit_limit_price") or raw.get("target"),
    }


def demo_execution_allowed(allow_orders: bool, environment: str) -> bool:
    return bool(allow_orders) and str(environment).lower() == "demo"


def execute_demo_tickets(
    config: Any,
    payload: dict[str, Any] | None,
    client: Any,
    known_instruments: dict[str, str] | None = None,
    *,
    db_path: str = "data/day_trader/audit.db",
) -> list[dict[str, Any]]:
    """Normalize every ticket and execute it; return per-ticket results."""
    results: list[dict[str, Any]] = []
    tickets = (payload or {}).get("tickets") or {}
    for sym, ticket in tickets.items():
        norm = normalize_ticket(sym, ticket, known_instruments)
        if norm is None:
            print(f"Demo execute {sym}: skipped (unmapped or incomplete ticket)")
            continue
        res = execute_demo_plan(config, norm, client, db_path=db_path)
        print(f"Demo execute {sym}: {res['status']} {res.get('reasons') or res.get('error') or ''}")
        results.append({"symbol": sym, "result": res})
    return results


def _count_placed_today(db_path: str | os.PathLike[str], session_date: str) -> int:
    """Count today's PLACED intents; -1 when the audit DB cannot be read."""
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
        return -1


def _owned_quantity(client: Any, symbol: str, *, attempts: int = 5, delay: float = 2.0) -> float | None:
    """Return the quantity actually held in the account for ``symbol``.

    A market order fills asynchronously, so immediately after placing one the
    account can still show the previous (possibly fractional) position. Sizing
    a protective exit from the requested quantity then fails with
    ``selling-equity-not-owned`` and leaves the position unprotected.

    Returns ``None`` when the position cannot be read at all, so the caller can
    fall back to the requested size instead of silently skipping protection.
    """
    base = symbol.split("_")[0].upper()

    def _read() -> float | None:
        get_positions = getattr(client, "get_positions", None)
        if get_positions is None:
            return None
        try:
            payload = get_positions() or {}
        except Exception:
            return None
        if isinstance(payload, dict):
            if payload.get("error") or payload.get("status") in ("error", "network_error", "auth_failed"):
                return None
            items = payload.get("items")
        else:
            items = payload
        for row in items or []:
            if not isinstance(row, dict):
                continue
            instrument = row.get("instrument")
            ticker = str(
                row.get("ticker")
                or (instrument.get("ticker") if isinstance(instrument, dict) else "")
                or ""
            ).upper()
            if ticker != symbol and ticker.split("_")[0] != base:
                continue
            # T212 reports the sellable size separately once orders are resting;
            # that is the quantity the broker will actually accept for an exit.
            raw_qty = row.get("quantityAvailableForTrading", row.get("quantity", 0))
            try:
                return abs(float(raw_qty or 0))
            except (TypeError, ValueError):
                return None
        return 0.0

    owned = _read()
    for _ in range(max(0, attempts - 1)):
        if owned is None or owned > 0:
            break
        time.sleep(delay)
        owned = _read()
    return owned


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
        find_intent_by_fingerprint,
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
        existing = find_intent_by_fingerprint(fp, db_path=db_path)
        status = str((existing or {}).get("status", "")).upper()
        if not existing or status not in ("FAILED", "BLOCKED"):
            return {"status": "BLOCKED", "order": None, "reasons": ["duplicate intent"]}
        # Same-day retry after a failed or blocked attempt: reuse the existing
        # intent row instead of inserting a duplicate fingerprint.
        intent_id = int(existing["id"])
        try:
            update_intent_status(intent_id, "PENDING", db_path=db_path)
        except Exception as exc:
            return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "order": None, "reasons": []}
    except Exception as exc:  # fail closed: no audited intent, no order
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "order": None, "reasons": []}

    if not daily_orders:
        daily_orders = _count_placed_today(db_path, session_date)
    if daily_orders < 0:
        _mark_intent(update_intent_status, intent_id, "FAILED", db_path=db_path)
        return {"status": "BLOCKED", "order": None, "reasons": ["audit db unavailable"]}

    def _mark(status: str, broker_order_id: str | None = None) -> None:
        _mark_intent(update_intent_status, intent_id, status, broker_order_id, db_path=db_path)

    account_currency = getattr(getattr(config, "budget", None), "account_currency", None)
    if not account_currency:
        account_currency = ticket.get("account_currency") or "UNKNOWN"

    recon_status = ticket.get("recon_status")
    if not recon_status:
        env_name = str(getattr(getattr(config, "execution", None), "environment", "")).lower()
        if env_name == "demo" and os.getenv("T212_DEMO_ALLOW_UNVERIFIED_RECON") == "1":
            recon_status = "PASS"
        else:
            recon_status = "UNKNOWN"

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
        recon_status=str(recon_status),
        account_currency=str(account_currency),
        kill_switch_path=ticket.get("kill_switch_path"),
        daily_orders=daily_orders,
        daily_loss=daily_loss,
        allowed_symbols=ticket.get("allowed_symbols"),
    )
    if not decision.allowed:
        _mark("BLOCKED")
        return {"status": "BLOCKED", "order": None, "reasons": decision.reasons}

    if getattr(client, "environment", "") != "demo":
        _mark("FAILED")
        return {"status": "BLOCKED", "order": None, "reasons": ["client is not demo"]}

    # Order-history-aware dedupe: one order per symbol+side per New York
    # trading day, regardless of quantity or plan changes between runs.
    from investment_engine import order_ledger

    duplicate, existing = order_ledger.check(
        symbol, side, db_path=db_path, exclude_intent_id=intent_id,
    )
    if duplicate:
        _mark("BLOCKED")
        reason_text = order_ledger.describe(existing)
        logger.info("Demo execute %s: blocked, %s", symbol, reason_text)
        return {"status": "BLOCKED", "order": None, "reasons": [reason_text]}

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

    exits: dict[str, Any] = {}
    stop_price = ticket.get("stop_price")
    target_price = ticket.get("target_price")
    if side == "BUY":
        # Protective orders must match what is actually owned. Ask the broker
        # instead of reusing the requested size: a fresh market order may not be
        # filled yet, and the account can already hold a fractional position.
        owned = _owned_quantity(client, symbol)
        if owned is None:
            # Position unreadable: still try to protect, sized from the request.
            exit_qty = abs(qty)
            logger.warning(
                "Demo exits for %s sized from request: position could not be read",
                symbol,
            )
        else:
            exit_qty = min(abs(qty), owned) if owned > 0 else 0.0
        if exit_qty <= 0:
            exits["skipped"] = {
                "error": "no owned quantity; protective orders not placed",
                "requested": abs(qty),
            }
            logger.warning(
                "Demo exits skipped for %s: no position to protect (requested %.8f)",
                symbol, abs(qty),
            )
        else:
            if stop_price is not None:
                try:
                    exits["stop"] = client.place_stop_order(symbol, -exit_qty, float(stop_price))
                except Exception as exc:
                    exits["stop"] = {"error": f"{type(exc).__name__}: {exc}"}
            if target_price is not None:
                try:
                    exits["target"] = client.place_limit_order(symbol, -exit_qty, float(target_price))
                except Exception as exc:
                    exits["target"] = {"error": f"{type(exc).__name__}: {exc}"}
            if exit_qty < abs(qty):
                logger.warning(
                    "Demo exits for %s sized to owned %.8f, requested %.8f",
                    symbol, exit_qty, abs(qty),
                )

    result: dict[str, Any] = {"status": "PLACED", "order": order, "reasons": [], "exits": exits}
    try:
        # Canonical history DB: never the audit DB.
        record_trade(
            symbol, side, qty, order_id=str(oid), status="PLACED",
            reason=reason,
            source="execute_demo_plan", mode=history_mode,
            plan={
                "bracket": ticket.get("bracket"),
                "tool_input": ticket.get("tool_input"),
                "fingerprint": ticket.get("fingerprint"),
                "max_loss": ticket.get("max_loss"),
            } or None,
        )
    except Exception as exc:
        logger.warning("history record_trade failed for %s: %s", symbol, exc)
        result["history_error"] = f"{type(exc).__name__}: {exc}"

    return result


def _mark_intent(
    update_intent_status: Any,
    intent_id: int,
    status: str,
    broker_order_id: str | None = None,
    *,
    db_path: str,
) -> None:
    try:
        update_intent_status(intent_id, status, broker_order_id=broker_order_id, db_path=db_path)
    except Exception:
        pass

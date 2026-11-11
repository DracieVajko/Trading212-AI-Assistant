"""Order ledger: one order per symbol and side per trading day.

The execute layer used to dedupe on a hash of
``date|symbol|side|quantity|reason``. That hash changes whenever the planned
quantity changes by a fraction, so a rerun an hour later placed a second order
for the same idea. This module answers the question the trader actually cares
about: *"has this symbol+side already been bought/sold today?"*

It reads both sources of truth:

* the canonical history files (``history/<mode>/trades.jsonl``) — what really
  reached the broker;
* the day-trader audit DB (``order_intents``) — what was attempted, including
  orders that are still resting.

A "trading day" is the calendar date in New York, so a plan made shortly before
the open and another shortly after it fall on the same day and the second one is
blocked.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HISTORY_ROOT = ROOT / "history"
NY_TZ = ZoneInfo("America/New_York")

# Statuses that mean the order actually reached the broker. ``pending`` is
# deliberately excluded: it is the transient state of the row being written by
# the very call that is asking, and stale pending rows are not real orders.
LIVE_STATUSES = {"placed", "filled", "partially_filled", "submitted"}

DEFAULT_AUDIT_DB = ROOT / "data" / "day_trader" / "audit.db"


def trading_day(moment: datetime | None = None) -> str:
    """Return the New York calendar date for ``moment`` (default: now)."""
    if moment is None:
        moment = datetime.now(tz=NY_TZ)
    elif moment.tzinfo is None:
        moment = moment.replace(tzinfo=NY_TZ)
    return moment.astimezone(NY_TZ).date().isoformat()


def _day_of(timestamp: Any) -> str | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return trading_day(parsed)


def _base_symbol(symbol: str) -> str:
    return str(symbol or "").split("_")[0].upper()


def _history_trades(mode: str) -> Iterable[dict[str, Any]]:
    path = HISTORY_ROOT / mode / "trades.jsonl"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            yield row


def _audit_rows(db_path: str | Path) -> Iterable[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return
    try:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT id, symbol, side, quantity, status, broker_order_id, session_date, created_at"
            " FROM order_intents"
        ):
            yield dict(row)
    except sqlite3.Error:
        return
    finally:
        conn.close()


def find_order(
    symbol: str,
    side: str,
    day: str,
    *,
    modes: tuple[str, ...] = ("demo",),
    db_path: str | Path = DEFAULT_AUDIT_DB,
    exclude_intent_id: int | None = None,
) -> dict[str, Any] | None:
    """Return the first order for ``symbol``/``side`` on ``day``, or None."""
    wanted_symbol = _base_symbol(symbol)
    wanted_side = str(side or "").upper()

    for mode in modes:
        for row in _history_trades(mode):
            if str(row.get("side", "")).upper() != wanted_side:
                continue
            if _base_symbol(row.get("symbol", "")) != wanted_symbol:
                continue
            if _day_of(row.get("ts")) != day:
                continue
            if str(row.get("status", "")).lower() not in LIVE_STATUSES:
                continue
            return {
                "source": f"history/{mode}",
                "symbol": row.get("symbol"),
                "side": wanted_side,
                "quantity": row.get("quantity"),
                "status": row.get("status"),
                "order_id": row.get("order_id"),
                "when": row.get("ts"),
            }

    for row in _audit_rows(db_path):
        if exclude_intent_id is not None and row.get("id") == exclude_intent_id:
            continue
        if str(row.get("side", "")).upper() != wanted_side:
            continue
        if _base_symbol(row.get("symbol", "")) != wanted_symbol:
            continue
        row_day = _day_of(row.get("created_at")) or row.get("session_date")
        if row_day != day:
            continue
        if str(row.get("status", "")).lower() not in LIVE_STATUSES:
            continue
        return {
            "source": "audit_db",
            "symbol": row.get("symbol"),
            "side": wanted_side,
            "quantity": row.get("quantity"),
            "status": row.get("status"),
            "order_id": row.get("broker_order_id"),
            "when": row.get("created_at"),
        }
    return None


def check(
    symbol: str,
    side: str,
    *,
    day: str | None = None,
    modes: tuple[str, ...] = ("demo",),
    db_path: str | Path = DEFAULT_AUDIT_DB,
    exclude_intent_id: int | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Return ``(already_ordered_today, existing_order)``."""
    day = day or trading_day()
    existing = find_order(
        symbol,
        side,
        day,
        modes=modes,
        db_path=db_path,
        exclude_intent_id=exclude_intent_id,
    )
    return existing is not None, existing


def describe(existing: dict[str, Any] | None) -> str:
    """Human-readable reason for a duplicate block."""
    if not existing:
        return "already ordered today"
    return (
        f"already {str(existing.get('side', '')).lower()} {existing.get('symbol')} today"
        f" (order {existing.get('order_id') or 'n/a'}, {existing.get('status')},"
        f" {existing.get('when') or 'time unknown'})"
    )

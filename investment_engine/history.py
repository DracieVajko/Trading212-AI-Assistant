"""Permanent trading history and AI memory.

`history/` is intentionally outside `reports/` and `logs/`, so cleanup and
purge operations cannot delete it. It stores what was bought/sold, why, and
the reasoning/plan behind each decision.

Layout:
  history/history.db          SQLite (trades + decisions, queryable)
  history/live/trades.jsonl   append-only live trade log
  history/live/decisions.jsonl
  history/demo/trades.jsonl
  history/demo/decisions.jsonl
  history/README.md
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HISTORY_ROOT = ROOT / "history"
DB_PATH = HISTORY_ROOT / "history.db"


def runtime_mode(explicit: str | None = None) -> str:
    """Return 'demo' or 'live' for the current run."""
    if explicit in ("demo", "live"):
        return explicit
    env = str(os.getenv("T212_ORDER_ENV", "") or "").strip().lower()
    return env if env in ("demo", "live") else "live"


def _connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            mode TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL,
            value REAL,
            currency TEXT,
            order_id TEXT,
            status TEXT,
            reason TEXT,
            source TEXT,
            plan_json TEXT
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            mode TEXT NOT NULL,
            run_id TEXT,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT,
            confidence REAL,
            source TEXT,
            plan_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(mode);
        CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_decisions_mode ON decisions(mode);
        CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol);
        """
    )
    conn.commit()
    return conn


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def record_trade(
    symbol: str,
    side: str,
    quantity: float,
    *,
    price: float | None = None,
    value: float | None = None,
    currency: str = "EUR",
    order_id: str | None = None,
    status: str = "FILLED",
    reason: str = "",
    source: str = "manual",
    mode: str | None = None,
    plan: dict[str, Any] | None = None,
    db_path: str | Path = DB_PATH,
) -> int:
    """Record a buy/sell in SQLite and the mode-specific JSONL log."""
    mode = runtime_mode(mode)
    ts = datetime.now(timezone.utc).isoformat()
    payload = {
        "ts": ts, "mode": mode, "symbol": str(symbol).upper(), "side": str(side).upper(),
        "quantity": quantity, "price": price, "value": value, "currency": currency,
        "order_id": order_id, "status": status, "reason": reason, "source": source,
        "plan": plan or {},
    }
    _append_jsonl(HISTORY_ROOT / mode / "trades.jsonl", payload)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO trades
            (ts, mode, symbol, side, quantity, price, value, currency, order_id,
             status, reason, source, plan_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, mode, payload["symbol"], payload["side"], quantity, price, value,
             currency, order_id, status, reason, source,
             json.dumps(plan or {}, default=str)),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def record_decision(
    symbol: str,
    action: str,
    reason: str,
    *,
    confidence: float = 0.0,
    source: str = "portfolio_ai",
    run_id: str = "",
    mode: str | None = None,
    plan: dict[str, Any] | None = None,
    db_path: str | Path = DB_PATH,
) -> int:
    """Record an AI decision/reasoning step in SQLite and JSONL."""
    mode = runtime_mode(mode)
    ts = datetime.now(timezone.utc).isoformat()
    payload = {
        "ts": ts, "mode": mode, "run_id": run_id, "symbol": str(symbol).upper(),
        "action": str(action).upper(), "reason": reason, "confidence": confidence,
        "source": source, "plan": plan or {},
    }
    _append_jsonl(HISTORY_ROOT / mode / "decisions.jsonl", payload)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO decisions
            (ts, mode, run_id, symbol, action, reason, confidence, source, plan_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, mode, run_id, payload["symbol"], payload["action"], reason,
             confidence, source, json.dumps(plan or {}, default=str)),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def query_trades(
    mode: str | None = None,
    symbol: str | None = None,
    limit: int = 100,
    db_path: str | Path = DB_PATH,
) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM trades"
        params: list[Any] = []
        clauses = []
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def query_decisions(
    mode: str | None = None,
    symbol: str | None = None,
    limit: int = 100,
    db_path: str | Path = DB_PATH,
) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM decisions"
        params: list[Any] = []
        clauses = []
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def ensure_history_readme() -> Path:
    """Create history/README.md explaining that it is permanent."""
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    readme = HISTORY_ROOT / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Trading history (permanent)\n\n"
            "This folder is deliberately outside `reports/` and `logs/`.\n"
            "Cleanup and purge operations never delete it.\n\n"
            "- `history.db` — SQLite: `trades` and `decisions` tables.\n"
            "- `live/` and `demo/` — append-only JSONL logs per mode.\n\n"
            "Query examples:\n"
            "```python\n"
            "from investment_engine.history import query_trades, query_decisions\n"
            "query_trades(mode='live', limit=20)\n"
            "query_decisions(symbol='AAOI', limit=20)\n"
            "```\n",
            encoding="utf-8",
        )
    return readme

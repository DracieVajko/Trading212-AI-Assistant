"""Signal recorder: stores every recommendation for later backtesting."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DB = "data/portfolio_signals.db"


def _connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trade_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            score REAL,
            confidence INTEGER,
            source TEXT,
            timestamp TEXT NOT NULL,
            metadata_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_signals_ticker ON trade_signals(ticker);
        CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON trade_signals(timestamp);
        """
    )
    conn.commit()
    return conn


def record_signal(
    run_id: str,
    ticker: str,
    signal_type: str,
    score: float = 0.0,
    confidence: int = 0,
    source: str = "portfolio_ai",
    metadata: dict[str, Any] | None = None,
    db_path: str = DEFAULT_DB,
) -> int:
    """Record a trade signal. Returns row id."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO trade_signals (run_id, ticker, signal_type, score, confidence, source, timestamp, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, ticker, signal_type, score, confidence, source, datetime.now().isoformat(), json.dumps(metadata or {}, default=str)),
        )
        conn.commit()
        return cur.lastrowid or 0
    except Exception:
        return 0
    finally:
        conn.close()


def get_signals(ticker: str | None = None, db_path: str = DEFAULT_DB) -> list[dict[str, Any]]:
    """Retrieve recorded signals, optionally filtered by ticker."""
    conn = _connect(db_path)
    try:
        if ticker:
            rows = conn.execute("SELECT * FROM trade_signals WHERE ticker = ? ORDER BY timestamp DESC", (ticker,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM trade_signals ORDER BY timestamp DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def record_portfolio_signals(run_id: str, portfolio_rows: list[dict[str, Any]], db_path: str = DEFAULT_DB) -> int:
    """Record all portfolio row signals from a run. Returns count recorded."""
    count = 0
    for row in portfolio_rows or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("display_symbol") or row.get("ticker") or "")
        signal = str(row.get("signal", "HOLD")).upper()
        if not ticker:
            continue
        try:
            score = float(row.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        rid = record_signal(run_id, ticker, signal, score=score, source="portfolio_row", db_path=db_path)
        if rid:
            count += 1
    return count

"""storage.py — SQLite schema for signal storage and backtesting.

Tables:
- portfolio_snapshots: timestamp, equity, cash, positions (JSON)
- trade_signals: ticker, signal_type, score, confidence, timestamp, source
- signal_outcomes: signal_id, horizon_days, actual_return, benchmark_return, excess
- sentiment_logs: ticker, source, text, sentiment, timestamp
- investor_events: investor, ticker, action, stance, published_at, source
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/portfolio_signals.db"


def _connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open SQLite connection, create tables if needed."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            equity_eur REAL,
            cash_eur REAL,
            positions_count INTEGER,
            positions_json TEXT,
            reconciliation_status TEXT
        );

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

        CREATE TABLE IF NOT EXISTS signal_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            horizon_days INTEGER NOT NULL,
            actual_return REAL,
            benchmark_return REAL,
            excess_return REAL,
            evaluated_at TEXT,
            FOREIGN KEY (signal_id) REFERENCES trade_signals(id)
        );

        CREATE TABLE IF NOT EXISTS sentiment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            ticker TEXT NOT NULL,
            source TEXT NOT NULL,
            text TEXT,
            sentiment TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS investor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            investor TEXT NOT NULL,
            ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            stance TEXT,
            published_at TEXT NOT NULL,
            source TEXT,
            confidence REAL,
            mode TEXT,
            raw_text TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_signals_ticker ON trade_signals(ticker);
        CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON trade_signals(timestamp);
        CREATE INDEX IF NOT EXISTS idx_outcomes_signal ON signal_outcomes(signal_id);
        CREATE INDEX IF NOT EXISTS idx_investor_ticker ON investor_events(ticker);
    """)
    conn.commit()


def store_portfolio_snapshot(run_id: str, equity: float, cash: float, positions: list, recon_status: str, db_path: str = DEFAULT_DB_PATH) -> int:
    """Store a portfolio snapshot. Returns row id."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO portfolio_snapshots (run_id, timestamp, equity_eur, cash_eur, positions_count, positions_json, reconciliation_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, datetime.now().isoformat(), equity, cash, len(positions), json.dumps(positions, default=str), recon_status),
        )
        conn.commit()
        return cur.lastrowid or 0
    except Exception as exc:
        logger.warning("storage: failed to store snapshot: %s", type(exc).__name__)
        return 0
    finally:
        conn.close()


def store_trade_signal(run_id: str, ticker: str, signal_type: str, score: float, confidence: int, source: str, metadata: dict | None = None, db_path: str = DEFAULT_DB_PATH) -> int:
    """Store a trade signal. Returns row id."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO trade_signals (run_id, ticker, signal_type, score, confidence, source, timestamp, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, ticker, signal_type, score, confidence, source, datetime.now().isoformat(), json.dumps(metadata or {}, default=str)),
        )
        conn.commit()
        return cur.lastrowid or 0
    except Exception as exc:
        logger.warning("storage: failed to store signal: %s", type(exc).__name__)
        return 0
    finally:
        conn.close()


def store_investor_event(event: dict, db_path: str = DEFAULT_DB_PATH) -> int:
    """Store an investor event. Returns row id."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO investor_events (investor, ticker, action, stance, published_at, source, confidence, mode, raw_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event.get("investor", ""), event.get("ticker", ""), event.get("action", ""), event.get("stance", ""),
             event.get("published_at", ""), event.get("source", ""), event.get("confidence", 0.5),
             event.get("mode", ""), event.get("raw_text", "")),
        )
        conn.commit()
        return cur.lastrowid or 0
    except Exception as exc:
        logger.warning("storage: failed to store investor event: %s", type(exc).__name__)
        return 0
    finally:
        conn.close()


def get_recent_signals(ticker: str, days: int = 30, db_path: str = DEFAULT_DB_PATH) -> list:
    """Get recent trade signals for a ticker."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM trade_signals WHERE ticker = ? AND timestamp > datetime('now', ?) ORDER BY timestamp DESC",
            (ticker, f"-{days} days"),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("storage: failed to get signals: %s", type(exc).__name__)
        return []
    finally:
        conn.close()

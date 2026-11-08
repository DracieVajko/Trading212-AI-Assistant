"""SQLite audit store for day-trader order intents and events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DB = "data/day_trader/audit.db"


def _connect(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS order_intents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            order_type TEXT NOT NULL,
            limit_price REAL,
            stop_price REAL,
            target_price REAL,
            fingerprint TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            broker_order_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS order_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intent_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            broker_order_id TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (intent_id) REFERENCES order_intents(id)
        );
        CREATE INDEX IF NOT EXISTS idx_intents_fingerprint ON order_intents(fingerprint);
        CREATE INDEX IF NOT EXISTS idx_intents_date ON order_intents(session_date);
        """
    )
    conn.commit()
    return conn


def record_intent(
    session_date: str,
    symbol: str,
    side: str,
    quantity: float,
    order_type: str,
    fingerprint: str,
    limit_price: float | None = None,
    stop_price: float | None = None,
    target_price: float | None = None,
    db_path: str | Path = DEFAULT_DB,
) -> int:
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()
        cur = conn.execute(
            """INSERT INTO order_intents
            (session_date, symbol, side, quantity, order_type, limit_price, stop_price,
             target_price, fingerprint, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
            (session_date, symbol, side, quantity, order_type, limit_price, stop_price,
             target_price, fingerprint, now, now),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def find_intent_by_fingerprint(fingerprint: str, db_path: str | Path = DEFAULT_DB) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM order_intents WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_intent_status(
    intent_id: int,
    status: str,
    broker_order_id: str | None = None,
    db_path: str | Path = DEFAULT_DB,
) -> None:
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()
        if broker_order_id is None:
            conn.execute(
                "UPDATE order_intents SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, intent_id),
            )
        else:
            conn.execute(
                "UPDATE order_intents SET status = ?, broker_order_id = ?, updated_at = ? WHERE id = ?",
                (status, broker_order_id, now, intent_id),
            )
        conn.commit()
    finally:
        conn.close()


def record_event(
    intent_id: int,
    event: str,
    broker_order_id: str | None = None,
    payload: Any = None,
    db_path: str | Path = DEFAULT_DB,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO order_events (intent_id, event, broker_order_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (intent_id, event, broker_order_id, json.dumps(payload, default=str) if payload is not None else None, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def list_intents(session_date: str | None = None, db_path: str | Path = DEFAULT_DB) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        if session_date:
            rows = conn.execute("SELECT * FROM order_intents WHERE session_date = ? ORDER BY id", (session_date,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM order_intents ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

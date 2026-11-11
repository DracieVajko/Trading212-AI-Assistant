"""Order ledger: one order per symbol+side per New York trading day."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from investment_engine import order_ledger


def _write_history(root, mode: str, rows: list[dict]) -> None:
    folder = root / mode
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "trades.jsonl", "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _audit_db(path, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE order_intents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date TEXT, symbol TEXT, side TEXT, quantity REAL,
            order_type TEXT, limit_price REAL, stop_price REAL, target_price REAL,
            fingerprint TEXT, status TEXT, broker_order_id TEXT,
            created_at TEXT, updated_at TEXT
        )"""
    )
    for row in rows:
        conn.execute(
            "INSERT INTO order_intents (session_date, symbol, side, quantity, order_type,"
            " fingerprint, status, broker_order_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                row["session_date"],
                row["symbol"],
                row["side"],
                row["quantity"],
                "MARKET",
                row.get("fingerprint", "fp"),
                row["status"],
                row.get("broker_order_id"),
                row["created_at"],
                row["created_at"],
            ),
        )
    conn.commit()
    conn.close()


def test_trading_day_uses_new_york_date():
    before_open = datetime.fromisoformat("2026-11-11T08:30:00-05:00")
    after_open = datetime.fromisoformat("2026-11-11T10:30:00-05:00")
    next_day = datetime.fromisoformat("2026-11-12T09:35:00-05:00")

    assert order_ledger.trading_day(before_open) == "2026-11-11"
    assert order_ledger.trading_day(after_open) == "2026-11-11"
    assert order_ledger.trading_day(next_day) == "2026-11-12"


def test_utc_timestamp_is_converted_to_new_york_day():
    # 2026-11-12T03:00Z is still 2026-11-11 22:00 in New York.
    moment = datetime.fromisoformat("2026-11-12T03:00:00+00:00")
    assert order_ledger.trading_day(moment) == "2026-11-11"


def test_history_order_blocks_a_second_order_same_day(_isolated_order_ledger):
    _write_history(
        _isolated_order_ledger,
        "demo",
        [{
            "ts": "2026-11-11T14:30:00+00:00",
            "mode": "demo",
            "symbol": "NVDA_US_EQ",
            "side": "BUY",
            "quantity": 2.0,
            "status": "PLACED",
            "order_id": "111",
        }],
    )

    found, order = order_ledger.check(
        "NVDA_US_EQ", "BUY", day="2026-11-11", db_path="missing.db"
    )

    assert found is True
    assert order["order_id"] == "111"
    assert "already buy" in order_ledger.describe(order)


def test_different_quantity_still_counts_as_the_same_order(_isolated_order_ledger):
    _write_history(
        _isolated_order_ledger,
        "demo",
        [{
            "ts": "2026-11-11T14:30:00+00:00",
            "symbol": "NVDA_US_EQ",
            "side": "BUY",
            "quantity": 2.0,
            "status": "PLACED",
        }],
    )

    found, _ = order_ledger.check(
        "NVDA_US_EQ", "BUY", day="2026-11-11", db_path="missing.db"
    )
    assert found is True


def test_other_symbol_side_or_day_is_not_blocked(_isolated_order_ledger):
    _write_history(
        _isolated_order_ledger,
        "demo",
        [{
            "ts": "2026-11-11T14:30:00+00:00",
            "symbol": "NVDA_US_EQ",
            "side": "BUY",
            "quantity": 2.0,
            "status": "PLACED",
        }],
    )
    db = "missing.db"

    assert order_ledger.check("AAPL_US_EQ", "BUY", day="2026-11-11", db_path=db)[0] is False
    assert order_ledger.check("NVDA_US_EQ", "SELL", day="2026-11-11", db_path=db)[0] is False
    assert order_ledger.check("NVDA_US_EQ", "BUY", day="2026-11-12", db_path=db)[0] is False


def test_failed_and_blocked_rows_do_not_count(_isolated_order_ledger, tmp_path):
    _write_history(
        _isolated_order_ledger,
        "demo",
        [{
            "ts": "2026-11-11T14:30:00+00:00",
            "symbol": "NVDA_US_EQ",
            "side": "BUY",
            "quantity": 2.0,
            "status": "FAILED",
        }],
    )
    db = tmp_path / "audit.db"
    _audit_db(db, [{
        "session_date": "2026-11-11",
        "symbol": "NVDA_US_EQ",
        "side": "BUY",
        "quantity": 2.0,
        "status": "BLOCKED",
        "created_at": "2026-11-11T14:30:00",
    }])

    assert order_ledger.check("NVDA_US_EQ", "BUY", day="2026-11-11", db_path=db)[0] is False


def test_audit_db_blocks_when_history_is_missing(_isolated_order_ledger, tmp_path):
    db = tmp_path / "audit.db"
    _audit_db(db, [{
        "session_date": "2026-11-11",
        "symbol": "NVDA_US_EQ",
        "side": "BUY",
        "quantity": 2.0,
        "status": "PLACED",
        "broker_order_id": "57900654522",
        "created_at": "2026-11-11T19:37:07",
    }])

    found, order = order_ledger.check("NVDA_US_EQ", "BUY", day="2026-11-11", db_path=db)

    assert found is True
    assert order["source"] == "audit_db"
    assert order["order_id"] == "57900654522"


def test_current_intent_can_be_excluded(_isolated_order_ledger, tmp_path):
    db = tmp_path / "audit.db"
    _audit_db(db, [{
        "session_date": "2026-11-11",
        "symbol": "NVDA_US_EQ",
        "side": "BUY",
        "quantity": 2.0,
        "status": "PLACED",
        "created_at": "2026-11-11T19:37:07",
    }])
    row_id = sqlite3.connect(db).execute("SELECT id FROM order_intents").fetchone()[0]

    assert order_ledger.check(
        "NVDA_US_EQ", "BUY", day="2026-11-11", db_path=db, exclude_intent_id=row_id
    )[0] is False


def test_live_history_does_not_block_demo(_isolated_order_ledger):
    _write_history(
        _isolated_order_ledger,
        "live",
        [{
            "ts": "2026-11-11T14:30:00+00:00",
            "symbol": "NVDA_US_EQ",
            "side": "BUY",
            "quantity": 2.0,
            "status": "FILLED",
        }],
    )
    db = "missing.db"

    assert order_ledger.check(
        "NVDA_US_EQ", "BUY", day="2026-11-11", modes=("demo",), db_path=db
    )[0] is False
    assert order_ledger.check(
        "NVDA_US_EQ", "BUY", day="2026-11-11", modes=("live",), db_path=db
    )[0] is True

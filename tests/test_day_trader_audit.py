from __future__ import annotations

from pathlib import Path

from investment_engine.day_trader.broker.audit import (
    find_intent_by_fingerprint,
    list_intents,
    record_event,
    record_intent,
    update_intent_status,
)


def test_audit_roundtrip(tmp_path: Path):
    db = tmp_path / "audit.db"
    iid = record_intent("2026-11-06", "AAPL_US_EQ", "BUY", 1.0, "market", "fp1", db_path=db)
    assert iid > 0
    found = find_intent_by_fingerprint("fp1", db_path=db)
    assert found is not None and found["status"] == "PENDING"
    update_intent_status(iid, "PLACED", broker_order_id="123", db_path=db)
    found = find_intent_by_fingerprint("fp1", db_path=db)
    assert found["status"] == "PLACED" and found["broker_order_id"] == "123"
    record_event(iid, "placed", broker_order_id="123", payload={"ok": True}, db_path=db)
    intents = list_intents("2026-11-06", db_path=db)
    assert len(intents) == 1
    # duplicate fingerprint rejected
    try:
        record_intent("2026-11-06", "AAPL_US_EQ", "BUY", 1.0, "market", "fp1", db_path=db)
        dup = False
    except Exception:
        dup = True
    assert dup

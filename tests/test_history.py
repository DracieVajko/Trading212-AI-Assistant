from __future__ import annotations

from pathlib import Path

from investment_engine import history


def test_history_trade_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_ROOT", tmp_path)
    db = tmp_path / "history.db"
    rid = history.record_trade(
        "AAPL", "BUY", 1.5, price=200.0, value=300.0,
        order_id="123", status="FILLED", reason="test", mode="demo",
        db_path=db,
    )
    assert rid > 0
    trades = history.query_trades(mode="demo", db_path=db)
    assert len(trades) == 1
    assert trades[0]["symbol"] == "AAPL"
    assert trades[0]["mode"] == "demo"
    assert (tmp_path / "demo" / "trades.jsonl").is_file()


def test_history_mode_separation(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_ROOT", tmp_path)
    db = tmp_path / "history.db"
    history.record_trade("AAPL", "BUY", 1, mode="live", db_path=db)
    history.record_trade("AAPL", "SELL", 1, mode="demo", db_path=db)
    assert len(history.query_trades(mode="live", db_path=db)) == 1
    assert len(history.query_trades(mode="demo", db_path=db)) == 1
    assert len(history.query_trades(db_path=db)) == 2


def test_history_decision_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_ROOT", tmp_path)
    db = tmp_path / "history.db"
    did = history.record_decision(
        "TSLA", "BUY", "breakout confirmed", confidence=0.72,
        source="test", run_id="r1", mode="demo", db_path=db,
    )
    assert did > 0
    decisions = history.query_decisions(symbol="TSLA", db_path=db)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "BUY"
    assert decisions[0]["confidence"] == 0.72

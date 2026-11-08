from __future__ import annotations

from pathlib import Path

from investment_engine.signals.signal_recorder import get_signals, record_portfolio_signals, record_signal


def test_record_and_retrieve(tmp_path: Path):
    db = tmp_path / "test.db"
    rid = record_signal("run1", "AAPL", "BUY", score=80.0, confidence=80, db_path=str(db))
    assert rid > 0
    sigs = get_signals("AAPL", db_path=str(db))
    assert len(sigs) == 1
    assert sigs[0]["signal_type"] == "BUY"
    assert sigs[0]["ticker"] == "AAPL"


def test_record_portfolio_signals(tmp_path: Path):
    db = tmp_path / "test.db"
    rows = [
        {"display_symbol": "AAPL", "signal": "BUY", "confidence": 80},
        {"display_symbol": "MSFT", "signal": "HOLD", "confidence": 50},
    ]
    count = record_portfolio_signals("run1", rows, db_path=str(db))
    assert count == 2
    all_sigs = get_signals(db_path=str(db))
    assert len(all_sigs) == 2

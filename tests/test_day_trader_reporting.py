from __future__ import annotations

from pathlib import Path

from investment_engine.day_trader.reporting import write_day_trader_report


def test_report_renders_empty_watchlist(tmp_path: Path):
    payload = {"status": "OK", "watchlist": {"hits": []}, "errors": []}
    out = write_day_trader_report(tmp_path, payload, tmp_path / "reports")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "no hits" in text.lower()

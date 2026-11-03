"""Focused tests for storage, risk profiles, and cash-flow normalization."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from investment_engine.accounting import cashflows
from investment_engine.risk import profiles
from investment_engine import storage
from investment_engine.discovery import discovery
from investment_engine.schemas import ai_recommendations
import pandas as pd


def test_storage_roundtrip(tmp_path):
    db = tmp_path / "signals.db"
    snap_id = storage.store_portfolio_snapshot(
        "run-1", equity=1000.0, cash=100.0, positions=[{"ticker": "AAPL"}],
        recon_status="PASS", db_path=str(db),
    )
    sig_id = storage.store_trade_signal(
        "run-1", "AAPL", "BUY", 0.8, 70, "test", {"note": "x"}, db_path=str(db),
    )
    event_id = storage.store_investor_event(
        {"investor": "buffett", "ticker": "AAPL", "action": "buy",
         "stance": "bullish", "published_at": "2026-01-01", "source": "13F"},
        db_path=str(db),
    )
    assert snap_id > 0 and sig_id > 0 and event_id > 0

    rows = storage.get_recent_signals("AAPL", db_path=str(db))
    assert len(rows) == 1
    assert rows[0]["signal_type"] == "BUY"

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM investor_events").fetchone()[0] == 1


def test_storage_invalid_path_returns_zero(tmp_path):
    db = tmp_path / "nested" / "signals.db"
    assert storage.store_trade_signal(
        "r", "AAPL", "HOLD", 0.5, 50, "test", db_path=str(db)
    ) > 0


def test_profiles_presets_and_unknown():
    assert "long_term" in profiles.available_profiles()
    merged, block = profiles.apply_profile({"risk": {"x": 1}}, "Long-Term")
    assert merged["risk"]["x"] == 1
    assert block["name"] == "long_term"
    assert profiles.normalize_name("Long-Term Profile") == "long_term_profile"

    with pytest.raises(profiles.UnknownProfile):
        profiles.apply_profile({}, "does_not_exist")

    custom, custom_block = profiles.apply_profile({}, "custom")
    assert custom_block["name"] == profiles.CUSTOM
    assert custom["profile"]["name"] == profiles.CUSTOM


def test_cashflow_conversion_and_summary():
    item = cashflows.normalize_cashflow_item(
        {"type": "deposit", "date": "2026-01-01", "amount": 100.0, "currency": "EUR"},
        source="test",
    )
    assert item["type"] == cashflows.DEPOSIT
    assert item["amount_eur"] == 100.0
    assert item["verified"] is True

    gbx = cashflows.convert_to_eur(
        1000.0, "GBX", date(2026, 1, 1), rate_fetcher=lambda ccy, day: (1.0, "test"),
    )
    assert gbx[0] == 10.0 and gbx[3] == "ok"

    usd = cashflows.convert_to_eur(
        100.0, "USD", date(2026, 1, 1), rate_fetcher=lambda ccy, day: (0.9, "test"),
    )
    assert usd[0] == 90.0 and usd[3] == "ok"

    summary = cashflows.summarize_cashflows([
        {"type": cashflows.DEPOSIT, "amount_eur": 100.0},
        {"type": cashflows.WITHDRAW, "amount_eur": -25.0},
        {"type": cashflows.FEE, "amount_eur": -2.0},
        {"type": cashflows.UNKNOWN, "amount_eur": None},
    ])
    assert summary["total_deposits_eur"] == 100.0
    assert summary["total_withdrawals_eur"] == 25.0
    assert summary["fees_eur"] == 2.0
    assert summary["net_deposits_eur"] == 75.0


def test_ai_recommendations_parse_and_reject():
    valid = '{"portfolio_actions": [], "trades": [], "position_updates": [], "cash_deployment": null}'
    parsed = ai_recommendations.parse_ai_recommendations(valid)
    assert parsed["portfolio_actions"] == []
    assert "error" not in parsed

    fenced = f"```json\n{valid}\n```"
    assert ai_recommendations.parse_ai_recommendations(fenced)["trades"] == []

    assert "error" in ai_recommendations.parse_ai_recommendations("")
    assert "error" in ai_recommendations.parse_ai_recommendations("{not json")
    assert "error" in ai_recommendations.parse_ai_recommendations('{"unexpected": 1}')


def test_discovery_empty_universe_and_insufficient_data():
    empty = discovery.run_discovery([], pd.DataFrame())
    assert empty.empty

    result = discovery.score_candidate("AAPL", pd.DataFrame(), {}, None, None)
    assert result["status"] == "REJECT"
    assert "insufficient_data" in result["reasons"]

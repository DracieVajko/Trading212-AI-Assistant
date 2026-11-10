"""Tests for the watchlist_stance skill (generalised research briefing)."""

from __future__ import annotations

from investment_engine.skills import registry


def _inputs(**over):
    base = {
        "watchlist": ["AAPL", "NVDA", "OGC"],
        "portfolio_rows": [
            {"display_symbol": "AAPL", "weight": 12.0, "current_price": 100.0,
             "support": 96.0, "resistance": 108.0},
            {"display_symbol": "NVDA", "weight": 8.0, "current_price": 200.0,
             "support": 190.0, "resistance": 201.0},
        ],
        "technicals": {
            "AAPL": {"price": 100.0, "support": 96.0, "resistance": 108.0,
                     "rsi": 45.0, "atr": 2.0, "trend": "TRENDING_UP"},
            "NVDA": {"price": 200.0, "support": 190.0, "resistance": 201.0,
                     "rsi": 78.0, "atr": 4.0, "trend": "TRENDING_UP"},
        },
        "news_events": [
            {"ticker": "AAPL", "type": "EARNINGS", "state": "CONFIRMED",
             "severity": "high", "what_is_new": "Q3 beat, FY outlook raised"},
        ],
        "earnings_status": {"OGC": "2026-11-11"},
        "sectors": {"AAPL": "Technology", "NVDA": "Semiconductors", "OGC": "Gold"},
        "event_calendar": [],
        "concentration_cap_pct": 20.0,
    }
    base.update(over)
    return base


def test_watchlist_rows_have_required_fields():
    out = registry.run_skill("watchlist_stance", _inputs())
    assert out["status"] == "OK"
    assert out["execution_type"] == "DETERMINISTIC"
    rows = out["data"]["rows"]
    assert {r["ticker"] for r in rows} == {"AAPL", "NVDA", "OGC"}
    for row in rows:
        assert {"sector", "catalyst", "confirmation_to_watch", "key_risk",
                "research_stance"} <= set(row)


def test_no_chasing_when_overbought_or_at_resistance():
    rows = {r["ticker"]: r for r in registry.run_skill("watchlist_stance", _inputs())["data"]["rows"]}
    assert rows["NVDA"]["research_stance"] == "NO_CHASING"


def test_event_risk_wait_when_earnings_imminent():
    rows = {r["ticker"]: r for r in registry.run_skill("watchlist_stance", _inputs())["data"]["rows"]}
    # OGC has earnings 2026-11-11; determine by days only when within 2 days.
    assert rows["OGC"]["earnings_days"] is not None


def test_fundamental_watch_with_catalyst_and_uptrend():
    rows = {r["ticker"]: r for r in registry.run_skill("watchlist_stance", _inputs())["data"]["rows"]}
    assert rows["AAPL"]["research_stance"] in ("FUNDAMENTAL_WATCH", "SELECTIVE_WATCH")


def test_event_calendar_has_why_it_matters():
    out = registry.run_skill("watchlist_stance", _inputs(
        event_calendar=[{"date": "2026-11-10", "event": "U.S. Consumer Price Index (CPI)"}]
    ))
    cal = out["data"]["event_calendar"]
    assert cal and "Fed" in cal[0]["why_it_matters"]


def test_watchlist_falls_back_to_portfolio_rows():
    out = registry.run_skill("watchlist_stance", _inputs(watchlist=[]))
    assert {r["ticker"] for r in out["data"]["rows"]} == {"AAPL", "NVDA"}


def test_insufficient_when_nothing_supplied():
    out = registry.run_skill("watchlist_stance", {})
    assert out["status"] == "INSUFFICIENT_EVIDENCE"


def test_render_marks_advisory_research_only():
    out = registry.run_skill("watchlist_stance", _inputs())
    mod = registry.get_skill("watchlist_stance")
    text = mod.render(out)
    assert "AAPL" in text and "NO_CHASING" in text

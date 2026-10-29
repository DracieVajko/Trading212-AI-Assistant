"""Tests for investor_intelligence.py (offline, no network, no real data)."""
from __future__ import annotations

import pytest

from investment_engine.investor_intelligence import (
    DEFAULT_CONFIG,
    InvestorEvent,
    InvestorSignal,
    _is_enabled,
    _get_mode,
    _load_config,
    parse_cramer_recommendation,
    compute_investor_signals,
    get_investor_summary,
    track_performance,
    MODE_FOLLOW,
    MODE_INVERSE,
    MODE_CONTRARIAN,
    MODE_IGNORE,
    MODE_PAPER_ONLY,
)


def test_default_config_disabled():
    assert DEFAULT_CONFIG["enabled"] is False


def test_load_config_empty():
    cfg = _load_config({})
    assert cfg["enabled"] is False
    assert cfg["mode"] == "inverse"


def test_load_config_override():
    cfg = _load_config({"investor_intelligence": {"enabled": True, "mode": "follow"}})
    assert cfg["enabled"] is True
    assert cfg["mode"] == "follow"


def test_is_enabled():
    assert _is_enabled({}) is False
    assert _is_enabled({"investor_intelligence": {"enabled": True}}) is True


def test_get_mode_default():
    assert _get_mode({}) == "inverse"


def test_get_mode_override():
    rules = {"investor_intelligence": {"mode": "follow", "modes": {"cramer": "inverse"}}}
    assert _get_mode(rules, "cramer") == "inverse"
    assert _get_mode(rules, "buffett") == "follow"


def test_parse_cramer_buy():
    text = "I recommend buying AAPL and MSFT. NVDA is a hold."
    events = parse_cramer_recommendation(text)
    assert len(events) >= 2
    tickers = {e.ticker for e in events}
    assert "AAPL" in tickers
    assert "MSFT" in tickers
    for e in events:
        if e.ticker in ("AAPL", "MSFT"):
            assert e.action == "buy"
            assert e.stance == "bullish"


def test_parse_cramer_sell():
    text = "Sell TSLA and avoid BYND. Stay away from AMC."
    events = parse_cramer_recommendation(text)
    tickers = {e.ticker for e in events}
    assert "TSLA" in tickers
    for e in events:
        if e.ticker == "TSLA":
            assert e.action == "sell"
            assert e.stance == "bearish"


def test_parse_cramer_dedup():
    text = "Buy AAPL. I am buying AAPL again."
    events = parse_cramer_recommendation(text)
    aapl_events = [e for e in events if e.ticker == "AAPL"]
    assert len(aapl_events) == 1


def test_parse_cramer_empty():
    assert parse_cramer_recommendation("") == []
    assert parse_cramer_recommendation(None) == []


def test_compute_signals_disabled():
    rules = {}  # disabled by default
    events = [InvestorEvent(investor="cramer", ticker="AAPL", stance="bullish", action="buy", published_at="2026-10-29T00:00:00", source="test", confidence=0.9)]
    signals = compute_investor_signals(events, rules)
    assert signals == []


def test_compute_signals_inverse():
    rules = {"investor_intelligence": {"enabled": True, "mode": "inverse", "weight": 0.5, "cap": 1.0, "min_confidence": 0.5}}
    events = [InvestorEvent(investor="cramer", ticker="AAPL", stance="bullish", action="buy", published_at="2026-10-29T00:00:00", source="test", confidence=0.9)]
    signals = compute_investor_signals(events, rules)
    assert len(signals) == 1
    assert signals[0].ticker == "AAPL"
    assert signals[0].mode == "inverse"
    assert signals[0].adjustment < 0  # inverse of buy = negative
    assert "INVERSE" in signals[0].reason


def test_compute_signals_follow():
    rules = {"investor_intelligence": {"enabled": True, "mode": "follow", "weight": 0.5, "cap": 1.0, "min_confidence": 0.5}}
    events = [InvestorEvent(investor="cramer", ticker="AAPL", stance="bullish", action="buy", published_at="2026-10-29T00:00:00", source="test", confidence=0.9)]
    signals = compute_investor_signals(events, rules)
    assert len(signals) == 1
    assert signals[0].adjustment > 0  # follow buy = positive


def test_compute_signals_low_confidence():
    rules = {"investor_intelligence": {"enabled": True, "mode": "inverse", "weight": 0.5, "cap": 1.0, "min_confidence": 0.9}}
    events = [InvestorEvent(investor="cramer", ticker="AAPL", stance="bullish", action="buy", published_at="2026-10-29T00:00:00", source="test", confidence=0.5)]
    signals = compute_investor_signals(events, rules)
    assert signals == []  # low confidence filtered out


def test_compute_signals_paper_only():
    rules = {"investor_intelligence": {"enabled": True, "mode": "paper_only", "weight": 0.5, "cap": 1.0, "min_confidence": 0.5}}
    events = [InvestorEvent(investor="cramer", ticker="AAPL", stance="bullish", action="buy", published_at="2026-10-29T00:00:00", source="test", confidence=0.9)]
    signals = compute_investor_signals(events, rules)
    assert len(signals) == 1
    assert signals[0].adjustment == 0.0  # paper only: no score impact


def test_get_investor_summary_empty():
    assert get_investor_summary([]) == "No investor signals (disabled or no events)."


def test_get_investor_summary_with_signals():
    sig = InvestorSignal(ticker="AAPL", investor="cramer", mode="inverse", adjustment=-0.25, confidence=0.9, reason="test")
    summary = get_investor_summary([sig])
    assert "AAPL" in summary
    assert "inverse" in summary


def test_track_performance():
    sig = InvestorSignal(ticker="AAPL", investor="cramer", mode="inverse", adjustment=-0.25, confidence=0.9, reason="test")
    result = track_performance([sig], {})
    assert "AAPL" in result
    assert result["AAPL"]["tracked"] is True


def test_cap_limit():
    rules = {"investor_intelligence": {"enabled": True, "mode": "inverse", "weight": 10.0, "cap": 1.0, "min_confidence": 0.5}}
    events = [InvestorEvent(investor="cramer", ticker="AAPL", stance="bullish", action="buy", published_at="2026-10-29T00:00:00", source="test", confidence=0.9)]
    signals = compute_investor_signals(events, rules)
    assert len(signals) == 1
    assert abs(signals[0].adjustment) <= 1.0  # capped


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

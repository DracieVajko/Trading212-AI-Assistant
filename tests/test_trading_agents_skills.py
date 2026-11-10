"""Tests for the TradingAgents-style skills: technical, sentiment, debate, trader."""

from __future__ import annotations

from investment_engine.skills import registry


def _tech_outputs():
    return registry.run_skill("technical_analyst", {
        "portfolio_rows": [
            {"display_symbol": "AAPL", "weight": 12.5, "current_price": 100.0,
             "support": 96.0, "resistance": 108.0},
        ],
        "technicals": {"AAPL": {"RSI_14": 25.0, "MACD_HIST": 0.5, "ADX": 30.0, "ATR_14": 2.0}},
    })


def _sent_outputs():
    return registry.run_skill("sentiment_analyst", {
        "decision_items": [
            {"title": "Apple beats estimates, shares surge", "ticker_tags": ["AAPL"]},
            {"title": "Apple upgrade to outperform", "ticker_tags": ["AAPL"]},
            {"title": "Tesla misses, stock plunges", "ticker_tags": ["TSLA"]},
        ],
        "social_items": [{"text": "AAPL bullish rally", "ticker": "AAPL"}],
    })


def test_technical_classifies_oversold_and_trend():
    out = _tech_outputs()
    assert out["status"] == "OK"
    assert out["execution_type"] == "DETERMINISTIC"
    read = out["data"]["reads"][0]
    assert read["ticker"] == "AAPL"
    assert read["momentum"] == "OVERSOLD"
    assert read["trend"].endswith("UP")
    assert read["level_proximity"] == "MID_RANGE"
    assert read["rsi"] == 25.0


def test_technical_reports_missing_indicators_not_invented():
    out = registry.run_skill("technical_analyst", {
        "portfolio_rows": [{"display_symbol": "XYZ", "weight": 1.0}],
        "technicals": {},
    })
    assert out["status"] == "INSUFFICIENT_EVIDENCE"


def test_sentiment_counts_stance():
    out = _sent_outputs()
    stances = {r["ticker"]: r["stance"] for r in out["data"]["reads"]}
    assert stances["AAPL"] == "BULLISH"
    assert stances["TSLA"] == "BEARISH"


def test_debate_builds_bull_and_bear_verdicts():
    out = registry.run_skill("researcher_debate", {
        "analyst_outputs": {"technical_analyst": _tech_outputs(),
                            "sentiment_analyst": _sent_outputs()},
    })
    verdicts = {d["ticker"]: d["verdict"] for d in out["data"]["debates"]}
    assert verdicts["AAPL"] == "BULL"
    assert verdicts["TSLA"] == "BEAR"


def test_trader_derives_levels_and_size():
    tech = _tech_outputs()
    sent = _sent_outputs()
    deb = registry.run_skill("researcher_debate", {
        "analyst_outputs": {"technical_analyst": tech, "sentiment_analyst": sent},
    })
    out = registry.run_skill("trader_agent", {
        "debates": deb["data"]["debates"],
        "technicals": {"AAPL": {"price": 100.0, "atr": 2.0, "support": 96.0, "resistance": 108.0}},
        "risk_budget": 50.0,
    })
    proposal = next(p for p in out["data"]["proposals"] if p["ticker"] == "AAPL")
    assert proposal["action"] == "BUY"
    assert proposal["entry"] == 100.0
    assert proposal["stop"] == 94.0          # support 96 - ATR 2
    assert proposal["target"] == 108.0       # resistance
    assert proposal["quantity"] == 8.3333    # 50 / 6 risk per share
    assert proposal["advisory_only"] is True


def test_trader_holds_without_price():
    out = registry.run_skill("trader_agent", {
        "debates": [{"ticker": "AAPL", "verdict": "BULL", "confidence": 0.5}],
        "technicals": {},
        "risk_budget": 50.0,
    })
    assert out["data"]["proposals"][0]["action"] == "HOLD"


def test_all_new_skills_are_registered():
    for name in ("technical_analyst", "sentiment_analyst", "researcher_debate", "trader_agent"):
        assert name in registry.SKILL_VERSIONS
        assert registry.load_prompt(name)          # prompt exists
        assert registry.load_manifest(name)["name"] == name


def test_skills_never_raise_on_garbage_inputs():
    for name in ("technical_analyst", "sentiment_analyst", "researcher_debate", "trader_agent"):
        out = registry.run_skill(name, {"portfolio_rows": "nonsense", "decision_items": 5})
        assert isinstance(out, dict) and "status" in out

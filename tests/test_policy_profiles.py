"""Policy profiles: user-selectable presets that gate sleeves and sizing.

Profiles may block or resize a candidate; they must never create a signal,
never bypass reconciliation, and never bypass the earnings blackout.
"""

from __future__ import annotations

import json

import pytest

from investment_engine.risk import order_plan as op
from investment_engine.risk import policy as pol
from investment_engine.risk import profiles


def _policy(**over):
    base = {"policy_version": "v1-preliminary", "risk_per_trade_pct": 2.0,
            "adverse_move_assumption": 0.25,
            "concentration": {"default_max_position_pct": 20.0},
            "cash": {"mandatory_floor_pct": 0.0, "zero_cash_blocks_buys": True},
            "earnings_blackout": {"before_bdays": 5, "after_bdays": 2},
            "discovery": {"enabled": True},
            "stops": {"scope": "tactical-only"}, "core_trims": True,
            "trims": {"trim_fraction_pct": 50.0}}
    base.update(over)
    return base


def _row(display="AAPL", weight=5.0, mapping="VERIFIED", pnl_pct=3.0):
    return {"display_symbol": display, "ticker": display, "signal": "HOLD",
            "weight": weight, "pnl_pct": pnl_pct,
            "external_mapping_status": mapping,
            "quantity": 10.0, "market_value": 500.0}


def _build(profile_name, *, decisions, sleeves, rows=None, recon="PASS",
           earnings=None, cash=5000.0, equity=10000.0, policy_extra=None):
    merged, _block = profiles.apply_profile(_policy(**(policy_extra or {})), profile_name)
    return op.build_plans(
        committee_decisions=decisions,
        portfolio_rows=rows if rows is not None else [_row()],
        recon_status=recon, free_cash=cash, total_equity=equity,
        earnings_status=earnings or {}, report_day="2026-09-24",
        news_events=[{"ticker": "AAPL"}], regime="NEUTRAL",
        risk_posture="NORMAL", policy=merged, sleeves=sleeves)


# --- preset table -------------------------------------------------------------

def test_five_presets_are_documented():
    assert profiles.available_profiles() == (
        "passive", "long_term", "medium_term", "short_term", "aggressive")


def test_custom_is_the_default_and_preserves_values():
    policy = _policy()
    merged, block = profiles.apply_profile(policy, None)
    assert merged["profile"] == block
    assert {k: v for k, v in merged.items() if k != "profile"} == policy
    assert block["name"] == "custom"
    assert block["allow_sells"] is True
    assert block["allowed_buy_sleeves"] == []


def test_profile_overrides_are_effective_and_reported():
    merged, block = profiles.apply_profile(_policy(), "passive")
    assert merged["risk_per_trade_pct"] == pytest.approx(1.0)
    assert merged["cash"]["mandatory_floor_pct"] == pytest.approx(5.0)
    assert merged["concentration"]["default_max_position_pct"] == pytest.approx(25.0)
    assert "cash.mandatory_floor_pct" in block["applied_overrides"]
    assert block["effective"]["max_position_pct"] == pytest.approx(25.0)
    assert block["allow_sells"] is False


def test_profile_leaves_unrelated_policy_sections_alone():
    policy = _policy()
    merged, _ = profiles.apply_profile(policy, "aggressive")
    assert merged["earnings_blackout"] == policy["earnings_blackout"]
    assert merged["discovery"] == policy["discovery"]
    assert merged["policy_version"] == "v1-preliminary"


def test_unknown_profile_is_rejected_loudly():
    assert profiles.normalize_name("Long-Term") == "long_term"
    with pytest.raises(profiles.UnknownProfile):
        profiles.apply_profile(_policy(), "yolo")


def test_load_policy_applies_profile_and_reports_it(tmp_path):
    path = tmp_path / "investment_policy.json"
    path.write_text(json.dumps(_policy(policy_profile="short_term")), encoding="utf-8")
    loaded = pol.load_policy(str(path))
    assert loaded["status"] == "OK"
    assert loaded["profile"]["name"] == "short_term"
    assert loaded["policy"]["concentration"]["default_max_position_pct"] == pytest.approx(8.0)
    assert loaded["policy"]["profile"] == loaded["profile"]


def test_load_policy_unknown_profile_is_invalid(tmp_path):
    path = tmp_path / "investment_policy.json"
    path.write_text(json.dumps(_policy(policy_profile="yolo")), encoding="utf-8")
    loaded = pol.load_policy(str(path))
    assert loaded["status"] == "INVALID"
    assert any("unknown policy_profile" in p for p in loaded["problems"])
    assert "passive" in " ".join(loaded["problems"])


# --- sleeve gating ------------------------------------------------------------

def test_passive_blocks_thematic_buy():
    bundle = _build("passive", decisions=[{"ticker": "AAPL", "action": "BUY", "basis": []}],
                    sleeves={"AAPL": "thematic"})
    assert bundle["plans"] == []
    assert bundle["blocked"][0]["source"] == "profile"
    assert "adds only to" in bundle["blocked"][0]["reason"]
    assert bundle["profile_effects"]["buy_candidates_blocked"] == 1


def test_passive_allows_long_term_buy():
    bundle = _build("passive", decisions=[{"ticker": "AAPL", "action": "BUY", "basis": []}],
                    sleeves={"AAPL": "long_term"})
    assert len(bundle["plans"]) == 1
    assert bundle["plans"][0]["direction"] == "BUY"


def test_passive_blocks_every_sell():
    bundle = _build("passive", decisions=[{"ticker": "AAPL", "action": "TRIM", "basis": []}],
                    sleeves={"AAPL": "long_term"})
    assert bundle["plans"] == []
    assert "manual only" in bundle["blocked"][0]["reason"]
    assert bundle["profile_effects"]["sell_candidates_blocked"] == 1


def test_long_term_blocks_tactical_add():
    bundle = _build("long_term", decisions=[{"ticker": "AAPL", "action": "BUY", "basis": []}],
                    sleeves={"AAPL": "tactical"})
    assert bundle["plans"] == []


def test_short_term_blocks_long_term_add():
    bundle = _build("short_term", decisions=[{"ticker": "AAPL", "action": "BUY", "basis": []}],
                    sleeves={"AAPL": "long_term"})
    assert bundle["plans"] == []


def test_short_term_sells_tactical_but_never_the_core():
    tactical = _build("short_term",
                      decisions=[{"ticker": "AAPL", "action": "TRIM", "basis": []}],
                      sleeves={"AAPL": "tactical"})
    assert len(tactical["plans"]) == 1
    core = _build("short_term",
                  decisions=[{"ticker": "AAPL", "action": "TRIM", "basis": []}],
                  sleeves={"AAPL": "long_term"})
    assert core["plans"] == []
    assert "does not sell sleeve=long_term" in core["blocked"][0]["reason"]


def test_aggressive_allows_crypto_add():
    bundle = _build("aggressive", decisions=[{"ticker": "AAPL", "action": "BUY", "basis": []}],
                    sleeves={"AAPL": "crypto"})
    assert len(bundle["plans"]) == 1


def test_custom_policy_without_profile_key_is_unrestricted():
    bundle = op.build_plans(
        committee_decisions=[{"ticker": "AAPL", "action": "BUY", "basis": []}],
        portfolio_rows=[_row()], recon_status="PASS", free_cash=5000.0,
        total_equity=10000.0, earnings_status={}, report_day="2026-09-24",
        news_events=[{"ticker": "AAPL"}], regime="NEUTRAL", risk_posture="NORMAL",
        policy=_policy(), sleeves={"AAPL": "tactical"})
    assert len(bundle["plans"]) == 1
    assert bundle["policy_profile"] == {}


# --- sizing -------------------------------------------------------------------

def test_aggressive_sizes_larger_than_passive():
    decisions = [{"ticker": "AAPL", "action": "BUY", "basis": []}]
    passive = _build("passive", decisions=decisions, sleeves={"AAPL": "long_term"})
    aggressive = _build("aggressive", decisions=decisions, sleeves={"AAPL": "long_term"})
    p_eur = passive["plans"][0]["indicative_notional_eur"]
    a_eur = aggressive["plans"][0]["indicative_notional_eur"]
    # passive: 1% risk / 30% adverse move = 333.33 EUR risk cap
    assert p_eur == pytest.approx(333.33, abs=0.01)
    # aggressive: 3% risk / 25% adverse move = 1200.00 EUR risk cap
    assert a_eur == pytest.approx(1200.00, abs=0.01)
    assert a_eur > p_eur


def test_passive_cash_floor_reduces_the_buy_pool():
    decisions = [{"ticker": "AAPL", "action": "BUY", "basis": []}]
    bundle = _build("passive", decisions=decisions, sleeves={"AAPL": "long_term"},
                    cash=1000.0, equity=10000.0)
    plan = bundle["plans"][0]
    assert plan["funding"]["reserve_eur"] == pytest.approx(500.0)
    assert plan["funding"]["available_pool_eur"] == pytest.approx(500.0)


# --- safety rails -------------------------------------------------------------

def test_profiles_never_bypass_reconciliation():
    bundle = _build("aggressive", decisions=[{"ticker": "AAPL", "action": "BUY", "basis": []}],
                    sleeves={"AAPL": "long_term"}, recon="FAIL")
    assert bundle["plans"] == []
    assert "reconciliation" in bundle["blocked"][0]["reason"]


def test_profiles_never_bypass_earnings_blackout():
    bundle = _build("aggressive", decisions=[{"ticker": "AAPL", "action": "BUY", "basis": []}],
                    sleeves={"AAPL": "long_term"},
                    earnings={"AAPL": ("2026-09-24", "confirmed")})
    assert bundle["plans"] == []
    assert "blackout" in bundle["blocked"][0]["reason"]


def test_profiles_never_create_signals():
    bundle = _build("aggressive", decisions=[], sleeves={})
    assert bundle["plans"] == []
    assert bundle["evaluation_status"] == "NO_CANDIDATES_PRODUCED"


# --- reporting ----------------------------------------------------------------

def test_bundle_and_render_report_the_active_profile():
    bundle = _build("passive", decisions=[], sleeves={})
    assert bundle["policy_profile"]["name"] == "passive"
    text = op.render(bundle)
    assert "Policy profile: Passive" in text
    assert "exits: manual only" in text


def test_describe_line_is_deterministic():
    _merged, block = profiles.apply_profile(_policy(), "short_term")
    first = profiles.describe_line(block)
    second = profiles.describe_line(block)
    assert first == second
    assert "Short-term" in first and "risk 1.0%/trade" in first


def test_intelligence_brief_shows_the_profile_line():
    from investment_engine.reporting.documents import build_intelligence_brief

    _merged, block = profiles.apply_profile(_policy(), "long_term")
    result = {
        "run_id": "t-profile", "brief_generated_at": "2026-10-15T12:00:00+00:00",
        "portfolio_rows": [], "reconciliation": {"status": "PASS"},
        "t212_data": {"account_summary": {"total_equity": 1000.0},
                      "cash": {"free": 10.0},
                      "timestamp": "2026-10-15T11:00:00+00:00"},
        "decision_news": [], "earnings_7d": {}, "ideas": [],
        "research_corpus": {"counts": {"total": 0, "decision": 0}},
        "providers_per_stage": {},
        "investment_policy": {"status": "OK", "profile": block},
    }
    brief = build_intelligence_brief(result)
    assert "Policy profile: Long-term" in brief


def test_human_brief_shows_the_profile_line():
    from investment_engine.reporting.documents import render_brief

    _merged, block = profiles.apply_profile(_policy(), "aggressive")
    brief = render_brief(
        generated_at="2026-10-15 12:00 CEST", regime_result=None,
        recon={"status": "PASS"}, rows=[], monitoring_items=[],
        earnings_7d={}, decision_news=[], ideas=[], cash_line="",
        order_plans={"plans": [], "blocked": [], "policy_profile": block},
        summary="")
    assert "Policy profile: Aggressive" in brief

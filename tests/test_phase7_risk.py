"""Phase 7 risk: policy, eligibility gates, sizing, advisory plans, no-execution.

Offline only. No live API.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _row(display="AAPL", signal="BUY", weight=5.0, mapping="VERIFIED"):
    return {"display_symbol": display, "ticker": display, "signal": signal,
            "weight": weight, "pnl_pct": 3.0, "external_mapping_status": mapping,
            "quantity": 10.0, "market_value": 500.0}


def _policy(**over):
    base = {"policy_version": "v1-preliminary", "risk_per_trade_pct": 2.0,
            "adverse_move_assumption": 0.25,
            "concentration": {"default_max_position_pct": 20.0},
            "cash": {"mandatory_floor_pct": 0.0, "zero_cash_blocks_buys": True},
            "earnings_blackout": {"before_bdays": 5, "after_bdays": 2},
            "stops": {"scope": "tactical-only"}, "core_trims": True}
    base.update(over)
    return base


def test_policy_template_loads_and_missing_is_not_set(tmp_path):
    from investment_engine.risk import policy as pol

    ok = pol.load_policy(str(ROOT / "investment_policy.example.json"))
    assert ok["status"] == "OK" and ok["version"] == "v1-preliminary"
    missing = pol.load_policy(str(tmp_path / "nope.json"))
    assert missing["status"] == "NOT SET"
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert pol.load_policy(str(bad))["status"] == "INVALID"
    assert pol.is_deferred("REQUIRES_USER_VALUE")
    assert not pol.is_deferred(2.0)


def test_eligibility_matrix():
    from investment_engine.risk import eligibility as e

    assert not e.gate_recon("FAIL")["pass"] and e.gate_recon("PASS")["pass"]
    assert not e.gate_cash("BUY", 0.0)["pass"] and e.gate_cash("BUY", 1.0)["pass"]
    assert e.gate_cash("TRIM", 0.0)["pass"]
    assert not e.gate_concentration(25.0, 20.0)["pass"] and e.gate_concentration(5.0, 20.0)["pass"]
    earn = {"AAPL": ("2026-09-24", "confirmed")}
    assert not e.gate_blackout("AAPL", earn, "2026-09-24")["pass"]  # T+0 inside
    assert not e.gate_blackout("AAPL", earn, "2026-09-17")["pass"]  # 5bd before: inside
    assert e.gate_blackout("AAPL", earn, "2026-09-16")["pass"]  # 6bd before: clear
    assert e.gate_blackout("AAPL", earn, "2026-09-10")["pass"]  # well before
    assert not e.gate_blackout("AAPL", earn, "2026-09-28")["pass"]  # 2bd after: inside
    assert e.gate_blackout("AAPL", earn, "2026-09-29")["pass"]  # 3bd after: clear
    assert e.gate_blackout("MSFT", earn, "2026-09-24")["pass"]  # no date
    assert not e.gate_mapping("UNRESOLVED", True)["pass"]
    assert e.gate_mapping("UNRESOLVED", False)["pass"] and e.gate_mapping("VERIFIED", True)["pass"]
    ev = [{"ticker": "AAPL"}]
    assert e.gate_evidence("BUY", "AAPL", ev, "NEUTRAL", "NORMAL")["pass"]
    assert e.gate_evidence("BUY", "AAPL", [], "MUST_BUY", "NORMAL")["pass"]
    assert e.gate_evidence("BUY", "AAPL", [], "POTENTIAL_ACCUMULATION_ZONE", "CAUTIOUS")["pass"]
    assert not e.gate_evidence("BUY", "AAPL", [], "NEUTRAL", "NORMAL")["pass"]
    assert not e.gate_evidence("BUY", "AAPL", [{"ticker": "AAPL", "state": "SOCIAL"}],
                               "NEUTRAL", "NORMAL")["pass"]
    assert e.gate_evidence("TRIM", "AAPL", [], "NEUTRAL", "NORMAL")["pass"]
    assert not e.gate_sleeve_known(None)["pass"] and e.gate_sleeve_known("tactical")["pass"]


def test_sizing_math():
    from investment_engine.risk import sizing as s

    assert s.risk_cap_eur(10000.0, 2.0, 0.25) == 800.0
    out = s.indicative_notional_eur(weight_pct=5.0, cap_pct=20.0, total_equity=10000.0,
                                    risk_pct=2.0, adverse_move=0.25,
                                    sector_headroom_eur=5000.0, deployable_cash_eur=300.0)
    assert out["notional_eur"] == 300.0 and out["binding_constraint"] == "cash"
    out2 = s.indicative_notional_eur(weight_pct=19.0, cap_pct=20.0, total_equity=10000.0,
                                     risk_pct=2.0, adverse_move=0.25,
                                     sector_headroom_eur=5000.0, deployable_cash_eur=9000.0)
    assert out2["notional_eur"] == 100.0 and out2["binding_constraint"] == "position-cap"


def _decisions():
    return [{"ticker": "AAPL", "action": "BUY", "basis": ["canonical-signal"]}]


def test_build_plans_end_to_end_and_guards():
    from investment_engine.risk import order_plan as op

    rows = [_row()]
    bundle = op.build_plans(
        committee_decisions=_decisions(), portfolio_rows=rows, recon_status="PASS",
        free_cash=1000.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[{"ticker": "AAPL"}], regime="NEUTRAL",
        risk_posture="NORMAL", policy=_policy(), sleeves={"AAPL": "tactical"})
    assert len(bundle["plans"]) == 1
    plan = bundle["plans"][0]
    assert plan["human_confirmation_required"] is True
    assert plan["direction"] == "BUY" and plan["indicative_notional_eur"] > 0
    assert all(g["pass"] or g["rule"] == "mapping-verified" for g in plan["policy_checks"])
    assert "Advisory only" in bundle["advisory_guard"]
    assert "not executed" in op.render(bundle)

    fail = op.build_plans(
        committee_decisions=_decisions(), portfolio_rows=rows, recon_status="FAIL",
        free_cash=1000.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[{"ticker": "AAPL"}], regime="NEUTRAL",
        risk_posture="DEFENSIVE", policy=_policy(), sleeves={"AAPL": "tactical"})
    assert fail["plans"] == [] and len(fail["blocked"]) == 1

    core = op.build_plans(
        committee_decisions=[{"ticker": "AAPL", "action": "TRIM", "basis": []}],
        portfolio_rows=[_row(signal="SELL")], recon_status="PASS",
        free_cash=1000.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[], regime="NEUTRAL",
        risk_posture="NORMAL", policy=_policy(core_trims="REQUIRES_USER_VALUE"),
        sleeves={"AAPL": "long_term"})
    assert core["plans"] == [] and "confirmation" in core["blocked"][0]["reason"]

    unknown = op.build_plans(
        committee_decisions=_decisions(), portfolio_rows=rows, recon_status="PASS",
        free_cash=1000.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[{"ticker": "AAPL"}], regime="NEUTRAL",
        risk_posture="NORMAL", policy=_policy(), sleeves={"AAPL": "unknown"})
    assert unknown["plans"] == []


def test_core_trims_allowed_generates_long_term_trim():
    """v1 policy: core_trims confirmed -> TRIM plans allowed on long_term."""
    from investment_engine.risk import order_plan as op

    bundle = op.build_plans(
        committee_decisions=[{"ticker": "AAPL", "action": "TRIM", "basis": []}],
        portfolio_rows=[_row(signal="SELL")], recon_status="PASS",
        free_cash=1000.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[], regime="NEUTRAL",
        risk_posture="NORMAL",
        policy=_policy(core_trims="allowed with human confirmation"),
        sleeves={"AAPL": "long_term"})
    assert len(bundle["plans"]) == 1
    plan = bundle["plans"][0]
    assert plan["direction"] == "TRIM" and plan["sleeve"] == "long_term"
    assert plan["human_confirmation_required"] is True


def test_trim_sizing_ignores_zero_cash():
    """EGT-like 2026-10-10: zero free cash must not produce a €0.00 TRIM plan."""
    from investment_engine.risk import order_plan as op

    bundle = op.build_plans(
        committee_decisions=[{"ticker": "AAPL", "action": "TRIM", "basis": []}],
        portfolio_rows=[_row(signal="SELL", weight=5.0)], recon_status="PASS",
        free_cash=0.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[], regime="NEUTRAL",
        risk_posture="NORMAL", policy=_policy(core_trims=True),
        sleeves={"AAPL": "tactical"})
    assert len(bundle["plans"]) == 1
    plan = bundle["plans"][0]
    # 5% of €10k = €500 position, default 50% trim fraction.
    assert plan["indicative_notional_eur"] == 250.0
    assert plan["binding_constraint"] == "trim-fraction"


def test_trim_dust_lands_in_blocked_not_zero_plan():
    from investment_engine.risk import order_plan as op

    bundle = op.build_plans(
        committee_decisions=[{"ticker": "AAPL", "action": "TRIM", "basis": []}],
        portfolio_rows=[_row(signal="SELL", weight=0.0)], recon_status="PASS",
        free_cash=0.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[], regime="NEUTRAL",
        risk_posture="NORMAL", policy=_policy(core_trims=True),
        sleeves={"AAPL": "tactical"})
    assert bundle["plans"] == []
    assert "below minimum" in bundle["blocked"][0]["reason"]


def test_hold_thesis_blocks_trim_plans():
    """TTWO/GTA VI thesis: TRIM decisions become blocked, BUY still allowed."""
    from investment_engine.risk import order_plan as op

    thesis = {"TTWO": "GTA VI hold"}
    rows = [_row(display="TTWO", signal="SELL", weight=12.5)]
    bundle = op.build_plans(
        committee_decisions=[{"ticker": "TTWO", "action": "TRIM", "basis": []}],
        portfolio_rows=rows, recon_status="PASS",
        free_cash=0.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[], regime="NEUTRAL",
        risk_posture="NORMAL", policy=_policy(core_trims=True),
        sleeves={"TTWO": "tactical"}, hold_thesis=thesis)
    assert bundle["plans"] == []
    assert "hold-thesis" in bundle["blocked"][0]["reason"]
    buys = op.build_plans(
        committee_decisions=[{"ticker": "TTWO", "action": "BUY", "basis": ["x"]}],
        portfolio_rows=rows, recon_status="PASS",
        free_cash=1000.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24",
        news_events=[{"ticker": "TTWO"}], regime="NEUTRAL",
        risk_posture="NORMAL", policy=_policy(core_trims=True),
        sleeves={"TTWO": "tactical"}, hold_thesis=thesis)
    assert len(buys["plans"]) == 1


def _funding_policy(**over):
    return _policy(
        cash={"mandatory_floor_pct": 0.0, "zero_cash_blocks_buys": True,
              "fund_buys_from_planned_trims": True},
        averaging_down={"allowed_sleeves": ["long_term", "core", "thematic"],
                        "require_hold_thesis": True, "max_add_count": 2},
        **over)


def test_trim_proceeds_fund_buy_when_policy_allows():
    from investment_engine.risk import order_plan as op

    rows = [_row(display="AAA"), _row(display="BBB")]
    bundle = op.build_plans(
        committee_decisions=[{"ticker": "AAA", "action": "TRIM", "basis": []},
                             {"ticker": "BBB", "action": "BUY", "basis": ["x"]}],
        portfolio_rows=rows, recon_status="PASS",
        free_cash=0.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[{"ticker": "BBB"}],
        regime="NEUTRAL", risk_posture="NORMAL", policy=_funding_policy(),
        sleeves={"AAA": "tactical", "BBB": "tactical"})
    buy = [p for p in bundle["plans"] if p["direction"] == "BUY"]
    trim = [p for p in bundle["plans"] if p["direction"] == "TRIM"]
    assert len(trim) == 1 and len(buy) == 1
    assert trim[0]["indicative_notional_eur"] == 250.0
    assert buy[0]["indicative_notional_eur"] == 250.0
    assert buy[0]["funding"]["source"] == "planned_trims"
    assert buy[0]["funding"]["trim_proceeds_eur"] == 250.0
    assert bundle["funding"]["trim_funding_enabled"] is True


def test_trim_funding_disabled_keeps_zero_cash_block():
    from investment_engine.risk import order_plan as op

    rows = [_row(display="AAA"), _row(display="BBB")]
    bundle = op.build_plans(
        committee_decisions=[{"ticker": "AAA", "action": "TRIM", "basis": []},
                             {"ticker": "BBB", "action": "BUY", "basis": ["x"]}],
        portfolio_rows=rows, recon_status="PASS",
        free_cash=0.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[{"ticker": "BBB"}],
        regime="NEUTRAL", risk_posture="NORMAL", policy=_policy(),
        sleeves={"AAA": "tactical", "BBB": "tactical"})
    assert [p for p in bundle["plans"] if p["direction"] == "BUY"] == []
    assert any(b["ticker"] == "BBB" and "cash" in b["reason"] for b in bundle["blocked"])


def test_trim_funding_blocks_same_ticker_churn():
    from investment_engine.risk import order_plan as op

    bundle = op.build_plans(
        committee_decisions=[{"ticker": "AAA", "action": "TRIM", "basis": []},
                             {"ticker": "AAA", "action": "BUY", "basis": ["x"]}],
        portfolio_rows=[_row(display="AAA")], recon_status="PASS",
        free_cash=0.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[{"ticker": "AAA"}],
        regime="NEUTRAL", risk_posture="NORMAL", policy=_funding_policy(),
        sleeves={"AAA": "tactical"})
    assert [p for p in bundle["plans"] if p["direction"] == "BUY"] == []
    assert any("churn" in b["reason"] for b in bundle["blocked"])


def test_averaging_down_requires_declared_thesis():
    from investment_engine.risk import order_plan as op

    rows = [_row(display="AAA"), {**_row(display="CCC"), "pnl_pct": -10.0}]
    decisions = [{"ticker": "AAA", "action": "TRIM", "basis": []},
                 {"ticker": "CCC", "action": "BUY", "basis": ["x"]}]
    base = dict(committee_decisions=decisions, portfolio_rows=rows, recon_status="PASS",
                free_cash=0.0, total_equity=10000.0, earnings_status={},
                report_day="2026-09-24", news_events=[{"ticker": "CCC"}],
                regime="NEUTRAL", risk_posture="NORMAL", policy=_funding_policy(),
                sleeves={"AAA": "tactical", "CCC": "long_term"})

    without = op.build_plans(**base)
    assert [p for p in without["plans"] if p["ticker"] == "CCC"] == []
    assert any(b["ticker"] == "CCC" and "thesis" in b["reason"] for b in without["blocked"])

    with_thesis = op.build_plans(**base, hold_thesis={"CCC": "long-term energy thesis"})
    ccc = [p for p in with_thesis["plans"] if p["ticker"] == "CCC"]
    assert len(ccc) == 1 and ccc[0]["direction"] == "BUY"


def test_averaging_down_allowed_tickers_gate():
    from investment_engine.risk import order_plan as op

    rows = [_row(display="AAA"), {**_row(display="CCC"), "pnl_pct": -10.0}]
    base = dict(committee_decisions=[{"ticker": "AAA", "action": "TRIM", "basis": []},
                                     {"ticker": "CCC", "action": "BUY", "basis": ["x"]}],
                portfolio_rows=rows, recon_status="PASS", free_cash=0.0,
                total_equity=10000.0, earnings_status={}, report_day="2026-09-24",
                news_events=[{"ticker": "CCC"}], regime="NEUTRAL",
                risk_posture="NORMAL",
                sleeves={"AAA": "tactical", "CCC": "long_term"})

    denied = _funding_policy()
    denied["averaging_down"]["allowed_tickers"] = ["ZZZ"]
    out = op.build_plans(**base, policy=denied)
    assert [p for p in out["plans"] if p["ticker"] == "CCC"] == []
    assert any("allowed_tickers" in b["reason"] for b in out["blocked"])

    allowed = _funding_policy()
    allowed["averaging_down"]["allowed_tickers"] = ["CCC"]
    out2 = op.build_plans(**base, policy=allowed)
    assert len([p for p in out2["plans"] if p["ticker"] == "CCC"]) == 1


def test_v1_policy_file_shape(tmp_path):
    """Local v1 policy: loads OK, deferred keys stay deferred, caps present."""
    import json

    from investment_engine.risk import policy as pol

    v1 = {
        "policy_version": "v1",
        "risk_per_trade_pct": 2.0,
        "cash": {"mandatory_floor_pct": 0.0, "zero_cash_blocks_buys": True},
        "earnings_blackout": {"before_bdays": 5, "after_bdays": 2},
        "discovery": {"enabled": True},
        "concentration": {"default_max_position_pct": 20.0},
        "crypto_cap_pct": 10.0,
        "tactical_sleeve_cap_pct": 15.0,
        "sector_caps_pct": "REQUIRES_USER_VALUE",
        "core_trims": "allowed with human confirmation",
        "stops": {"scope": "tactical-only"},
    }
    path = tmp_path / "investment_policy.json"
    path.write_text(json.dumps(v1), encoding="utf-8")
    loaded = pol.load_policy(str(path))
    assert loaded["status"] == "OK" and loaded["version"] == "v1"
    assert not pol.is_deferred(loaded["policy"]["core_trims"])
    assert pol.is_deferred(loaded["policy"]["sector_caps_pct"])
    assert loaded["policy"]["crypto_cap_pct"] == 10.0
    assert loaded["policy"]["cash"]["mandatory_floor_pct"] == 0.0


def test_no_execution_capability_in_risk_package():
    import re

    for path in (ROOT / "investment_engine" / "risk").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for pat in (r"\bimport requests\b", r"\bimport socket\b", r"\bsubprocess\b",
                    r"os\.system", r"place_order", r"submit_order", r"execute_order",
                    r"webbrowser", r"Trade212Client"):
            assert not re.search(pat, src), f"{path}:{pat}"


def test_advisory_blocker_text_specific_not_generic():
    """Phase 5: deep dive must show specific blocker reason, not generic text."""
    from investment_engine.reporting.documents import build_deep_dive

    # Case 1: Policy NOT SET
    md1 = build_deep_dive(
        generated_at="2026-10-15 12:00 CEST",
        run_id="test123",
        regime_result=None,
        recon={"status": "PASS"},
        rows=[_row()],
        monitoring_items=[],
        t212_data=None,
        news_by_symbol=None,
        decision_news=[],
        earnings_7d={},
        ideas=[],
        trump_tracking=None,
        commodity_news=None,
        analyst_news=None,
        order_plans={"plans": [], "blocked": [], "policy_version": ""},
    )
    assert "investment policy NOT SET" in md1
    # Generic text must NOT appear
    assert "policy not set, gates unmet, or reconciliation FAIL" not in md1

    # Case 2: Blocked candidates with reasons
    md2 = build_deep_dive(
        generated_at="2026-10-15 12:00 CEST",
        run_id="test123",
        regime_result=None,
        recon={"status": "PASS"},
        rows=[_row()],
        monitoring_items=[],
        t212_data=None,
        news_by_symbol=None,
        decision_news=[],
        earnings_7d={},
        ideas=[],
        trump_tracking=None,
        commodity_news=None,
        analyst_news=None,
        order_plans={
            "plans": [],
            "blocked": [{"ticker": "AAPL", "reason": "zero free cash blocks BUY/ADD"}],
            "policy_version": "v1",
        },
    )
    assert "zero free cash blocks BUY/ADD" in md2
    assert "policy not set, gates unmet, or reconciliation FAIL" not in md2


def test_manifest_policy_version(tmp_path):
    import json

    import portfolio_ai_assistant as entry

    result = {"brief_markdown": "", "snapshot_markdown": "",
              "reconciliation": {"status": "UNKNOWN"}, "failed_tickers": [],
              "monitoring_items": [], "decision_news": [], "brief_metadata": {},
              "investment_policy": {"status": "OK", "version": "v1-preliminary", "problems": []}}
    entry.write_reports(result, tmp_path / "o", tmp_path / "a", "p7")
    manifest = json.loads((tmp_path / "o" / "current" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["policy_version"] == "v1-preliminary"


def test_sleeve_mapping():
    from investment_engine.risk.order_plan import sleeve_for_group

    assert sleeve_for_group("TECH_PIE") == "thematic"
    assert sleeve_for_group("SHORT_TERM_TRADING") == "tactical"
    assert sleeve_for_group("LONG_RUN_DCA") == "long_term"
    assert sleeve_for_group("CRYPTO") == "crypto"
    assert sleeve_for_group("???") == "unknown"


def test_ladder_concentration_trim_to_cap():
    """Phase 7 (hand-computed): 800 EUR in a 10,000 EUR portfolio, cap 5% → sell 300 (37.5%), keep 500."""
    from investment_engine.risk import action_ladder as al

    out = al.build_ladder(ticker="TTWO", reason="concentration_over_cap",
                          weight_pct=8.0, cap_pct=5.0, position_value_eur=800.0,
                          total_equity_eur=10000.0, quantity=4.0, price_eur=200.0,
                          report_day="2026-10-16")
    assert out["action"] == "TRIM"
    assert out["fraction_to_sell"] == 0.375
    assert out["estimated_proceeds_eur"] == 300.0
    assert out["quantity"] == 1.5
    assert out["post_trade_value_eur"] == 500.0
    assert out["post_trade_weight_pct"] == 5.0
    assert out["within_cap_after"] is True
    assert out["review_after"] == "2026-11-15"


def test_ladder_thesis_weakened_half_now():
    """Phase 7: weakened thesis with no trigger fired → 50% now, rest conditional."""
    from investment_engine.risk import action_ladder as al

    out = al.build_ladder(ticker="EGT", reason="thesis_weakened",
                          weight_pct=6.0, cap_pct=20.0, position_value_eur=600.0,
                          total_equity_eur=10000.0, quantity=4000.0, price_eur=0.15,
                          report_day="2026-10-16")
    assert out["fraction_to_sell"] == 0.5
    assert out["estimated_proceeds_eur"] == 300.0
    assert out["tranche_2_trigger"]["metric"] == "downgrade_event"
    assert "50%" in out["wait_branch"]


def test_ladder_below_materiality():
    """Phase 7: a 20 EUR position with a 50 EUR minimum → no action."""
    from investment_engine.risk import action_ladder as al

    out = al.build_ladder(ticker="DUST", reason="concentration_over_cap",
                          weight_pct=0.2, cap_pct=0.1, position_value_eur=20.0,
                          total_equity_eur=10000.0, quantity=10.0, price_eur=2.0,
                          min_trade_value_eur=50.0, report_day="2026-10-16")
    assert out["action"] == "HOLD"
    assert out["verdict"] == "BELOW_MATERIALITY"
    assert out["fraction_to_sell"] == 0.0


def test_ladder_fractional_rounding_never_rounds_up():
    """Phase 7: fractional quantities round DOWN to broker precision."""
    from investment_engine.risk import action_ladder as al

    out = al.build_ladder(ticker="FRC", reason="thesis_broken",
                          weight_pct=1.0, cap_pct=20.0, position_value_eur=100.0,
                          total_equity_eur=10000.0, quantity=0.123456789, price_eur=810.0,
                          report_day="2026-10-16")
    assert out["action"] == "EXIT"
    assert out["quantity"] <= 0.123456789
    assert out["quantity"] == round(out["quantity"], 8)


def test_ladder_tax_unverified_without_facts():
    """Phase 7: missing tax facts → explicit 'unverified', never invented."""
    from investment_engine.risk import action_ladder as al

    out = al.build_ladder(ticker="AAPL", reason="valuation_stretched",
                          weight_pct=10.0, cap_pct=20.0, position_value_eur=1000.0,
                          total_equity_eur=10000.0, quantity=5.0, price_eur=200.0,
                          tax_facts=None, report_day="2026-10-16")
    assert "unverified" in out["tax_note_per_lot"]
    assert "FIFO" in out["lots_first"]


def test_ladder_never_returns_avoid_for_held():
    """Phase 7: held positions get TRIM/EXIT/HOLD — AVOID is for non-held only."""
    from investment_engine.risk import action_ladder as al

    for reason in ("thesis_broken", "thesis_weakened", "concentration_over_cap",
                   "valuation_stretched", "tactical_invalidation",
                   "better_alternative", "cash_needed"):
        out = al.build_ladder(ticker="X", reason=reason, weight_pct=5.0, cap_pct=20.0,
                              position_value_eur=500.0, total_equity_eur=10000.0,
                              quantity=5.0, price_eur=100.0,
                              cash_need_eur=100.0, report_day="2026-10-16")
        assert out["action"] in ("TRIM", "EXIT", "HOLD"), reason


def test_ladder_broken_thesis_ignores_chart():
    """Phase 7: broken thesis = 100% regardless of RSI extremes or P&L."""
    from investment_engine.risk import action_ladder as al

    out = al.build_ladder(ticker="BROK", reason="thesis_broken",
                          weight_pct=2.0, cap_pct=20.0, position_value_eur=200.0,
                          total_equity_eur=10000.0, quantity=2.0, price_eur=100.0,
                          report_day="2026-10-16")
    assert out["action"] == "EXIT"
    assert out["fraction_to_sell"] == 1.0
    assert "bounce" in out["wait_branch"]


def test_ladder_cost_gate_and_load_defaults(tmp_path):
    """Phase 7: cost gate blocks expensive trades; missing config → unevaluable."""
    from investment_engine.risk import action_ladder as al

    blocked = al.build_ladder(ticker="COST", reason="valuation_stretched",
                              weight_pct=10.0, cap_pct=20.0, position_value_eur=1000.0,
                              total_equity_eur=10000.0, quantity=10.0, price_eur=100.0,
                              max_cost_pct=0.1, fee_per_trade_eur=5.0,
                              report_day="2026-10-16")
    assert blocked["verdict"] == "BELOW_MATERIALITY"
    max_pct, min_val = al.load_trading_costs(None)
    assert max_pct is None and min_val == 1.0
    cfg = tmp_path / "profile.yaml"
    cfg.write_text("trading_costs:\n  max_cost_pct: 2.0\n  min_trade_value_eur: 25.0\n",
                   encoding="utf-8")
    max_pct2, min_val2 = al.load_trading_costs(str(cfg))
    assert (max_pct2, min_val2) == (2.0, 25.0)


def test_advisory_evaluation_status_distinguishes_zero_cases():
    """Empty plans must state WHY: upstream failure vs no candidates vs all-HOLD."""
    from investment_engine.risk import order_plan as op

    rows = [_row()]
    base = dict(portfolio_rows=rows, recon_status="PASS",
                free_cash=1000.0, total_equity=10000.0, earnings_status={},
                report_day="2026-09-24", news_events=[{"ticker": "AAPL"}], regime="NEUTRAL",
                risk_posture="NORMAL", policy=_policy(), sleeves={"AAPL": "tactical"})

    # Committee skill failed upstream → UPSTREAM_SKILL_FAILURE
    b1 = op.build_plans(committee_decisions=[], upstream_ok=False, **base)
    assert b1["plans"] == [] and b1["blocked"] == []
    assert b1["evaluation_status"] == "UPSTREAM_SKILL_FAILURE"

    # Skills OK but no decisions → NO_CANDIDATES_PRODUCED
    b2 = op.build_plans(committee_decisions=[], upstream_ok=True, **base)
    assert b2["evaluation_status"] == "NO_CANDIDATES_PRODUCED"

    # All HOLD → NO_ACTIONABLE_SIGNAL (HOLD decisions are not candidates)
    b3 = op.build_plans(
        committee_decisions=[{"ticker": "AAPL", "action": "HOLD", "basis": []}],
        upstream_ok=True, **base)
    assert b3["plans"] == [] and b3["blocked"] == []
    assert b3["evaluation_status"] == "NO_ACTIONABLE_SIGNAL"


def test_advisory_fixture_one_plan_one_blocked():
    """Offline fixture: one candidate passes all gates, one is blocked.
    No broker calls, no order execution — pure gate evaluation.
    """
    from investment_engine.risk import order_plan as op

    # Zero free cash blocks BUY plans
    buy_bundle = op.build_plans(
        committee_decisions=[
            {"ticker": "AAPL", "action": "BUY", "basis": ["canonical-signal"]},
        ],
        portfolio_rows=[_row(display="AAPL", signal="BUY", weight=5.0)],
        recon_status="PASS",
        free_cash=0.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[{"ticker": "AAPL"}],
        regime="NEUTRAL", risk_posture="NORMAL", policy=_policy(),
        sleeves={"AAPL": "tactical"})
    assert buy_bundle["evaluation_status"] == "ALL_BLOCKED"
    assert any("cash" in b["reason"] for b in buy_bundle["blocked"])

    # TRIM path: under-cap position passes, dust-weight position blocked
    trim_bundle = op.build_plans(
        committee_decisions=[
            {"ticker": "AAPL", "action": "TRIM", "basis": ["canonical-signal"]},
            {"ticker": "MSFT", "action": "TRIM", "basis": ["canonical-signal"]},
        ],
        portfolio_rows=[_row(display="AAPL", signal="SELL", weight=15.0),
                        _row(display="MSFT", signal="SELL", weight=0.0)],
        recon_status="PASS", free_cash=0.0, total_equity=10000.0, earnings_status={},
        report_day="2026-09-24", news_events=[], regime="NEUTRAL",
        risk_posture="NORMAL", policy=_policy(core_trims=True),
        sleeves={"AAPL": "tactical", "MSFT": "tactical"})
    assert trim_bundle["evaluation_status"] == "PLANS_GENERATED"
    assert len(trim_bundle["plans"]) == 1 and trim_bundle["plans"][0]["ticker"] == "AAPL"
    assert len(trim_bundle["blocked"]) == 1 and trim_bundle["blocked"][0]["ticker"] == "MSFT"

"""Tests for custom_rules application and the explicit cash-floor override."""

from __future__ import annotations

from types import SimpleNamespace

from investment_engine.config.custom_rules import apply_custom_rules_to_settings
from investment_engine.config.settings import EngineSettings
from investment_engine.run_engine import apply_user_cash_floor


def test_investment_rules_cash_floor_maps_to_settings():
    settings = EngineSettings()
    rules = {"investment_rules": {"cash_floor_pct": 0.0}}
    apply_custom_rules_to_settings(settings, rules)
    assert settings.cash_floor_pct == 0.0


def test_script_behavior_still_applies():
    settings = EngineSettings()
    rules = {"script_behavior": {"max_news_age_days": 3}}
    apply_custom_rules_to_settings(settings, rules)
    assert settings.max_news_age_days == 3


def test_unknown_investment_rule_is_ignored():
    settings = EngineSettings()
    before = settings.cash_floor_pct
    apply_custom_rules_to_settings(
        settings, {"investment_rules": {"not_a_real_setting": 123}}
    )
    assert settings.cash_floor_pct == before
    assert not hasattr(settings, "not_a_real_setting")


def test_explicit_zero_cash_floor_disables_regime_cash_target():
    regime = SimpleNamespace(implications={"cash_target_pct": 10})
    result = apply_user_cash_floor(regime, 0.0)
    assert result.implications["cash_target_pct"] == 0.0


def test_missing_cash_floor_keeps_regime_target():
    regime = SimpleNamespace(implications={"cash_target_pct": 15})
    result = apply_user_cash_floor(regime, None)
    assert result.implications["cash_target_pct"] == 15


def test_invalid_cash_floor_keeps_regime_target():
    regime = SimpleNamespace(implications={"cash_target_pct": 15})
    result = apply_user_cash_floor(regime, "not-a-number")
    assert result.implications["cash_target_pct"] == 15


def test_zero_cash_target_is_rendered_not_replaced_by_default():
    from investment_engine.reporting.formatters import format_cash_deployment

    regime = SimpleNamespace(regime="NEUTRAL", implications={"cash_target_pct": 0.0})
    t212_data = {
        "cash": {"free": 50.0},
        "account_summary": {"total_equity": 1000.0},
        "reconciliation_ok": True,
    }
    text = format_cash_deployment(
        regime, t212_data, {}, [], recon_status="PASS", sell_plan_count=0
    )
    assert "cash target 0%" in text


def test_deterministic_summary_does_not_claim_zero_target_requires_trims():
    from investment_engine.reporting.formatters import deterministic_summary

    regime = SimpleNamespace(regime="NEUTRAL", implications={"cash_target_pct": 0.0})
    t212_data = {
        "cash": {"free": 50.0, "pie_cash": 0.0, "blocked": 0.0},
        "account_summary": {"total_equity": 1000.0},
    }
    text = deterministic_summary([], regime, t212_data)
    assert "disabled by user" in text
    assert "requires manual trims" not in text


def test_deterministic_summary_stance_matches_buy_signals():
    from investment_engine.reporting.formatters import deterministic_summary

    regime = SimpleNamespace(regime="NEUTRAL", implications={"cash_target_pct": 0.0})
    t212_data = {
        "cash": {"free": 50.0, "pie_cash": 0.0, "blocked": 0.0},
        "account_summary": {"total_equity": 1000.0},
    }
    rows = [
        {"display_symbol": "AAPL", "signal": "BUY", "weight": 2.0, "pnl_pct": 1.0},
        {"display_symbol": "MSFT", "signal": "HOLD", "weight": 3.0, "pnl_pct": -1.0},
    ]
    text = deterministic_summary(rows, regime, t212_data)
    assert "stance BUY" in text
    assert "1 BUY / 0 SELL" in text
    assert "1 BUY signal(s) require manual confirmation" in text


def test_explicit_cash_floor_overrides_policy_reserve():
    from investment_engine.run_engine import apply_user_cash_floor_to_policy

    policy_state = {
        "status": "OK",
        "policy": {"cash": {"mandatory_floor_pct": 5.0}},
    }
    result = apply_user_cash_floor_to_policy(policy_state, 0.0)
    assert result["policy"]["cash"]["mandatory_floor_pct"] == 0.0


def test_missing_cash_floor_keeps_policy_reserve():
    from investment_engine.run_engine import apply_user_cash_floor_to_policy

    policy_state = {
        "status": "OK",
        "policy": {"cash": {"mandatory_floor_pct": 5.0}},
    }
    result = apply_user_cash_floor_to_policy(policy_state, None)
    assert result["policy"]["cash"]["mandatory_floor_pct"] == 5.0


def test_cash_floor_not_applied_when_policy_missing():
    from investment_engine.run_engine import apply_user_cash_floor_to_policy

    policy_state = {"status": "NOT SET", "policy": {}}
    result = apply_user_cash_floor_to_policy(policy_state, 0.0)
    assert result["policy"] == {}

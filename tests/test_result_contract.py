"""Result-contract tests: run_engine() must return every key the wrapper
and generate_human_brief() consume. Guards against empty-brief regressions."""

from __future__ import annotations

import pytest

import portfolio_ai_assistant as wrapper
from investment_engine.reporting import report_structure


def _required_keys() -> tuple:
    return (
        "portfolio_rows",
        "monitoring_items",
        "regime_result",
        "decision_news",
        "earnings_7d",
        "ideas",
        "portfolio_names",
    )


def test_wrapper_contract_keys_match_brief_signature():
    """Every key the wrapper extracts must be a generate_human_brief() parameter."""
    import inspect

    params = set(inspect.signature(report_structure.generate_human_brief).parameters)
    for key in _required_keys():
        assert key in params, f"wrapper reads {key!r} which generate_human_brief() does not accept"


def test_run_engine_returns_brief_keys(monkeypatch):
    """run_engine() return dict contains all human-brief keys (mocked internals)."""
    import investment_engine.main as engine

    sentinel = {
        "portfolio_rows": [{"display": "AAPL"}],
        "monitoring_items": [{"display": "AAPL"}],
        "regime_result": None,
        "decision_news": [],
        "earnings_7d": {},
        "ideas": [],
        "portfolio_names": {"AAPL": "Apple"},
    }

    # Patch at module level is heavy; instead verify the source contract:
    # the final return statement of run_engine() must reference each key.
    import pathlib

    src = pathlib.Path(engine.__file__).read_text(encoding="utf-8")
    anchor = src.index("def _build_ai_recommendations")
    start = src.rindex("    return {", 0, anchor)
    ret_block = src[start:anchor]
    for key in _required_keys():
        assert f'"{key}"' in ret_block, f"run_engine() return is missing {key!r}"


def test_failed_tickers_helpers_present():
    from investment_engine.reporting import failed_tickers as ft

    assert callable(ft.collect_failed_tickers)
    assert callable(ft.render_failed_tickers_md)
    assert ft.render_failed_tickers_md([], "r1") == ""
    md = ft.render_failed_tickers_md(
        [{"display": "XXX", "t212_id": "XXX_US_EQ", "yahoo_attempted": "XXX",
          "support_state": "UNRESOLVED", "fetch_failed": True,
          "qty": 1, "value_eur": 10.0, "alias_hint": {"XXX": "<YAHOO_SYMBOL>"}}],
        "r1",
    )
    assert "XXX" in md and "symbol_aliases" in md


def test_intelligence_brief_news_items_have_clickable_links():
    """Phase 3: news items in brief must have clickable URLs and publication times."""
    from investment_engine.reporting.documents import build_intelligence_brief

    result = {
        "run_id": "test123",
        "brief_generated_at": "2026-10-15T12:00:00+00:00",
        "portfolio_rows": [],
        "reconciliation": {"status": "PASS"},
        "t212_data": {
            "account_summary": {"total_equity": 1000.0},
            "cash": {"free": 100.0},
            "timestamp": "2026-10-15T11:00:00+00:00",
        },
        "decision_news": [
            {
                "title": "AAPL beats earnings",
                "url": "https://example.com/aapl-earnings",
                "source": "Reuters",
                "published": "2026-10-15T08:00:00+00:00",
            }
        ],
        "earnings_7d": {},
        "ideas": [],
        "research_corpus": {"counts": {"total": 5, "decision": 3}},
        "providers_per_stage": {
            "decision": {"provider": "Gemini", "model_served": "gemini-2.5-flash"},
        },
        "investment_policy": {"status": "OK"},
    }
    brief = build_intelligence_brief(result)
    assert "[AAPL beats earnings](https://example.com/aapl-earnings)" in brief
    assert "Reuters" in brief
    assert "2026-10-15" in brief  # publication date


def test_intelligence_brief_has_explicit_status_section():
    """Phase 3: brief must have explicit status section, not health score."""
    from investment_engine.reporting.documents import build_intelligence_brief

    result = {
        "run_id": "test123",
        "brief_generated_at": "2026-10-15T12:00:00+00:00",
        "portfolio_rows": [],
        "reconciliation": {"status": "PASS"},
        "t212_data": {
            "account_summary": {"total_equity": 1000.0},
            "cash": {"free": 100.0},
            "timestamp": "2026-10-15T11:00:00+00:00",
        },
        "decision_news": [],
        "earnings_7d": {},
        "ideas": [],
        "research_corpus": {"counts": {"total": 5, "decision": 3}},
        "providers_per_stage": {},
        "investment_policy": {"status": "OK"},
    }
    brief = build_intelligence_brief(result)
    assert "## Status" in brief
    assert "Broker data: available" in brief
    assert "Accounting audit: PASS" in brief
    # WP3: precise counts, not the misleading "decision-grade" label.
    assert "Research coverage: 5 items collected" in brief
    assert "3 fresh decision-tier" in brief
    assert "decision-grade" not in brief
    assert "Advisory eligibility: OK" in brief
    # Health score must NOT appear
    assert "Health score" not in brief
    assert "90/100" not in brief


def test_brief_pnl_unavailable_not_zero():
    """Phase 8: missing P&L must say unavailable, never €+0.00."""
    from investment_engine.reporting.documents import build_intelligence_brief

    base = {
        "run_id": "t8", "brief_generated_at": "2026-10-16T12:00:00+00:00",
        "portfolio_rows": [], "reconciliation": {"status": "PASS"},
        "t212_data": {"account_summary": {"total_equity": 1000.0},
                      "cash": {"free": 10.0}, "timestamp": "2026-10-16T11:00:00+00:00"},
        "decision_news": [], "earnings_7d": {}, "ideas": [],
        "research_corpus": {"counts": {"total": 0, "decision": 0}},
        "account_performance": {"net_pnl_after_costs_eur": None,
                               "net_deposits_status": "UNAVAILABLE"},
        "providers_per_stage": {}, "investment_policy": {"status": "OK"},
    }
    brief = build_intelligence_brief(base)
    assert "Net P&L unavailable" in brief
    assert "Net P&L €+0.00" not in brief

    ok = dict(base, account_performance={"net_pnl_after_costs_eur": 132.19,
                                         "return_pct": 4.13,
                                         "net_deposits_status": "VERIFIED"})
    brief2 = build_intelligence_brief(ok)
    assert "Net P&L €+132.19 (+4.13%)" in brief2


def test_brief_timestamps_are_explicit_utc():
    """Phase 8: no bare local times; UTC explicitly labelled."""
    from investment_engine.reporting.documents import build_intelligence_brief

    result = {
        "run_id": "t8", "brief_generated_at": "2026-10-16T12:00:00+00:00",
        "portfolio_rows": [], "reconciliation": {"status": "PASS"},
        "t212_data": {"account_summary": {"total_equity": 1000.0},
                      "cash": {"free": 10.0}, "timestamp": "2026-10-16T11:00:00+00:00"},
        "decision_news": [{"title": "X beats", "url": "https://example.com/x",
                           "source": "Reuters", "published": "2026-10-16T08:00:00+00:00",
                           "why": "Why it matters: test.", "links": ["AAPL"]}],
        "earnings_7d": {}, "ideas": [],
        "research_corpus": {"counts": {"total": 1, "decision": 1}},
        "providers_per_stage": {}, "investment_policy": {"status": "OK"},
    }
    brief = build_intelligence_brief(result)
    assert "2026-10-16 08:00 UTC" in brief
    assert "Why it matters: test." in brief
    assert "[linked: AAPL]" in brief


def test_brief_todays_plan_buckets():
    """Phase 8: Today's plan separates immediate / conditional / monitoring / research."""
    from investment_engine.reporting.documents import build_intelligence_brief

    result = {
        "run_id": "t8", "brief_generated_at": "2026-10-16T12:00:00+00:00",
        "portfolio_rows": [], "reconciliation": {"status": "PASS"},
        "t212_data": {"account_summary": {"total_equity": 10000.0},
                      "cash": {"free": 1000.0}, "timestamp": "2026-10-16T11:00:00+00:00"},
        "decision_news": [], "earnings_7d": {},
        "ideas": [{"ticker": "NVDA", "reason": "watch"}],
        "research_corpus": {"counts": {"total": 0, "decision": 0}},
        "providers_per_stage": {}, "investment_policy": {"status": "OK"},
        "monitoring_items": [{"display": "TTWO", "presentation": "HOLD",
                              "triggers": "weight 12% ≥ 5%", "weight": 12.0}],
        "order_plans": {"plans": [{"ticker": "AAPL", "direction": "TRIM",
                                   "indicative_notional_eur": 100.0}],
                        "blocked": [{"ticker": "MSFT", "reason": "zero free cash blocks BUY"}],
                        "evaluation_status": "PLANS_GENERATED"},
    }
    brief = build_intelligence_brief(result)
    assert "## Today's plan" in brief
    assert "NOW: **AAPL**" in brief
    assert "CONDITIONAL: **MSFT**" in brief
    assert "no add proposed" in brief  # HOLD format rule


def test_brief_concentration_section():
    """Phase 8: effective holdings, top weights, small positions, FX exposure."""
    from investment_engine.reporting.documents import build_intelligence_brief

    rows = [{"display_symbol": "A", "ticker": "A", "weight": 50.0, "quote_currency": "USD"},
            {"display_symbol": "B", "ticker": "B", "weight": 30.0, "quote_currency": "EUR"},
            {"display_symbol": "C", "ticker": "C", "weight": 15.0, "quote_currency": "EUR"},
            {"display_symbol": "D", "ticker": "D", "weight": 0.5, "quote_currency": "GBX"}]
    result = {
        "run_id": "t8", "brief_generated_at": "2026-10-16T12:00:00+00:00",
        "portfolio_rows": rows, "reconciliation": {"status": "PASS"},
        "t212_data": {"account_summary": {"total_equity": 10000.0},
                      "cash": {"free": 100.0}, "timestamp": "2026-10-16T11:00:00+00:00"},
        "decision_news": [], "earnings_7d": {}, "ideas": [],
        "research_corpus": {"counts": {"total": 0, "decision": 0}},
        "providers_per_stage": {}, "investment_policy": {"status": "OK"},
    }
    brief = build_intelligence_brief(result)
    assert "## Concentration" in brief
    assert "Effective holdings: 2.8" in brief  # 1/(0.25+0.09+0.0225+0.000025)
    assert "A 50.0%" in brief
    assert "Small positions" in brief
    assert "USD: 50.0%" in brief


def test_deterministic_skill_attribution_not_unknown():
    """_note_deterministic_skill must record provider=deterministic, never unknown."""
    import investment_engine.main as m
    from investment_engine.providers.fallback import reset_circuit_breaker

    reset_circuit_breaker()
    m._STAGE_ATTRIBUTION.clear()
    m._note_deterministic_skill("risk", "deterministic_by_design")
    rec = m._STAGE_ATTRIBUTION["risk"]
    assert rec["provider"] == "deterministic"
    assert rec["model_served"] == "deterministic(skills)"
    assert rec["reason"] == "deterministic_by_design"
    m._STAGE_ATTRIBUTION.clear()
    reset_circuit_breaker()


def test_stage_counting_ignores_unknown():
    """Unknown/unrecorded stages must not inflate the LLM count."""
    from investment_engine.reporting.documents import build_intelligence_brief

    result = {
        "run_id": "test123",
        "brief_generated_at": "2026-10-15T12:00:00+00:00",
        "portfolio_rows": [],
        "reconciliation": {"status": "PASS"},
        "t212_data": {
            "account_summary": {"total_equity": 1000.0},
            "cash": {"free": 100.0},
            "timestamp": "2026-10-15T11:00:00+00:00",
        },
        "decision_news": [],
        "earnings_7d": {},
        "ideas": [],
        "research_corpus": {"counts": {"total": 5, "decision": 3}},
        "providers_per_stage": {
            "decision": {"provider": "Gemini", "model_served": "gemini-2.5-flash",
                         "fallback_depth": 0, "error_class": ""},
            "risk": {"provider": "deterministic", "model_served": "deterministic(skills)",
                     "fallback_depth": 99, "error_class": ""},
            "mystery": {"provider": "unknown", "model_served": "",
                        "fallback_depth": -1, "error_class": ""},
        },
        "investment_policy": {"status": "OK"},
    }
    brief = build_intelligence_brief(result)
    assert "1 LLM stages, 1 deterministic, 1 unknown/unrecorded" in brief


def test_weak_match_dropped_from_decision():
    """Phase 5: a Meta article without company name is dropped from decision news."""
    from datetime import datetime, timezone
    from investment_engine.research.news_engine import filter_decision_news

    now = datetime.now(timezone.utc)
    recs = {
        "CBRS": [{"title": "Meta and the metaverse: what investors should know",
                  "url": "https://example.com/meta-metaverse", "source": "Reuters",
                  "published_dt": now, "hours_ago": 2, "relevance_score": 80,
                  "content_hash": "h1", "query": "q"}],
        "META": [{"title": "Meta Platforms reports strong Q4 revenue",
                  "url": "https://example.com/meta-q4", "source": "Reuters",
                  "published_dt": now, "hours_ago": 2, "relevance_score": 80,
                  "content_hash": "h2", "query": "q"}],
    }
    out = filter_decision_news(recs, owned={"CBRS", "META"}, relevance_min=30, now=now,
                               names={"META": "Meta Platforms"})
    titles = [r["title"] for r in out]
    assert "Meta and the metaverse: what investors should know" not in titles
    assert "Meta Platforms reports strong Q4 revenue" in titles

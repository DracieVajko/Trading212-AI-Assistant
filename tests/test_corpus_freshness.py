"""WP3 — Corpus extraction/freshness/events.

Tests:
- undated articles are excluded from the decision set;
- future (implausible) timestamps are never decision-relevant;
- corpus items carry explicit completeness labels (never "full article"
  from a headline);
- the brief distinguishes collected items, decision-tier items, and items
  actually selected for analysis (no misleading "decision-grade" label).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from investment_engine.research.corpus.freshness import age_hours, classify
from investment_engine.research.corpus.adapters import _record_to_item


# --------------------------------------------------------------------------
# Freshness / rejection
# --------------------------------------------------------------------------

def test_undated_article_is_excluded_from_decision():
    assert classify(None, tier=1, category="general") == "EXCLUDED-UNDATED"


def test_future_article_is_not_decision():
    future = datetime.now(timezone.utc) + timedelta(hours=5)
    age = age_hours(future.isoformat())
    assert age is not None and age < 0
    assert classify(age, tier=1, category="general") == "BACKGROUND"


def test_stale_article_is_background():
    stale = datetime.now(timezone.utc) - timedelta(hours=120)
    age = age_hours(stale.isoformat())
    assert classify(age, tier=1, category="general") == "BACKGROUND"


def test_fresh_tier1_article_is_decision():
    fresh = datetime.now(timezone.utc) - timedelta(hours=6)
    age = age_hours(fresh.isoformat())
    assert classify(age, tier=1, category="general") == "DECISION"


def test_reference_category_is_background_reference():
    fresh = datetime.now(timezone.utc) - timedelta(hours=1)
    age = age_hours(fresh.isoformat())
    assert classify(age, tier=1, category="earnings_calendar") == "BACKGROUND-REFERENCE"


# --------------------------------------------------------------------------
# Completeness labels
# --------------------------------------------------------------------------

def _record(title="Title", url="https://example.com/a", preview="", source="Reuters",
            category="general", tier=1, published=None, symbol="AAPL"):
    rec = {
        "title": title,
        "url": url,
        "source": source,
        "category": category,
        "tier": tier,
        "published": published or datetime.now(timezone.utc).isoformat(),
    }
    if preview:
        rec["preview"] = preview
    return rec


def test_headline_only_label_when_no_preview():
    now = datetime.now(timezone.utc)
    item = _record_to_item(_record(preview=""), "AAPL", now)
    assert item["completeness"] == "HEADLINE_ONLY"


def test_rss_summary_label_when_preview_present():
    now = datetime.now(timezone.utc)
    item = _record_to_item(
        _record(preview="Company reports quarterly results and guidance.", ), "AAPL", now)
    assert item["completeness"] == "RSS_SUMMARY"


def test_completeness_never_claims_full_text():
    """A headline/RSS item must never be labelled FULL_TEXT."""
    now = datetime.now(timezone.utc)
    for preview in ("", "short summary"):
        item = _record_to_item(_record(preview=preview), "AAPL", now)
        assert item["completeness"] in ("HEADLINE_ONLY", "RSS_SUMMARY")
        assert item["completeness"] != "FULL_TEXT"


# --------------------------------------------------------------------------
# Brief research label
# --------------------------------------------------------------------------

def test_brief_label_distinguishes_selected_from_decision_tier():
    from investment_engine.reporting.documents import build_intelligence_brief

    result = {
        "run_id": "wp3test",
        "portfolio_rows": [{"display_symbol": "AAPL", "signal": "HOLD"}],
        "reconciliation": {"status": "PASS"},
        "research_corpus": {"counts": {"total": 18, "decision": 18, "background": 0,
                                       "undated": 0, "rejected": 0}},
        "decision_news": [{"title": "t", "url": "https://x", "source": "S", "age": "2h"}],
        "monitoring_items": [],
        "earnings_7d": {},
        "ideas": [],
        "portfolio_names": {},
        "regime_result": None,
    }
    brief = build_intelligence_brief(result)
    assert "18 items collected" in brief
    assert "18 fresh decision-tier" in brief
    assert "1 selected for analysis" in brief
    assert "decision-grade" not in brief


def test_brief_label_without_filter_mentions_decision_tier():
    from investment_engine.reporting.documents import build_intelligence_brief

    result = {
        "run_id": "wp3test2",
        "portfolio_rows": [{"display_symbol": "AAPL", "signal": "HOLD"}],
        "reconciliation": {"status": "PASS"},
        "research_corpus": {"counts": {"total": 5, "decision": 5}},
        "decision_news": [{"title": "a"}, {"title": "b"}, {"title": "c"},
                          {"title": "d"}, {"title": "e"}],
        "monitoring_items": [],
        "earnings_7d": {},
        "ideas": [],
        "portfolio_names": {},
        "regime_result": None,
    }
    brief = build_intelligence_brief(result)
    assert "5 items" in brief
    assert "5 fresh decision-tier" in brief
    assert "decision-grade" not in brief


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
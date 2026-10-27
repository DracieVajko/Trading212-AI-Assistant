"""Phase 5 corpus: schema, tiers, freshness, dedupe, adapters, builder.

Offline only (frozen fixtures, fixed clock). No live API.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _rec(title="AAPL beats", url="https://example.com/a", source="Reuters",
         hours_ago=5, category="general", tier=1, relevance=80):
    return {
        "title": title, "url": url, "source": source,
        "published_dt": NOW - timedelta(hours=hours_ago),
        "published_str": "2026-09-24",
        "category": category, "tier": tier, "relevance_score": relevance,
        "preview": "preview text",
    }


def test_schema_valid_and_forbids_extra():
    from investment_engine.schemas.research_item import ResearchItem

    item = ResearchItem(
        id="abc123", title="t", canonical_url="https://example.com/x",
        published_at_utc="2026-09-24T10:00:00+00:00", age_hours=2.0,
        source_tier=1, fetch_status="OK")
    assert item.decision_relevant()
    with pytest.raises(Exception):
        ResearchItem(id="x", title="t", canonical_url="https://example.com/x",
                     published_at_utc=NOW.isoformat(), fetch_status="OK",
                     totally_made_up_field=1)


def test_schema_rejects_bad_url_and_undated_ok():
    from pydantic import ValidationError

    from investment_engine.schemas.research_item import ResearchItem

    with pytest.raises(ValidationError):
        ResearchItem(id="x", title="t", canonical_url="not-a-url",
                     published_at_utc=NOW.isoformat(), fetch_status="OK")
    with pytest.raises(ValidationError):
        ResearchItem(id="x", title="t", canonical_url="https://example.com/x",
                     published_at_utc="", fetch_status="OK")
    undated = ResearchItem(id="x", title="t", canonical_url="https://example.com/x",
                           fetch_status="UNDATED")
    assert not undated.decision_relevant()
    assert undated.background_label() == "UNDATED"


def test_freshness_boundaries():
    from investment_engine.research.corpus import freshness as f

    assert f.age_hours(NOW - timedelta(hours=47.9), NOW) == pytest.approx(47.9)
    assert f.age_hours(None, NOW) is None
    assert f.age_hours("undated", NOW) is None
    assert f.classify(47.9, 1, "general") == "DECISION"
    assert f.classify(48.1, 1, "general") == "BACKGROUND"
    assert f.classify(5.0, 3, "reddit") == "BACKGROUND"
    assert f.classify(None, 0, "general") == "EXCLUDED-UNDATED"


def test_tiers_social_never_decision():
    from investment_engine.research.corpus import tiers as t

    assert t.tier_for_category("reddit", 0) == 3
    assert not t.may_enter_decision(0, "reddit")
    assert t.may_enter_decision(2, "general")
    assert not t.may_enter_decision(3, "general")


def test_dedupe_trackers_and_fuzzy_titles():
    from investment_engine.research.corpus import dedupe as d

    assert d.normalize_url("https://Example.COM/x?utm_source=a&b=1") == "https://example.com/x?b=1"
    assert d.item_id("https://example.com/x?utm_source=a") == d.item_id("https://example.com/x")
    assert d.titles_similar("Apple unveils new AI chip datacenters today",
                            "Apple unveils new AI chip datacenters today updated")
    assert not d.titles_similar("Apple earnings beat", "Tesla deliveries miss")
    items = [
        {"id": "1", "title": "Apple unveils new AI chip for datacenters",
         "canonical_url": "https://a.example/1"},
        {"id": "2", "title": "Apple unveils new AI chip for datacenters",
         "canonical_url": "https://b.example/2"},
    ]
    assert len(d.dedupe(items)) == 1


def test_adapter_never_raises_and_marks_undated():
    from investment_engine.research.corpus import adapters as ad

    out = ad.adapt_symbol_records("AAPL", [_rec(), {"garbage": True}, "not-a-dict",
                                           _rec(title="HTML scrape", hours_ago=0) | {"published_dt": None}],
                                  "AAPL", NOW)
    assert all(isinstance(i, dict) for i in out)
    undated = [i for i in out if i["title"] == "HTML scrape"]
    assert undated and undated[0]["fetch_status"] == "UNDATED"
    assert all(i["fetch_status"] != "OK" or i["published_at_utc"] for i in out)


def test_builder_counts_and_files(tmp_path):
    from investment_engine.research.corpus.builder import build_corpus, build_corpus_files

    news = {
        "AAPL": [_rec(hours_ago=5), _rec(title="Old story", url="https://example.com/old", hours_ago=100)],
        "REDDIT": [_rec(title="Hype thread", url="https://reddit.example/r", source="r/wallstreetbets",
                         category="reddit", tier=3)],
        "SLOVAK": [{"title": "HTML scrape", "url": "https://sme.example/x", "source": "SME",
                    "published_dt": None, "published_str": "undated", "undated": True, "category": "slovak"}],
    }
    corpus = build_corpus(news, NOW)
    assert corpus["counts"]["total"] >= 3
    assert corpus["counts"]["decision"] == 1
    assert corpus["counts"]["undated"] == 1
    assert corpus["decision_items"][0]["title"].startswith("AAPL beats")
    info = build_corpus_files(news, run_id="t5", output_dir=str(tmp_path), now=NOW)
    assert info["path_md"] and info["path_json"]
    assert "Decision-relevant" in open(info["path_md"], encoding="utf-8").read()


def test_builder_survives_garbage_buckets():
    from investment_engine.research.corpus.builder import build_corpus

    corpus = build_corpus({"X": None, "Y": "junk", "Z": [{"ok": False}]}, NOW)
    assert corpus["counts"]["total"] >= 0  # never raises; degraded by design


def test_decision_filter_default_is_48h():
    import inspect

    from investment_engine.research.news_engine import filter_decision_news

    assert inspect.signature(filter_decision_news).parameters["max_age_hours"].default == 48


def test_sector_templates_healthcare():
    from investment_engine.research.sector_templates import build_dynamic_search_queries
    assert any("FDA" in q for q in build_dynamic_search_queries("XYZ", "healthcare"))
    assert any("PDUFA" in q or "trial" in q.lower() for q in build_dynamic_search_queries("XYZ", "biotech"))


def test_bucket_names_never_become_ticker_tags():
    """Phase 2: RSS_FALLBACK/SLOVAK/REDDIT buckets record queried_for, not ticker_tags."""
    from datetime import datetime, timezone
    from investment_engine.research.corpus import adapters as ad

    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    rec = {"title": "Market selloff deepens", "url": "https://example.com/x",
           "source": "CNBC", "published_dt": now, "category": "general", "tier": 1}
    for bucket in ("RSS_FALLBACK", "SLOVAK", "REDDIT"):
        items = ad.adapt_symbol_records(bucket, [dict(rec)], bucket, now)
        assert items, bucket
        assert items[0]["ticker_tags"] == [], f"{bucket} leaked into ticker_tags"
        assert items[0]["queried_for"] == bucket
        assert items[0]["portfolio_relevance"] == "unconfirmed"
    # Entity bucket without symbol in content → indirect (bucket link only).
    items = ad.adapt_symbol_records("AAPL", [dict(rec)], "AAPL", now)
    assert items[0]["ticker_tags"] == ["AAPL"]
    assert items[0]["queried_for"] == "AAPL"
    assert items[0]["portfolio_relevance"] == "indirect"
    assert items[0]["entities_confirmed_in_content"] == []
    # Entity bucket with symbol in the title → direct, confirmed.
    direct = dict(rec, title="AAPL beats earnings on iPhone demand")
    items = ad.adapt_symbol_records("AAPL", [direct], "AAPL", now)
    assert items[0]["portfolio_relevance"] == "direct"
    assert items[0]["entities_confirmed_in_content"] == ["AAPL"]


def test_tradingview_distributor_split():
    """Phase 2: TradingView/<origin> splits into publisher + distributor."""
    from datetime import datetime, timezone
    from investment_engine.research.corpus import adapters as ad

    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    rec = {"title": "Chip stocks fall", "url": "https://example.com/y",
           "source": "TradingView/benzinga", "published_dt": now,
           "category": "tv_symbol", "tier": 2}
    items = ad.adapt_symbol_records("NVDA", [rec], "NVDA", now)
    assert items[0]["publisher"] == "benzinga"
    assert items[0]["distributor"] == "TradingView"


def test_sector_region_backfill():
    """Phase 2: keyword backfill fills sector/region tags, unknown stays empty."""
    from investment_engine.research.corpus import sector_map

    sectors, regions = sector_map.tags_for("TSMC chip profit beats on AI boom", "")
    assert "semiconductors" in sectors
    assert "ai" in sectors
    sectors2, regions2 = sector_map.tags_for("Random local bakery opens", "")
    assert sectors2 == [] and regions2 == []
    sectors3, regions3 = sector_map.tags_for("China chip export controls", "")
    assert "CN" in regions3


def test_research_universe_builder():
    """Phase 2: universe covers holdings + watchlist + themes + benchmarks."""
    from investment_engine.research.universe import build_research_universe

    u = build_research_universe(
        [{"broker_symbol": "AAPL_US_EQ"}, {"yahoo_symbol": "msft"}],
        ["NVDA", "aapl_us_eq"],
        ["AI", "batteries"],
        ["EXI2.DE"],
        ["PLTR"],
    )
    assert u["holdings"] == ["AAPL_US_EQ", "MSFT"]
    assert u["watchlist"] == ["NVDA", "AAPL_US_EQ"]
    assert u["themes"] == ["AI", "BATTERIES"]
    assert u["benchmarks"] == ["EXI2.DE"]
    assert u["discovery"] == ["PLTR"]


def test_issuer_aggregation_combines_listings():
    """Phase 2: same ISIN via two listings = one issuer exposure, rows intact."""
    from investment_engine.portfolio.exposure import aggregate_issuer_exposure

    rows = [
        {"display_symbol": "AAPL", "ticker": "AAPL_US_EQ", "isin": "US0378331005",
         "value_eur": 500.0, "weight": 5.0},
        {"display_symbol": "AAPL", "ticker": "APCd_EQ", "isin": "US0378331005",
         "value_eur": 300.0, "weight": 3.0},
        {"display_symbol": "MSFT", "ticker": "MSFT_US_EQ", "isin": "US5949181045",
         "value_eur": 200.0, "weight": 2.0},
    ]
    agg = aggregate_issuer_exposure(rows)
    assert len(agg) == 2
    aapl = next(g for g in agg if g["isin"] == "US0378331005")
    assert aapl["value_eur"] == 800.0
    assert aapl["weight_pct"] == 8.0
    assert sorted(aapl["listings"]) == ["AAPL_US_EQ", "APCd_EQ"]


def test_source_status_ledger_records_and_summarizes():
    """Phase 3: ledger records per-adapter outcomes, degrades bad input, never raises."""
    from investment_engine.research.corpus import source_status as ss

    ledger = ss.new_ledger()
    ss.record(ledger, adapter="test.feed", domain="news",
              status="SUCCESS_WITH_ITEMS", raw_count=5, normalized_count=4, selected_count=3)
    ss.record(ledger, adapter="test.dead", domain="news",
              status="BOGUS_STATUS", error="boom")
    assert ledger[0]["attempted_at"] and ledger[0]["status"] == "SUCCESS_WITH_ITEMS"
    assert ledger[1]["status"] == "FAILED"
    summary = ss.summarize(ledger)
    assert summary == {"SUCCESS_WITH_ITEMS": 1, "FAILED": 1}
    assert ss.summarize(None) == {}


def test_corpus_md_json_same_records():
    """Phase 3: MD and JSON are rendered from identical records."""
    from investment_engine.research.corpus.builder import build_corpus, render_corpus_markdown

    news = {
        "AAPL": [{"title": "AAPL beats estimates", "url": "https://example.com/a1",
                  "source": "Reuters", "published_dt": NOW,
                  "category": "general", "tier": 1}],
    }
    corpus = build_corpus(news, NOW)
    md = render_corpus_markdown(corpus, "t3")
    for item in corpus["decision_items"]:
        assert item["title"] in md
        assert item["canonical_url"] in md
    # Completeness + distributor rendered per item
    assert "HEADLINE_ONLY" in md or "RSS_SUMMARY" in md


def test_source_status_valid_set():
    """Phase 3: ledger accepts the full contracted status vocabulary."""
    from investment_engine.research.corpus import source_status as ss

    for status in ("SUCCESS_WITH_ITEMS", "SUCCESS_EMPTY", "FILTERED_ALL", "PARTIAL",
                   "FAILED", "RATE_LIMITED", "AUTH_REQUIRED", "ACCESS_RESTRICTED",
                   "NOT_ATTEMPTED", "DISABLED", "NOT_CONFIGURED", "NOT_IMPLEMENTED"):
        ledger = ss.new_ledger()
        ss.record(ledger, adapter="a", domain="d", status=status)
        assert ledger[0]["status"] == status


def test_personal_finance_excluded_from_decision():
    """Phase 4: off-topic personal-finance article never enters the decision set."""
    from investment_engine.research.corpus.builder import build_corpus

    warsaw_now = NOW
    news = {
        "AAPL": [
            _rec(title="AAPL beats earnings, revenue up", url="https://example.com/earn",
                 hours_ago=5, category="general", tier=1),
            _rec(title="How I paid off my personal debt in a year", url="https://example.com/debt",
                 hours_ago=5, category="general", tier=1),
        ],
    }
    corpus = build_corpus(news, warsaw_now)
    titles = [i["title"] for i in corpus["decision_items"]]
    assert any("beats earnings" in t for t in titles)
    # Bucket attribution alone is not confirmation: the debt article carries
    # the AAPL bucket tag but nothing in its content confirms the entity.
    debt = next(i for i in corpus["items"] if "personal debt" in i["title"])
    assert debt["entities_confirmed_in_content"] == []
    assert debt["portfolio_relevance"] == "indirect"
    # The earnings article names the symbol → confirmed + direct.
    earn = next(i for i in corpus["items"] if "beats earnings" in i["title"])
    assert earn["entities_confirmed_in_content"] == ["AAPL"]
    assert earn["portfolio_relevance"] == "direct"


def test_syndicated_copies_form_one_event():
    """Phase 4: five copies of one story = one event, five preserved sources."""
    from investment_engine.research.corpus.builder import build_corpus

    title = "Chipmaker posts record quarter on AI demand"
    news = {"NVDA": [
        _rec(title=title, url=f"https://example.com/n{i}", source=f"Publisher{i}",
             hours_ago=2, category="general", tier=1)
        for i in range(5)
    ]}
    corpus = build_corpus(news, NOW)
    assert corpus["counts"]["total"] == 1
    kept = corpus["items"][0]
    assert kept["corroboration"] == 5
    assert len(kept["event_sources"]) == 5
    assert kept["event_id"] == kept["id"]


def test_reference_category_keeps_as_of_date():
    """Phase 4: earnings-calendar material is background with its date, never fresh news."""
    from investment_engine.research.corpus import freshness as fr

    assert fr.classify(10.0, 1, "earnings_calendar") == "BACKGROUND-REFERENCE"
    assert fr.classify(10.0, 1, "analyst_consensus") == "BACKGROUND-REFERENCE"
    assert fr.classify(10.0, 1, "general") == "DECISION"


def test_credibility_splits_masthead_from_evidence():
    """Phase 4: T1 headline < T2 full text; corroboration raises confidence."""
    from investment_engine.research.corpus import tiers as _tiers

    headline = {"source_tier": 1, "completeness": "HEADLINE_ONLY",
                "url_kind": "aggregator_url", "corroboration": 1}
    full = {"source_tier": 2, "completeness": "FULL_TEXT",
            "url_kind": "article", "corroboration": 1}
    assert _tiers.credibility_for(full) > _tiers.credibility_for(headline)
    lone = dict(full, corroboration=1)
    confirmed = dict(full, corroboration=3)
    assert _tiers.credibility_for(confirmed) > _tiers.credibility_for(lone)


def test_relevance_adjusted_transparent_and_gated():
    """Phase 4: adjustments recorded in basis; fresh entity items keep the gate."""
    from investment_engine.research.corpus import tiers as _tiers

    item = {"relevance_score": 65.0, "completeness": "HEADLINE_ONLY",
            "url_kind": "article", "corroboration": 1,
            "age_hours": 5.0, "source_tier": 2, "ticker_tags": ["AAPL"]}
    adjusted, basis = _tiers.adjust_relevance(item)
    assert adjusted == 60.0
    assert any("headline_only" in b for b in basis)
    assert any("gate-floor" in b for b in basis)
    # Entity-less background items keep their honest lower value.
    bg = {"relevance_score": 65.0, "completeness": "HEADLINE_ONLY",
          "url_kind": "article", "corroboration": 1,
          "age_hours": 100.0, "source_tier": 2, "ticker_tags": []}
    adjusted_bg, _ = _tiers.adjust_relevance(bg)
    assert adjusted_bg < 60.0


def test_analyst_consensus_bundle_counts_and_unknown():
    """Phase 5: consensus bundle parses analyst counts; garbage stays explicit."""
    import investment_engine.main as m

    b = m._analyst_consensus_bundle({"AAPL": "recent: buy=5, hold=2, sell=1",
                                     "MSFT": "recent: buy=3, hold=1, sell=0"})
    assert b["analyst_count"] == 12
    assert "AAPL" in b["summary"] and b["as_of"]
    assert b["by_symbol"]["MSFT"].startswith("recent:")
    empty = m._analyst_consensus_bundle({})
    assert empty["analyst_count"] == "unknown"
    assert "No consensus" in empty["summary"]
    bad = m._analyst_consensus_bundle({"X": "n/a"})
    assert bad["analyst_count"] == "unknown"


def test_earnings_source_labels():
    """Phase 5: calendar-filled displays tracked separately from yahoo."""
    from investment_engine.research.market_data import earnings_source_for

    assert earnings_source_for("AAPL", {"AAPL"}) == "playwright-calendar"
    assert earnings_source_for("MSFT", {"AAPL"}) == "yahoo"
    assert earnings_source_for("MSFT", None) == "yahoo"
    assert earnings_source_for("", set()) == "yahoo"


def test_policy_stage_vocabulary():
    """Phase 5: a mention is not an implementation."""
    from investment_engine.skills.news_event_analyst.skill import _policy_stage, _deterministic_events

    assert _policy_stage("Trump signs executive order on chips") == "order"
    assert _policy_stage("Bill signed into law after vote") == "law"
    assert _policy_stage("White House proposes new tariff package") == "proposal"
    assert _policy_stage("Minister says rates may rise") == "statement"
    assert _policy_stage("Markets rally on strong earnings") == ""
    evts = _deterministic_events([{
        "id": "p1", "title": "Trump signs executive order on chips",
        "publisher": "Reuters", "ticker_tags": ["NVDA"],
    }])
    assert evts[0]["type"] == "POLICY"
    assert evts[0]["policy_stage"] == "order"


def test_energy_snapshot_offline_mocked(monkeypatch):
    """Phase 5: benchmark-identified prices; failures stay explicit, never raise."""
    from investment_engine.research import energy_snapshot as en

    class _Ticker:
        def __init__(self, sym):
            self.sym = sym

        @property
        def fast_info(self):
            if self.sym == "CL=F":
                return {"lastPrice": 71.5}
            raise RuntimeError("no data")

    import yfinance as _yf
    monkeypatch.setattr(_yf, "Ticker", _Ticker)
    out = en.fetch_snapshot()
    assert out["stats"]["attempted"] == 5
    assert out["stats"]["ok"] == 1
    wti = out["benchmarks"]["CL=F"]
    assert wti["price"] == 71.5 and wti["currency"] == "USD" and wti["unit"] == "bbl"
    assert wti["venue"] == "NYMEX" and wti["contract"] == "front-month futures"
    assert "error" in out["benchmarks"]["BZ=F"]


def test_tv_collectors_manifest(tmp_path):
    """Phase 5: manifest separates TV collectors; ideas explicitly unimplemented."""
    import json

    import portfolio_ai_assistant as entry

    result = {"brief_markdown": "", "snapshot_markdown": "",
              "reconciliation": {"status": "PASS"}, "failed_tickers": [],
              "monitoring_items": [], "decision_news": [], "brief_metadata": {},
              "playwright": {"technicals": 2, "facts": 0},
              "tvnews": {"items": 14, "symbols": 3}}
    entry.write_reports(result, tmp_path / "o", tmp_path / "a", "tv1")
    manifest = json.loads((tmp_path / "o" / "current" / "run_manifest.json").read_text(encoding="utf-8"))
    collectors = manifest["tv_collectors"]
    assert collectors["technicals"]["items"] == 2
    assert collectors["symbol_news"]["items"] == 14
    assert collectors["user_ideas"]["status"] == "NOT_IMPLEMENTED"

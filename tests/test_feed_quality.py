from __future__ import annotations

from datetime import datetime, timedelta, timezone

from investment_engine.research.news_engine import (
    NewsItem,
    _item_published_dt,
    _item_source,
    _item_title,
    _item_url,
    news_dedupe_key,
    score_feed_quality,
    source_tier,
)


def _item(title, source, url, age_h, base, now=None):
    ref = now or datetime.now(timezone.utc)
    dt = ref - timedelta(hours=age_h)
    return NewsItem(
        title=title, url=url, source=source, published_dt=dt,
        published_str=dt.date().isoformat(), relevance_score=base,
        content_hash="x", query="q",
    )


def test_tier_weight_boosts_tier0():
    now = datetime.now(timezone.utc)
    a = _item("Apple beats earnings", "Reuters", "https://reuters.com/a", 2, 40, now)
    score_feed_quality([a], now=now)
    assert a.relevance_score > 40


def test_freshness_decays():
    now = datetime.now(timezone.utc)
    fresh = _item("Apple beats earnings", "Reuters", "https://reuters.com/f", 1, 40, now)
    stale = _item("Apple beats earnings", "Reuters", "https://reuters.com/s", 40, 40, now)
    score_feed_quality([fresh, stale], now=now)
    assert fresh.relevance_score > stale.relevance_score


def test_corroboration_boost():
    now = datetime.now(timezone.utc)
    a = _item("Apple beats earnings", "Reuters", "https://reuters.com/a", 2, 40, now)
    b = _item("Apple beats earnings", "CNBC", "https://cnbc.com/a", 2, 40, now)
    before = a.relevance_score
    score_feed_quality([a, b], now=now)
    assert a.relevance_score > 40 and b.relevance_score > 40


def test_empty_list():
    assert score_feed_quality([]) == []


def test_score_capped_at_100():
    now = datetime.now(timezone.utc)
    a = _item("Apple beats earnings guidance upgrade", "Reuters", "https://reuters.com/a", 0, 100, now)
    score_feed_quality([a], now=now)
    assert a.relevance_score <= 100


def test_retry_on_429_then_success(monkeypatch):
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    from unittest.mock import MagicMock
    from investment_engine.research.news_engine import StrictNewsFetcher

    fetcher = StrictNewsFetcher(min_relevance=0, max_age_hours=48)
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "1"}
    resp_429.raise_for_status = lambda: None
    resp_429.content = b"<rss/>"
    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.headers = {}
    resp_ok.raise_for_status = lambda: None
    resp_ok.content = b"""<?xml version='1.0'?><rss><channel>
    <item><title>Apple beats earnings</title><link>https://x.com/a</link>
    <pubDate>Mon, 11 Nov 2026 10:00:00 GMT</pubDate><source>Reuters</source></item>
    </channel></rss>"""
    fetcher._session.get = MagicMock(side_effect=[resp_429, resp_ok])
    items = fetcher._fetch_google_news("Apple earnings")
def test_sorted_by_score_then_date():
    now = datetime.now(timezone.utc)
    low = _item("Apple misses", "Reuters", "https://reuters.com/low", 1, 10, now)
    high = _item("Apple beats earnings", "Reuters", "https://reuters.com/high", 5, 80, now)
    out = score_feed_quality([low, high], now=now)
    assert out[0] is high
    now = datetime.now(timezone.utc)
    low = _item("Apple misses", "Reuters", "https://reuters.com/low", 1, 10, now)
    high = _item("Apple beats earnings", "Reuters", "https://reuters.com/high", 5, 80, now)
    out = score_feed_quality([low, high], now=now)
    assert out[0] is high

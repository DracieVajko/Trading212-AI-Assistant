"""News fetch, source ledger, and social-news merging."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NewsPhase:
    """All news buckets plus the per-adapter source ledger."""

    news_by_symbol: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    all_news_items: list[Any] = field(default_factory=list)
    trump_tracking: dict[str, Any] = field(default_factory=dict)
    commodity_news: dict[str, Any] = field(default_factory=dict)
    analyst_news: dict[str, Any] = field(default_factory=dict)
    slovak_news: list[Any] = field(default_factory=list)
    reddit_news: list[Any] = field(default_factory=list)
    news_context_path: str | None = None
    source_ledger: list[dict[str, Any]] = field(default_factory=list)


def fetch_news_phase(
    *,
    settings_dict: dict[str, Any],
    all_active_assets: list[dict[str, Any]],
    portfolio_context: dict[str, Any],
) -> NewsPhase:
    """Fetch all news adapters and record collection status once."""
    from investment_engine.fetching import fetch_all_news_parallel

    result = fetch_all_news_parallel(
        settings_dict,
        all_active_assets,
        run_id=str(portfolio_context.get("run_id", "") or ""),
    )

    from investment_engine.research.corpus import source_status as srcstat

    source_ledger: list[dict[str, Any]] = srcstat.new_ledger()
    try:
        buckets = sum(1 for value in (result.news_by_symbol or {}).values() if value)
        srcstat.record(
            source_ledger,
            adapter="news_engine.strict_rss",
            domain="holdings_news",
            status="SUCCESS_WITH_ITEMS" if buckets else "SUCCESS_EMPTY",
            normalized_count=len(result.news_by_symbol or {}),
            selected_count=sum(len(v or []) for v in (result.news_by_symbol or {}).values()),
        )
        for name, bucket in (
            ("trump_policy", result.trump_tracking),
            ("commodities", result.commodity_news),
            ("analyst", result.analyst_news),
        ):
            count = (
                sum(len(v or []) for v in (bucket or {}).values())
                if isinstance(bucket, dict)
                else len(bucket or [])
            )
            srcstat.record(
                source_ledger,
                adapter="news_engine.enhanced",
                domain=name,
                status="SUCCESS_WITH_ITEMS" if count else "SUCCESS_EMPTY",
                normalized_count=len(bucket or {}) if isinstance(bucket, dict) else 0,
                selected_count=count,
            )
        srcstat.record(
            source_ledger,
            adapter="news_sources.slovak",
            domain="slovak_press",
            status="SUCCESS_WITH_ITEMS" if result.slovak_news else "SUCCESS_EMPTY",
            selected_count=len(result.slovak_news or []),
        )
        srcstat.record(
            source_ledger,
            adapter="news_engine.reddit",
            domain="social",
            status="SUCCESS_WITH_ITEMS" if result.reddit_news else "SUCCESS_EMPTY",
            selected_count=len(result.reddit_news or []),
        )
    except Exception as exc:
        logger.debug("Source ledger recording failed: %s", type(exc).__name__)

    for item in result.slovak_news:
        data = item.__dict__
        data.setdefault("category", "slovak")
        data.get("source", "Slovak")
        result.news_by_symbol.setdefault("SLOVAK", []).append(data)
        result.all_news_items.append(item)
    for item in result.reddit_news:
        data = item.__dict__
        data.setdefault("category", "reddit")
        data.get("source", "Reddit")
        result.news_by_symbol.setdefault("REDDIT", []).append(data)
        result.all_news_items.append(item)

    return NewsPhase(
        news_by_symbol=result.news_by_symbol,
        all_news_items=result.all_news_items,
        trump_tracking=result.trump_tracking,
        commodity_news=result.commodity_news,
        analyst_news=result.analyst_news,
        slovak_news=result.slovak_news,
        reddit_news=result.reddit_news,
        news_context_path=result.news_context_path,
        source_ledger=source_ledger,
    )

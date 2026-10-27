"""Phase 5 source adapters with failure isolation and compliance headers.

ACCESS ORDER (binding for every adapter in this package):
  1. documented official API or official feed,
  2. RSS / Atom,
  3. permitted public HTML (titles/extracts only, ToS-respecting),
  4. Playwright ONLY for dynamic pages, capped (max symbols, timeout,
     kill-switch), data-facts only,
  5. otherwise an explicit UNAVAILABLE / ACCESS_RESTRICTED record.
Playwright is never a universal fallback: it must not retry dead or
restricted pages across stages. Each adapter reports one status per run
(see corpus/source_status.py); a failure is recorded, never hidden.

COMPLIANCE SUMMARY (see docs/sources.md in a later docs pass):
- Google News RSS: unofficial but tolerated; headlines + links only, modest rate.
- Slovak press RSS (sme/pravda/aktuality): RSS extracts fine; HTML full-text
  only where the outlet ToS allow (current code uses titles/links only).
- Reddit public JSON: user-agent + rate limits, no auth circumvention; treat as
  LOW_CONFIDENCE sentiment, never standalone evidence.
- Finviz / TradingView / EarningsHub HTML: ToS-sensitive; Playwright stays
  opt-in, low frequency, data-facts only. Prefer official APIs/RSS.
- X / StockTwits: NO scraping in this codebase; flags without fetchers must be
  removed or wired to official channels (user decision pending).

An adapter NEVER raises: per-record failures yield FAILED items, a dead source
yields a single FAILED placeholder, the run always continues.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# Bucket names that are collection contexts, NOT entities. They must never
# appear in `ticker_tags` — the bucket is recorded in `queried_for` instead.
# (Run evidence: RSS_FALLBACK/SLOVAK/REDDIT buckets polluted ticker_tags.)
_NON_ENTITY_BUCKETS = frozenset({
    "RSS_FALLBACK", "RSS", "FALLBACK",
    "SLOVAK", "REDDIT",
    "SPY", "BTC", "TRUMP",
    "CRYPTO-MACRO", "MACRO", "GENERAL",
})


def is_entity_bucket(symbol_key: str) -> bool:
    """True when a corpus bucket key names an instrument (else a context)."""
    key = str(symbol_key or "").strip().upper()
    if not key or key in _NON_ENTITY_BUCKETS:
        return False
    return True


def _clean(text: Any, limit: int = 600) -> str:
    import re

    out = re.sub(r"\s+", " ", str(text or "")).strip()
    out = re.sub(r"(?i)^(breaking|exclusive|just in|watch|live blogs?)\s*[:|-]\s*", "", out)
    return out[:limit]


def failed_item(source: str, reason: str, category: str = "general") -> dict[str, Any]:
    return {
        "id": f"failed-{abs(hash(source + reason)) % 10**8:08d}",
        "title": f"Source unavailable: {source}",
        "canonical_url": "https://localhost/unavailable",
        "publisher": source,
        "published_at_utc": "",
        "age_hours": None,
        "source_tier": 3,
        "source_category": category,
        "ticker_tags": [],
        "sector_tags": [],
        "region_tags": [],
        "clean_extract": "",
        "raw_extract_if_available": "",
        "credibility": 0.0,
        "relevance_score": 0.0,
        "sentiment_if_available": None,
        "fetch_status": "FAILED",
        "failure_reason_if_any": str(reason)[:200],
        "url_kind": "unavailable",
        "collection_method": "",
        "adapter_id": "corpus.adapters",
        "query_id": str(source or ""),
        "queried_for": "",
        "entities_confirmed_in_content": [],
        "portfolio_relevance": "unconfirmed",
        "distributor": "",
        "completeness": "UNKNOWN",
    }


def _record_to_item(record: dict[str, Any], symbol_key: str, now: datetime,
                    names_map: dict[str, str] | None = None,
                    universe_symbols: set | None = None) -> dict[str, Any]:
    """Convert a Strict/Enhanced-style record dict to a normalized item dict.

    ``names_map`` + ``universe_symbols`` enable conservative company-name
    confirmation (WP2). When absent, only the queried symbol is confirmed.
    """
    from investment_engine.research.corpus import dedupe as _dedupe
    from investment_engine.research.corpus import freshness as _fresh
    from investment_engine.research.corpus import sector_map as _sector_map
    from investment_engine.research.corpus import tiers as _tiers

    title = str(record.get("title", "") or "").strip()
    url = str(record.get("url", "") or "").strip()
    if not title or not url:
        # A decision-relevant item MUST have title + URL; without either the
        # record can only exist as an explicitly rejected FAILED item.
        bad = dict(failed_item(str(symbol_key or "unknown"),
                               "missing title or URL", "general"))
        bad["title"] = title or bad["title"]
        return bad
    source = str(record.get("source", "unknown") or "unknown").strip()
    # TradingView acts as distributor when the origin publisher is embedded
    # as "TradingView/<origin>" — split them, never flatten to one tier.
    distributor = ""
    if source.lower().startswith("tradingview/"):
        distributor = "TradingView"
        source = source.split("/", 1)[1].strip() or "TradingView"
    category = str(record.get("category", "general") or "general").strip().lower()
    pub = record.get("published_dt", record.get("published"))
    undated = bool(record.get("undated")) or pub is None
    host = url.lower()
    url_kind = ("aggregator_url" if ("news.google.com" in host or "news.search.yahoo" in host)
                else "article")
    try:
        tier = int(record.get("tier", record.get("source_tier", _tiers.tier_for_category(category))))
        tier = max(0, min(3, tier))
    except (TypeError, ValueError):
        tier = _tiers.tier_for_category(category)
    if category in _tiers.SOCIAL_CATEGORIES:
        tier = 3
    try:
        relevance = float(record.get("relevance_score", record.get("score", 0)) or 0)
    except (TypeError, ValueError):
        relevance = 0.0
    preview = str(record.get("preview", record.get("content", record.get("summary", ""))) or "")
    if undated:
        status, age_h, published_iso = "UNDATED", None, ""
    else:
        age_h = _fresh.age_hours(pub, now)
        if age_h is None:
            status, published_iso = "UNDATED", ""
        else:
            from investment_engine.schemas.research_item import parse_utc

            dt = parse_utc(pub)
            published_iso = dt.isoformat() if dt else ""
            status = "OK"
    credibility = {0: 95.0, 1: 80.0, 2: 60.0, 3: 25.0}.get(tier, 25.0)
    clean = _clean(preview or title)
    sector_tags, region_tags = _sector_map.tags_for(title, clean)
    # Phase 2 identity rule: bucket names are collection context, not entities.
    entity = is_entity_bucket(symbol_key)
    # Content confirmation (WP2): the bucket symbol as a whole word, plus
    # conservative company-name confirmation when a names map is provided.
    confirmed: list[str] = []
    if entity:
        from investment_engine.portfolio.symbols import confirm_content_entities
        confirmed, _rel = confirm_content_entities(
            title, clean, symbol_key, names_map, universe_symbols)
    return {
        "id": _dedupe.item_id(url),
        "title": title,
        "canonical_url": _dedupe.normalize_url(url),
        "url_kind": url_kind,
        "publisher": source,
        "published_at_utc": published_iso,
        "age_hours": age_h,
        "source_tier": tier,
        "source_category": category,
        "ticker_tags": [str(symbol_key).strip().upper()] if (symbol_key and entity) else [],
        "sector_tags": sector_tags,
        "region_tags": region_tags,
        "clean_extract": clean,
        "raw_extract_if_available": preview[:1200],
        "credibility": credibility,
        "relevance_score": relevance,
        "sentiment_if_available": None,
        "fetch_status": status,
        "failure_reason_if_any": "",
        "collection_method": "rss" if url_kind == "aggregator_url" else "feed",
        "adapter_id": "corpus.adapters",
        "query_id": str(symbol_key or ""),
        "queried_for": str(symbol_key or ""),
        "entities_confirmed_in_content": confirmed,
        "portfolio_relevance": "direct" if (entity and confirmed) else ("indirect" if entity else "unconfirmed"),
        "distributor": distributor,
        "completeness": "RSS_SUMMARY" if clean and clean != title else "HEADLINE_ONLY",
    }


def adapt_symbol_records(symbol_key: str, records: list[dict[str, Any]],
                         source_label: str, now: datetime,
                         names_map: dict[str, str] | None = None,
                         universe_symbols: set | None = None) -> list[dict[str, Any]]:
    """Adapt one symbol bucket. Never raises: failures become FAILED items."""
    try:
        items = [_record_to_item(r, symbol_key, now, names_map, universe_symbols)
                 for r in (records or []) if isinstance(r, dict)]
        return [i for i in items if i.get("title")]
    except Exception as exc:
        logger.debug("Corpus adapter failed for %s: %s", source_label, type(exc).__name__)
        return [failed_item(source_label, f"{type(exc).__name__}", "general")]

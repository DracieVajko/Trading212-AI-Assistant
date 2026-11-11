"""Data fetching helpers (T212, news, regime snapshots).

Extracted from ``main.py`` so the orchestrator and phase modules depend on a
focused fetch layer instead of a single utility hub.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from investment_engine.research.news_engine import NewsItem, StrictNewsFetcher
from investment_engine.research.news_sources import (
    EnhancedNewsFetcher,
    NewsContextBuilder,
)
from investment_engine.schemas.context import T212Snapshot

logger = logging.getLogger(__name__)

def _symbol(asset: dict[str, Any]) -> str:
    return str(asset.get("broker_symbol") or asset.get("yahoo_symbol") or asset.get("name") or "UNKNOWN")


def _fetch_t212_data(settings_dict: dict) -> T212Snapshot | None:
    """Fetch Trading212 portfolio data if enabled, with graceful degradation.

    ``settings_dict["t212_snapshot_override"]`` short-circuits the fetch. Branch
    runs use it to push their own environment's snapshot (demo or live) through
    the same pipeline without re-fetching the live account.
    """
    override = settings_dict.get("t212_snapshot_override")
    if isinstance(override, dict) and override.get("status"):
        logger.info("T212 snapshot override in use (status=%s)", override.get("status"))
        return override
    if not settings_dict.get("use_trading212_api", True):
        return None
    try:
        import time
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FuturesTimeoutError

        from trading212.integration import create_integration
        
        logger.info("Fetching T212 account summary...")
        t212 = create_integration(config_file="api.env")
        if not t212:
            logger.warning("T212 not configured")
            return {"status": "failed", "error": "T212 not configured"}
        
        logger.debug("T212 integration created, calling get_account_summary...")
        # Single call to get_account_summary gets everything (cash + positions)
        # Increased timeout to 120s + retry for transient network issues
        max_attempts = 3
        summary = None
        for attempt in range(1, max_attempts + 1):
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(t212.get_account_summary)
                    summary = future.result(timeout=120)
                break
            except FuturesTimeoutError:
                if attempt < max_attempts:
                    logger.warning("T212 summary timeout (attempt %d/%d), retrying in %.0fs...",
                                   attempt, max_attempts, 5.0)
                    time.sleep(5.0)
                else:
                    logger.error("T212 summary timeout after %d attempts", max_attempts)
                    return {"status": "failed", "error": "T212 summary timeout"}
            except Exception as exc:
                if attempt < max_attempts:
                    logger.warning("T212 summary error (attempt %d/%d): %s. Retrying in %.0fs...",
                                   attempt, max_attempts, exc, 5.0)
                    time.sleep(5.0)
                else:
                    logger.error("T212 summary failed after %d attempts: %s", max_attempts, exc)
                    return {"status": "failed", "error": f"T212 summary failed: {exc}"}
        
        logger.info(f"T212 summary received: status={summary.get('status')}, keys={list(summary.keys()) if isinstance(summary, dict) else 'N/A'}")
        
        if summary.get("status") == "failed":
            logger.warning(f"T212 summary failed: {summary.get('error')}")
            return {"status": "failed", "error": summary.get("error")}
        
        logger.debug(f"T212 summary: total_equity={summary.get('total_equity')}, cash_free={summary.get('cash_free')}, positions={len(summary.get('positions', []))}, all_positions={len(summary.get('all_positions', []))}")

        # Extract everything from single response. `all_positions` is the
        # authoritative broker snapshot; `positions` is the non-pie subset view.
        return {
            "status": "ok",
            "account_summary": summary,
            "positions": summary.get("positions", []),
            "all_positions": summary.get("all_positions", []),
            "cash": {
                "free": summary.get("cash_free", 0),
                "invested": summary.get("invested", 0),
                "pie_cash": summary.get("cash_pie", 0),
                "total": summary.get("total_equity", 0),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"T212 fetch failed: {e}")
        return {"status": "failed", "error": str(e)}


@dataclass
class NewsFetchResult:
    """Named result of one parallel news fetch (replaces positional 8-tuple)."""

    news_by_symbol: dict
    all_news_items: list[NewsItem]
    trump_tracking: dict
    commodity_news: dict
    analyst_news: dict
    slovak_news: dict
    reddit_news: dict
    news_context_path: str | None


def _fetch_all_news_parallel(settings_dict: dict, assets: list[dict[str, Any]], max_workers: int = 8, run_id: str = "") -> NewsFetchResult:
    """Fetch news for assets in parallel - all enabled assets, not just top 10.

    Returns a NewsFetchResult with named fields so callers never unpack a
    positional tuple whose ordering can silently drift.

    Results are cached for the life of the process: the live and demo branches
    of one run analyse the same asset universe, so the second branch reuses the
    corpus instead of hammering the news sources again.
    """
    cache_key = _news_cache_key(settings_dict, assets)
    cached = _NEWS_CACHE.get(cache_key)
    if cached is not None:
        logger.info("News corpus reused from this process (shared across branches)")
        return cached

    result = _fetch_all_news_uncached(settings_dict, assets, max_workers=max_workers, run_id=run_id)
    _NEWS_CACHE[cache_key] = result
    return result


_NEWS_CACHE: dict[str, NewsFetchResult] = {}


def reset_news_cache() -> None:
    """Drop the process-level news cache (tests and forced refreshes)."""
    _NEWS_CACHE.clear()


def _news_cache_key(settings_dict: dict, assets: list[dict[str, Any]]) -> str:
    symbols = sorted(
        str(a.get("yahoo_symbol") or a.get("name") or "")
        for a in (assets or [])
        if isinstance(a, dict)
    )
    mr_news = (settings_dict.get("market_regime") or {}).get("news") or {}
    return "|".join(
        [
            f"{datetime.now(timezone.utc).date().isoformat()}",
            str(mr_news.get("max_age_hours", 48)),
            str(mr_news.get("min_relevance_score", 30)),
            ",".join(symbols),
        ]
    )


def _fetch_all_news_uncached(settings_dict: dict, assets: list[dict[str, Any]], max_workers: int = 8, run_id: str = "") -> NewsFetchResult:
    mr_news = settings_dict.get("market_regime", {}).get("news", {})
    fetcher = StrictNewsFetcher(
        max_age_hours=mr_news.get("max_age_hours", 48),
        min_relevance=mr_news.get("min_relevance_score", 30),
    )

    # Extended fetcher for Slovak, Reddit, and enhanced sources
    enhanced_fetcher = EnhancedNewsFetcher(
        max_age_hours=mr_news.get("max_age_hours", 48),
        enable_slovak=bool(settings_dict.get("enable_slovak_news", False)),
        enable_reddit=True,
    )

    # Fetch for ALL enabled assets (not just top 10)
    priority_assets = [a for a in assets if a.get("enabled", True)]

    def fetch_one(asset):
        sym = _symbol(asset)
        name = asset.get("name", sym)
        items = fetcher.fetch_for_symbol(
            sym, name,
            limit=mr_news.get("max_articles_per_symbol", 5)
        )
        return sym, [item.__dict__ for item in items], items

    news_by_symbol: dict[str, list[dict]] = {}
    all_news_items: list[NewsItem] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, asset): asset for asset in priority_assets}
        for future in as_completed(futures):
            try:
                sym, items_dict, items_obj = future.result(timeout=15)
                if items_dict:
                    news_by_symbol[sym] = items_dict
                    all_news_items.extend(items_obj)
            except Exception as e:
                asset = futures[future]
                logger.warning("News fetch failed for %s: %s",
                               asset.get('name', 'unknown'), e)

    # Fetch macro news (SPY, BTC) + Trump policy watch in parallel
    macro_queries = {
        "SPY": ("S&P 500", 3, None),
        "BTC": ("Bitcoin", 2, None),
        "TRUMP": ("Trump", 5, ["Trump tariffs trade policy", "Trump economy markets", "Trump regulation stocks"]),
    }
    with ThreadPoolExecutor(max_workers=3) as executor:
        macro_futures = {
            executor.submit(fetcher.fetch_for_symbol, sym, name, limit, extra): label
            for sym, (name, limit, extra) in macro_queries.items()
            for label in [sym]
        }
        for future in as_completed(macro_futures):
            try:
                label = macro_futures[future]
                items = future.result(timeout=15)
                if items:
                    news_by_symbol[label] = [item.__dict__ for item in items]
            except Exception:
                pass

    # Fetch Slovak news (sme.sk, pravda.sk, aktuality.sk)
    symbols_list = [a.get("symbol", "") for a in priority_assets if a.get("symbol")]
    companies_list = [a.get("name", "") for a in priority_assets if a.get("name")]
    slovak_news = fetcher.fetch_slovak_news(symbols=symbols_list, companies=companies_list)

    # Fetch Reddit discussions
    reddit_queries = [f"{a.get('name', a.get('symbol', ''))} stock news" for a in priority_assets[:5]]
    reddit_news = fetcher.fetch_reddit_search(reddit_queries, limit_per_query=5)

    # Fetch Trump tracking with categorized keywords
    trump_tracking = fetcher.fetch_trump_tracking()

    # Fetch commodity and crypto news (gold, silver, lithium, uranium, BTC, ETH)
    commodity_targets = ["gold", "silver", "lithium", "uranium", "BTC", "ETH", "SOL"]
    commodity_news = enhanced_fetcher.fetch_commodity_news(fetcher, commodities=commodity_targets)

    # Fetch analyst recommendations
    analyst_news = enhanced_fetcher.fetch_analyst_recommendations(fetcher, priority_assets)

    # Verified RSS fallbacks (Yahoo/CNBC/MarketWatch): additive market bucket so
    # a thin Google-RSS day still leaves a usable corpus. Keyword-filtered,
    # capped, tier-labelled; failures degrade silently per adapter contract.
    try:
        _fallback_terms = [str(a.get("name") or a.get("symbol") or "").split()[0]
                           for a in priority_assets[:15]]
        _fallback_terms += ["stock market", "earnings", "S&P 500"]
        _rss_items = enhanced_fetcher.fetch_rss_fallbacks(_fallback_terms, limit_total=12)
        if _rss_items:
            news_by_symbol.setdefault("RSS_FALLBACK", []).extend(_rss_items)
    except Exception as exc:
        logger.debug("RSS fallback fetch skipped: %s", type(exc).__name__)

    # Generate news context .md file for AI (ai_context layer, single home).
    # run_id comes from the caller (wrapper run_id via portfolio_context) —
    # settings_dict never carries it, which used to leave "Run ID:" blank.
    news_context_path = None
    try:
        output_dir = str(Path(settings_dict.get("output_folder", "reports")) / "ai_context")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        ctx_builder = NewsContextBuilder()
        news_context_path = ctx_builder.build_news_context_file(
            news_by_symbol=news_by_symbol,
            output_dir=output_dir,
            run_id=run_id or settings_dict.get("run_id", ""),
            trump_tracking=trump_tracking,
            commodity_news=commodity_news,
            analyst_news=analyst_news,
            slovak_news=slovak_news,
            reddit_news=reddit_news,
        )
    except Exception as exc:
        logger.debug("News context file generation failed: %s", exc)

    return NewsFetchResult(
        news_by_symbol=news_by_symbol,
        all_news_items=all_news_items,
        trump_tracking=trump_tracking,
        commodity_news=commodity_news,
        analyst_news=analyst_news,
        slovak_news=slovak_news,
        reddit_news=reddit_news,
        news_context_path=news_context_path,
    )


def _yahoo_symbol(asset: dict[str, Any]) -> str:
    """Get the Yahoo Finance symbol for market data lookups."""
    return str(asset.get("yahoo_symbol") or asset.get("broker_symbol") or asset.get("name") or "UNKNOWN")


def _fetch_finviz_safe(symbol: str) -> dict:
    """Safe FinViz fetch — disabled gracefully when incompatible/unavailable.

    FinViz covers US listings only; anything else returns {} without a call.
    Import paths are probed defensively so an installed-library API change
    degrades to {} (logged at debug) instead of raising.
    """
    if not symbol or not _is_us_symbol(symbol):
        return {}
    try:
        from finvizfinance.quote import finvizfinance
        stock = finvizfinance(symbol)
        fund = stock.ticker_fundament()
        if fund is None or (hasattr(fund, "empty") and fund.empty):
            return {}
    except Exception as exc:
        logger.debug("FinViz quote unavailable for %s: %s", symbol, exc)
        return {}

    breadth = {}
    try:
        from finvizfinance.group.overview import Overview as FinvizGroupOverview
        try:
            from investment_engine.research.technical_analysis import (
                group_sector_breadth_from_table as _parse_group_table,
            )
        except Exception:
            _parse_group_table = None
        go = FinvizGroupOverview()
        # Group endpoint has no set_filter (AttributeError in run 524fffa0):
        # one call returns the whole sector-aggregate table.
        df = go.screener_view(group="Sector", order="Name")
        if _parse_group_table is not None:
            breadth = _parse_group_table(df) or {}
    except Exception as exc:
        logger.debug("FinViz group overview unavailable: %s", exc)

    result: dict = {"fundamentals": fund}
    if breadth:
        result["sector_breadth"] = breadth
    return result


def _is_us_symbol(symbol: str) -> bool:
    """Check if symbol is likely US-listed (for FinViz compatibility)."""
    non_us_suffixes = ('.DE', '.L', '.F', '.CO', '.KS', '.AS', '.SW', '.MI', '.PA', '.BR', '.OL', '.HE', '.VI', '.ST', '.CO', '.IC')
    return not any(symbol.endswith(suf) for suf in non_us_suffixes)


def _load_symbol_aliases(portfolio_context: dict[str, Any] | None) -> dict[str, str]:
    """Load T212 -> Yahoo symbol aliases from the JSON config (symbol_aliases)."""
    try:
        cfg_path = (portfolio_context or {}).get("config_path")
        if not cfg_path:
            return {}
        import json as _json
        cfg = _json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        aliases = cfg.get("symbol_aliases", {}) or {}
        return {str(k).strip().upper(): str(v).strip() for k, v in aliases.items() if v}
    except Exception:
        return {}


def _t212_yahoo_symbol(t212_symbol: str, aliases: dict[str, str]) -> str | None:
    """Map a Trading212 internal ID to a Yahoo Finance ticker (or None).

    Single mapping layer (see investment_engine.portfolio.symbols). Never
    returns company names. Kept for backward compatibility.
    """
    try:
        from investment_engine.portfolio.symbols import (
            to_display_symbol,
            to_yahoo_symbol,
        )
        disp = to_display_symbol(t212_symbol)
        return to_yahoo_symbol(t212_symbol, disp, aliases)
    except Exception:
        return None


def _build_regime_context(regime_result) -> str:
    """Build concise regime context for AI prompts."""
    if not regime_result:
        return "Regime analysis unavailable"
    impl = regime_result.implications
    return (
        f"EXI2 Regime: {regime_result.regime} ({regime_result.confidence:.0%} confidence)\n"
        f"Current Price: €{regime_result.timeframes.get('daily', {}).get('indicators', {}).get('CLOSE', 0):.2f}\n"
        f"RSI Daily: {regime_result.timeframes.get('daily', {}).get('indicators', {}).get('RSI_14', 0):.1f} | "
        f"RSI Weekly: {regime_result.timeframes.get('weekly', {}).get('indicators', {}).get('RSI_14', 0):.1f}\n"
        f"Trend Daily: {regime_result.timeframes.get('daily', {}).get('trend', 'UNKNOWN')} | "
        f"Trend Weekly: {regime_result.timeframes.get('weekly', {}).get('trend', 'UNKNOWN')}\n"
        f"Portfolio Action: {impl.get('portfolio_action', 'UNKNOWN')}\n"
        f"Tech Allocation: {impl.get('tech_allocation', 'NORMAL_DCA')}\n"
        f"Crypto Allocation: {impl.get('crypto_allocation', 'NORMAL_DCA')}\n"
        f"DCA Multiplier: {impl.get('dca_multiplier', 1.0)}x\n"
        f"Cash Target: {impl.get('cash_target_pct', 10)}%\n"
        f"Guidance: {impl.get('message', '')}\n"
        f"Warnings: {'; '.join(regime_result.warnings) if regime_result.warnings else 'None'}"
    )

# Public aliases for cross-module use (private names remain the
# implementation detail and stay available for in-module calls).
symbol = _symbol
fetch_t212_data = _fetch_t212_data
fetch_all_news_parallel = _fetch_all_news_parallel
yahoo_symbol = _yahoo_symbol
fetch_finviz_safe = _fetch_finviz_safe
is_us_symbol = _is_us_symbol
load_symbol_aliases = _load_symbol_aliases
t212_yahoo_symbol = _t212_yahoo_symbol
build_regime_context = _build_regime_context

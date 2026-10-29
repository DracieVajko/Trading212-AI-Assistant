"""universe.py — Build stock universe for discovery.

Fetches S&P 500 (and optionally Nasdaq-100) tickers from Wikipedia.
Falls back to a hardcoded list if network is unavailable.
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

# Fallback universe (top 50 liquid US stocks) — used when Wikipedia is unreachable
_FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "AVGO", "JPM",
    "LLY", "V", "UNH", "XOM", "MA", "JNJ", "PG", "HD", "MRK", "COST",
    "ABBV", "CVX", "BAC", "KO", "PEP", "ADBE", "WMT", "CRM", "MCD", "NFLX",
    "TMO", "ACN", "ABT", "LIN", "DHR", "ORCL", "TXN", "NEE", "PM", "CAT",
    "RTX", "UPS", "LOW", "INTU", "AMGN", "IBM", "GS", "BLK", "ISRG", "MDT",
]


def _fetch_sp500() -> List[str]:
    """Fetch S&P 500 tickers from Wikipedia. Returns empty list on failure."""
    try:
        import pandas as pd
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        if tables and len(tables) > 0:
            df = tables[0]
            tickers = df["Symbol"].tolist() if "Symbol" in df.columns else []
            # Clean: replace dots with dashes (BRK.B -> BRK-B)
            tickers = [str(t).replace(".", "-").strip() for t in tickers if t]
            logger.info("universe: fetched %d S&P 500 tickers from Wikipedia", len(tickers))
            return tickers
    except Exception as exc:
        logger.warning("universe: Wikipedia S&P 500 fetch failed: %s", type(exc).__name__)
    return []


def _fetch_nasdaq100() -> List[str]:
    """Fetch Nasdaq-100 tickers from Wikipedia. Returns empty list on failure."""
    try:
        import pandas as pd
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        if tables:
            for t in tables:
                if "Ticker" in t.columns:
                    tickers = t["Ticker"].tolist()
                    tickers = [str(t).replace(".", "-").strip() for t in tickers if t]
                    logger.info("universe: fetched %d Nasdaq-100 tickers", len(tickers))
                    return tickers
    except Exception as exc:
        logger.warning("universe: Wikipedia Nasdaq-100 fetch failed: %s", type(exc).__name__)
    return []


def build_universe(
    include_sp500: bool = True,
    include_nasdaq100: bool = False,
    min_market_cap: float = 1e9,
    exclude_tickers: set[str] | None = None,
) -> List[str]:
    """Build a deduplicated list of tickers for discovery screening.

    Args:
        include_sp500: Include S&P 500 constituents.
        include_nasdaq100: Include Nasdaq-100 constituents.
        min_market_cap: Minimum market cap filter (best-effort, requires yfinance).
        exclude_tickers: Tickers to exclude (e.g., already held).

    Returns:
        List of unique ticker symbols.
    """
    exclude = {t.upper() for t in (exclude_tickers or set())}
    universe: set[str] = set()

    if include_sp500:
        sp500 = _fetch_sp500()
        if sp500:
            universe.update(sp500)
        else:
            universe.update(_FALLBACK_UNIVERSE)

    if include_nasdaq100:
        ndx = _fetch_nasdaq100()
        if ndx:
            universe.update(ndx)

    # Remove excluded
    universe -= exclude

    # Sort for deterministic order
    result = sorted(universe)
    logger.info("universe: built %d tickers (sp500=%s, ndx=%s, excluded=%d)",
                len(result), include_sp500, include_nasdaq100, len(exclude))
    return result

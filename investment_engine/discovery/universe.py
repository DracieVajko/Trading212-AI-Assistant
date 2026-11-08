"""universe.py — Build stock universe for discovery.

Fetches S&P 500 (and optionally Nasdaq-100) tickers from Wikipedia.
Falls back to a hardcoded list if network is unavailable.
"""

from __future__ import annotations

import logging
from typing import List, Set

logger = logging.getLogger(__name__)

# Fallback universe (top 50 liquid US stocks) — used when Wikipedia is unreachable
_FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "AVGO", "JPM",
    "LLY", "V", "UNH", "XOM", "MA", "JNJ", "PG", "HD", "MRK", "COST",
    "ABBV", "CVX", "BAC", "KO", "PEP", "ADBE", "WMT", "CRM", "MCD", "NFLX",
    "TMO", "ACN", "ABT", "LIN", "DHR", "ORCL", "TXN", "NEE", "PM", "CAT",
    "RTX", "UPS", "LOW", "INTU", "AMGN", "IBM", "GS", "BLK", "ISRG", "MDT",
]

# EU stocks (liquid EU listings) — for international diversification
_EU_UNIVERSE = [
    "EXI2.DE", "VWCE.DE", "VWS.CO", "IBE.MC", "RWE.DE", "ENR.DE", "LOM.DE", "SAP.DE",
    "ASML.AS", "MC.PA", "TTE.PA", "SIE.DE", "AIR.PA", "BNP.PA", "ADYEN.AS", "DSY.PA",
    "RI.PA", "SU.PA", "OR.PA", "SAF.PA", "VIV.PA", "ORANGE.PA", "DG.PA", "CAP.PA",
    "UG.PA", "RMS.PA", "KER.PA", "STLA.PA", "VIV.PA", "MGGT.L", "HSBA.L", "HSBA.L",
    "BP.L", "AZN.L", "GSK.L", "VOD.L", "BT-A.L", "VOD.L", "TSCO.L", "SGE.L",
    "BARC.L", "LSEG.L", "HSBA.L", "UBSG.SW", "ZURN.SW", "NESN.SW", "ROG.SW",
    "NOVN.SW", "LONN.SW", "UBSG.SW", "ZURN.SW", "ADEN.SW", "SWX.SW",
]

# EU/China ETFs and major international ETFs
_ETF_UNIVERSE = [
    "VWCE.DE", "IWDA.L", "VUAA.L", "VUSA.L", "VUAG.L", "EQQQ.L", "VUAG.L",
    "CSPX.L", "VUAG.L", "VUSA.L", "VUAG.L", "EQQQ.L", "VWRA.L", "VWRL.L",
    "VWRA.L", "VWRL.L", "IWDA.L", "EIMI.L", "VUAG.L", "VUSA.L", "VUAG.L",
    "IWDA.L", "VWRA.L", "VWRL.L",
]

# Chinese stocks (liquid US/EU listings)
_CHINA_UNIVERSE = [
    "BABA", "JD", "PDD", "NIO", "BIDU", "TCEHY", "0700.HK", "9988.HK",
    "3690.HK", "2318.HK", "1398.HK", "2318.HK", "939.HK", "1398.HK",
    "0700.HK", "9988.HK", "3690.HK", "2318.HK", "1398.HK", "939.HK",
]


def _fetch_sp500() -> list[str]:
    """Fetch S&P 500 tickers from Wikipedia. Returns empty list on failure."""
    try:
        import io
        import pandas as pd
        import requests
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioAI/1.0)"}
        html = requests.get(url, headers=headers, timeout=20).text
        tables = pd.read_html(io.StringIO(html))
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


def _fetch_nasdaq100() -> list[str]:
    """Fetch Nasdaq-100 tickers from Wikipedia. Returns empty list on failure."""
    try:
        import io
        import pandas as pd
        import requests
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioAI/1.0)"}
        html = requests.get(url, headers=headers, timeout=20).text
        tables = pd.read_html(io.StringIO(html))
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
    include_eu: bool = True,
    include_china: bool = True,
    include_etfs: bool = True,
    min_market_cap: float = 1e9,
    exclude_tickers: set[str] | None = None,
) -> list[str]:
    """Build a deduplicated list of tickers for discovery screening.

    Args:
        include_sp500: Include S&P 500 constituents.
        include_nasdaq100: Include Nasdaq-100 constituents.
        include_eu: Include EU stocks (Germany, France, Spain, etc.).
        include_china: Include Chinese stocks (US/EU listings).
        include_etfs: Include major ETFs (VWCE, SPY, QQQ, etc.).
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

    if include_eu:
        universe.update(_EU_UNIVERSE)

    if include_china:
        universe.update(_CHINA_UNIVERSE)

    if include_etfs:
        universe.update(_ETF_UNIVERSE)

    # Remove excluded
    universe -= exclude

    # Sort for deterministic order
    result = sorted(universe)
    logger.info(
        "universe: built %d tickers (sp500=%s, ndx=%s, eu=%s, china=%s, etfs=%s, excluded=%d)",
        len(result), include_sp500, include_nasdaq100, include_eu, include_china,
        include_etfs, len(exclude),
    )
    return result

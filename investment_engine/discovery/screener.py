"""screener.py — Technical screening orchestrator for Discovery Engine.

Wraps discovery.py and signals_ext.py into a single callable that:
1. Builds universe
2. Fetches price data (yfinance)
3. Scores each ticker (technical + fundamental + external)
4. Returns ranked candidates
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _yf_loader(ticker: str):
    """Fetch daily OHLCV + info from yfinance."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    daily = t.history(period="1y", auto_adjust=True)
    info = t.info or {}
    return daily, info


def run_screener(
    universe: List[str],
    index_daily: pd.DataFrame | None = None,
    loader=None,
    ext: dict | None = None,
    cfg: dict | None = None,
    held: set[str] | None = None,
    max_candidates: int = 20,
) -> pd.DataFrame:
    """Run discovery screening on a universe of tickers.

    Args:
        universe: List of ticker symbols.
        index_daily: Daily OHLCV for market index (SPY). If None, fetched.
        loader: Function (ticker) -> (daily_df, info_dict). Defaults to yfinance.
        ext: External signals dict (from trackers). Defaults to empty.
        cfg: Discovery config. Defaults to DEFAULT_CONFIG.
        held: Set of held tickers (uppercase).
        max_candidates: Max candidates to return.

    Returns:
        DataFrame sorted by status/score, with columns:
        ticker, status, score, base, ext, components, reasons, flags, held
    """
    if loader is None:
        loader = _yf_loader

    if index_daily is None:
        try:
            import yfinance as yf
            index_daily = yf.download("SPY", period="1y", progress=False, auto_adjust=True)
            if isinstance(index_daily.columns, pd.MultiIndex):
                index_daily = index_daily.droplevel(1, axis=1)
        except Exception as exc:
            logger.warning("screener: could not fetch SPY index: %s", type(exc).__name__)
            index_daily = pd.DataFrame()

    if cfg is None:
        from .discovery import DEFAULT_CONFIG
        cfg = DEFAULT_CONFIG

    if held is None:
        held = set()

    # Import discovery module
    from .discovery import run_discovery

    try:
        result_df = run_discovery(
            universe=universe,
            index_daily=index_daily,
            loader=loader,
            ext=ext or {},
            cfg=cfg,
            held=held,
        )
    except Exception as exc:
        logger.error("screener: run_discovery failed: %s", type(exc).__name__)
        return pd.DataFrame()

    # Filter to candidates and watch only
    if "status" in result_df.columns:
        candidates = result_df[result_df["status"].isin(["CANDIDATE", "WATCH"])]
    else:
        candidates = result_df

    # Limit
    if len(candidates) > max_candidates:
        candidates = candidates.head(max_candidates)

    logger.info("screener: %d candidates from %d universe tickers", len(candidates), len(universe))
    return candidates.reset_index(drop=True)

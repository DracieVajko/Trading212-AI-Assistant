"""screener.py — Technical screening orchestrator for Discovery Engine.

Wraps discovery.py and signals_ext.py into a single callable that:
1. Builds universe (currency-aware if config provided)
2. Fetches price data (yfinance)
3. Scores each ticker (technical + fundamental + external)
4. Returns ranked candidates
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def _yf_loader(ticker: str):
    """Fetch daily OHLCV + info from yfinance."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    daily = t.history(period="1y", auto_adjust=True)
    info = t.info or {}
    return daily, info


def _relative_strength_strength(ticker_df: pd.DataFrame, benchmark_df: pd.DataFrame) -> dict:
    """Compute relative strength vs benchmark (delegates to technical_analysis)."""
    from investment_engine.research.technical_analysis import relative_strength
    return relative_strength(ticker_df, benchmark_df)


def _pullback_detect(ticker_df: pd.DataFrame) -> dict:
    """Detect pullback in uptrend (delegates to technical_analysis)."""
    from investment_engine.research.technical_analysis import pullback_in_uptrend
    return pullback_in_uptrend(ticker_df)


def _breakout_detect(ticker_df: pd.DataFrame) -> dict:
    """Detect breakout from downtrend (delegates to technical_analysis)."""
    from investment_engine.research.technical_analysis import breakout_from_downtrend
    return breakout_from_downtrend(ticker_df)


def run_screener(
    universe: list[str] | None = None,
    index_daily: pd.DataFrame | None = None,
    loader=None,
    ext: dict | None = None,
    cfg: dict | None = None,
    held: set[str] | None = None,
    max_candidates: int = 20,
) -> pd.DataFrame:
    """Run discovery screening on a universe of tickers.

    Args:
        universe: List of ticker symbols. If None, universe is built from cfg
            using currency-aware discovery.
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

    # Build universe if not provided, using currency-aware discovery
    if universe is None:
        from investment_engine.discovery.universe_builder import build_universe_symbols
        from investment_engine.day_trader.config import DayTraderConfig

        # Build config from cfg dict if available
        dcfg = DayTraderConfig()
        if isinstance(cfg, dict):
            dcfg = DayTraderConfig.from_mapping(cfg)
        universe_list = build_universe_symbols(dcfg, portfolio_symbols=held)
        universe = [item["ticker"] for item in universe_list]

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

    # Enrich candidates with relative strength and pullback/breakout detection
    try:
        import yfinance as yf

        from investment_engine.research.technical_analysis import (
            breakout_from_downtrend as _breakout,
        )
        from investment_engine.research.technical_analysis import (
            pullback_in_uptrend as _pullback,
        )
        from investment_engine.research.technical_analysis import (
            relative_strength as _rs,
        )
        benchmark_ticker = "SPY"
        benchmark_df = yf.Ticker(benchmark_ticker).history(period="1y", auto_adjust=True)
        for _, row in candidates.iterrows():
            ticker = row.get("ticker", "")
            if not ticker:
                continue
            try:
                ticker_df = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
                if ticker_df is not None and not ticker_df.empty and benchmark_df is not None and not benchmark_df.empty:
                    rs = _rs(ticker_df, benchmark_df)
                    pullback = _pullback(ticker_df)
                    breakout = _breakout(ticker_df)
                    # Attach to candidate row (mutate in place is not possible on DataFrame row,
                    # so store in a side dict keyed by ticker for later use)
                    candidates.at[row.name, "rs_20d"] = rs.get("rs_20d")
                    candidates.at[row.name, "rs_60d"] = rs.get("rs_60d")
                    candidates.at[row.name, "rs_120d"] = rs.get("rs_120d")
                    candidates.at[row.name, "rs_trend"] = rs.get("rs_trend")
                    candidates.at[row.name, "pullback_status"] = pullback.get("status")
                    candidates.at[row.name, "pullback_depth_pct"] = pullback.get("pullback_depth_pct")
                    candidates.at[row.name, "breakout_status"] = breakout.get("status")
                    candidates.at[row.name, "breakout_strength"] = breakout.get("breakout_strength")
            except Exception:
                # Per-ticker failure must not break the whole screener
                continue
    except Exception:
        # If benchmark fetch fails, skip RS enrichment entirely
        pass

    # Compute price targets for each candidate
    try:
        for _, row in candidates.iterrows():
            row.get("ticker", "")
            # We don't have price data here, so skip (will be computed in report)
            pass
    except Exception:
        pass

    # Limit
    if len(candidates) > max_candidates:
        candidates = candidates.head(max_candidates)

    logger.info("screener: %d candidates from %d universe tickers", len(candidates), len(universe or []))
    return candidates.reset_index(drop=True)
"""Verification of indicator levels used for short- and long-term decisions."""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest


def _frame(n=260, start=100.0, step=0.2):
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close = np.arange(n) * step + start
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": np.full(n, 1_000_000),
        },
        index=idx,
    )


def test_technical_period_is_long_enough_for_sma200():
    from investment_engine.research.market_data import _fetch_technical_yfinance

    default = inspect.signature(_fetch_technical_yfinance).parameters["period"].default
    assert default in ("1y", "2y", "5y", "max"), f"period={default} cannot warm up SMA_200"


def test_sma200_is_present_with_one_year_of_bars(monkeypatch):
    import yfinance as yf

    from investment_engine.research import market_data as md

    frame = _frame(260)
    captured = {}

    class _Ticker:
        def __init__(self, symbol):
            captured["symbol"] = symbol

        def history(self, period="1y", interval="1d"):
            captured["period"] = period
            return frame

        class _Fast:
            @staticmethod
            def get(key, default=None):
                return "USD" if key == "currency" else default

        fast_info = _Fast()

    monkeypatch.setattr(yf, "Ticker", _Ticker)
    out = md._fetch_technical_yfinance("TEST")

    assert out is not None
    assert captured["period"] in ("1y", "2y", "5y", "max")
    assert out["SMA_200"] is not None


def test_support_resistance_use_prior_bars_not_today():
    from investment_engine.research.market_data import _support_resistance_levels

    high = pd.Series([10.0] * 20 + [100.0])
    low = pd.Series([9.0] * 20 + [8.0])
    support, resistance = _support_resistance_levels(high, low, lookback=20)

    assert resistance == 10.0, "today's high must not become its own resistance"
    assert support == 9.0


def test_breakout_is_possible_against_prior_resistance():
    from investment_engine.research.market_data import _support_resistance_levels

    high = pd.Series([10.0] * 20 + [12.0])
    low = pd.Series([9.0] * 20 + [11.0])
    _, resistance = _support_resistance_levels(high, low, lookback=20)

    assert 12.0 > resistance


def test_nearest_resistance_is_none_at_all_time_high():
    from investment_engine.research.peak_valley import analyze_price_structure

    n = 80
    closes = np.concatenate([np.linspace(10, 12, 30), np.linspace(11.5, 20, 50)])
    close = pd.Series(closes, index=pd.date_range("2025-01-01", periods=n, freq="D"))

    structure = analyze_price_structure(close, {"prominence_pct": 1.0, "min_distance": 3})

    assert structure.nearest_resistance is None, (
        "a peak below the current price is support, not resistance"
    )


def test_nearest_support_is_none_at_all_time_low():
    from investment_engine.research.peak_valley import analyze_price_structure

    n = 80
    closes = np.concatenate([np.linspace(20, 18, 30), np.linspace(18.5, 10, 50)])
    close = pd.Series(closes, index=pd.date_range("2025-01-01", periods=n, freq="D"))

    structure = analyze_price_structure(close, {"prominence_pct": 1.0, "min_distance": 3})

    assert structure.nearest_support is None, (
        "a valley above the current price is resistance, not support"
    )

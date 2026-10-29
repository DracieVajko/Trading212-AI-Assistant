"""tip_screen.py — helpers for signals_ext and discovery.

Normalizes a yfinance DataFrame and provides market regime, MACD, trend, and
pump-risk features used by the Discovery Engine.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _naive(daily: pd.DataFrame) -> pd.DataFrame:
    """Normalize a yfinance DataFrame to simple columns."""
    df = daily.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in df.columns:
            low = col.lower()
            if low in df.columns:
                df[col] = df[low]
    return df


def market_regime(index_daily: pd.DataFrame) -> dict:
    """Simple market regime classifier based on SPY vs 200-day SMA."""
    try:
        df = _naive(index_daily)
        close = df["Close"].dropna()
        if len(close) < 200:
            return {"ok": False, "risk_on": False, "regime": "insufficient_data"}
        sma200 = close.rolling(200).mean().iloc[-1]
        current = close.iloc[-1]
        risk_on = bool(current > sma200)
        return {"ok": True, "risk_on": risk_on, "regime": "risk_on" if risk_on else "risk_off"}
    except Exception:
        return {"ok": False, "risk_on": False, "regime": "error"}


def weekly_macd_features(daily: pd.DataFrame) -> dict:
    """Weekly MACD features from daily data."""
    try:
        df = _naive(daily)
        close = df["Close"].dropna()
        if len(close) < 50:
            return {"ok": False, "reason": f"{len(close)} bars < 50"}
        weekly = close.resample("W").last().dropna()
        if len(weekly) < 35:
            return {"ok": False, "reason": f"{len(weekly)} weekly bars < 35"}
        ema12 = weekly.ewm(span=12).mean()
        ema26 = weekly.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        hist = macd_line - signal_line
        signal_active = bool(macd_line.iloc[-1] > signal_line.iloc[-1])
        momentum_strengthening = bool(hist.iloc[-1] > hist.iloc[-2]) if len(hist) > 1 else False
        return {"ok": True, "signal_active": signal_active, "momentum_strengthening": momentum_strengthening}
    except Exception:
        return {"ok": False, "reason": "error"}


def trend_features(daily: pd.DataFrame, max_gain: float = 0.60) -> dict:
    """Trend features: SMA200, breakout, limited prior gain."""
    try:
        df = _naive(daily)
        close = df["Close"].dropna()
        if len(close) < 200:
            return {"ok": False, "reason": f"{len(close)} bars < 200"}
        sma200 = close.rolling(200).mean()
        above_sma200 = bool(close.iloc[-1] > sma200.iloc[-1])
        sma200_rising = bool(sma200.iloc[-1] > sma200.iloc[-20]) if len(sma200) > 20 else False
        sma50 = close.rolling(50).mean()
        broke_out = bool(close.iloc[-1] > sma50.iloc[-1] and close.iloc[-20] < sma50.iloc[-20]) if len(close) > 20 else False
        low_252 = close.iloc[-252:].min() if len(close) >= 252 else close.min()
        gain_from_low = (close.iloc[-1] / low_252 - 1) if low_252 > 0 else 0
        limited_prior_gain = bool(gain_from_low < max_gain)
        return {
            "ok": True,
            "above_sma200": above_sma200,
            "sma200_rising": sma200_rising,
            "broke_out_of_downtrend": broke_out,
            "limited_prior_gain": limited_prior_gain,
        }
    except Exception:
        return {"ok": False, "reason": "error"}


def pump_risk_flags(daily: pd.DataFrame, market_cap, min_dollar_vol: float, min_cap: float, penny: float) -> dict:
    """Pump risk flags: low price, low volume, small cap."""
    try:
        df = _naive(daily)
        close = df["Close"].dropna()
        vol = df["Volume"].dropna()
        flags = []
        high_risk = False
        if len(close) == 0:
            return {"ok": False, "reason": "no data", "high_risk": True, "flags": ["no_data"]}
        last_price = float(close.iloc[-1])
        avg_vol = float(vol.rolling(20).mean().iloc[-1]) if len(vol) >= 20 else float(vol.mean())
        dollar_vol = last_price * avg_vol if avg_vol else 0
        if last_price < penny:
            flags.append("low_price")
            high_risk = True
        if dollar_vol < min_dollar_vol:
            flags.append("low_dollar_volume")
            high_risk = True
        if market_cap is not None and market_cap < min_cap:
            flags.append("small_cap")
            high_risk = True
        return {"ok": True, "high_risk": high_risk, "flags": flags}
    except Exception:
        return {"ok": False, "reason": "error", "high_risk": True, "flags": ["error"]}
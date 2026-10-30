"""price_targets.py — Price target and risk/reward calculations for Discovery.

Provides buy/sell ranges, take profit, stop loss, and expected price targets
based on technical analysis (support/resistance, ATR, SMA, Bollinger bands).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _naive(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in df.columns:
            low = col.lower()
            if low in df.columns:
                df[col] = df[low]
    return df


def compute_price_targets(daily: pd.DataFrame, info: dict | None = None) -> dict:
    """Compute price targets, buy/sell ranges, take profit, stop loss.

    Returns dict with:
        current_price, support, resistance, buy_range_low, buy_range_high,
        sell_target, take_profit, stop_loss, expected_price_30d,
        risk_reward_ratio, atr, sma50, sma200
    """
    info = info or {}
    result = {
        "current_price": None,
        "support": None,
        "resistance": None,
        "buy_range_low": None,
        "buy_range_high": None,
        "sell_target": None,
        "take_profit": None,
        "stop_loss": None,
        "expected_price_30d": None,
        "risk_reward_ratio": None,
        "atr": None,
        "sma50": None,
        "sma200": None,
    }

    try:
        df = _naive(daily)
        close = df["Close"].dropna()
        high = df["High"].dropna()
        low = df["Low"].dropna()

        if len(close) < 50:
            return result

        current = float(close.iloc[-1])
        result["current_price"] = round(current, 2)

        # SMA
        sma50 = float(close.rolling(50).mean().iloc[-1])
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
        result["sma50"] = round(sma50, 2)
        result["sma200"] = round(sma200, 2) if sma200 else None

        # ATR (14-day)
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        result["atr"] = round(atr, 2)

        # Support/Resistance (20-day low/high)
        support = float(low.iloc[-20:].min())
        resistance = float(high.iloc[-20:].max())
        result["support"] = round(support, 2)
        result["resistance"] = round(resistance, 2)

        # Buy range: support to slightly above (ATR-based)
        buy_low = support
        buy_high = support + atr * 0.5
        result["buy_range_low"] = round(buy_low, 2)
        result["buy_range_high"] = round(buy_high, 2)

        # Stop loss: below support by 1 ATR
        stop_loss = support - atr
        result["stop_loss"] = round(stop_loss, 2)

        # Take profit: resistance level
        take_profit = resistance
        result["take_profit"] = round(take_profit, 2)

        # Sell target: resistance + 1 ATR (breakout target)
        sell_target = resistance + atr
        result["sell_target"] = round(sell_target, 2)

        # Expected price 30d: current + (momentum * ATR * 30)
        # Simple momentum-based projection
        if len(close) >= 30:
            momentum_30d = (close.iloc[-1] / close.iloc[-30] - 1) if close.iloc[-30] > 0 else 0
            expected_30d = current * (1 + momentum_30d * 0.5)  # conservative: half momentum
            result["expected_price_30d"] = round(expected_30d, 2)

        # Risk/reward ratio
        risk = current - stop_loss
        reward = take_profit - current
        if risk > 0:
            result["risk_reward_ratio"] = round(reward / risk, 2)

    except Exception as exc:
        logger.debug("price_targets: computation failed: %s", type(exc).__name__)

    return result


def format_price_targets(targets: dict, currency: str = "USD") -> str:
    """Format price targets as a readable string."""
    if targets.get("current_price") is None:
        return "Price targets unavailable (insufficient data)."

    parts = [
        f"Current: {targets['current_price']} {currency}",
        f"Support: {targets['support']} | Resistance: {targets['resistance']}",
        f"Buy range: {targets['buy_range_low']} - {targets['buy_range_high']}",
        f"Sell target: {targets['sell_target']} | Take profit: {targets['take_profit']}",
        f"Stop loss: {targets['stop_loss']}",
    ]
    if targets.get("expected_price_30d"):
        parts.append(f"Expected (30d): {targets['expected_price_30d']}")
    if targets.get("risk_reward_ratio"):
        parts.append(f"Risk/Reward: {targets['risk_reward_ratio']}")
    if targets.get("atr"):
        parts.append(f"ATR(14): {targets['atr']}")
    return " | ".join(parts)

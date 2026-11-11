"""Multi-timeframe support/resistance screener.

Uses scipy.signal.argrelextrema to find local minima/maxima on both 1h and
1d charts simultaneously. When levels coincide across timeframes, they are
marked as strong support/resistance. Risk-Reward Ratio is computed from the
nearest levels.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def find_local_extrema(
    prices: pd.Series,
    order: int = 5,
) -> tuple[list[int], list[int]]:
    """Find local minima and maxima indices in a price series.

    Args:
        prices: Series of close prices.
        order: how many points on each side to compare.

    Returns:
        (minima_indices, maxima_indices)
    """
    if prices is None or len(prices) < 2 * order + 1:
        return [], []
    arr = np.asarray(prices, dtype=float)
    minima = argrelextrema(arr, np.less, order=order)[0].tolist()
    maxima = argrelextrema(arr, np.greater, order=order)[0].tolist()
    return minima, maxima


def extract_levels(
    prices: pd.Series,
    order: int = 5,
    tolerance: float = 0.02,
) -> dict[str, list[float]]:
    """Extract support and resistance levels from a price series.

    Levels are clustered: close extrema (within tolerance) are merged.

    Returns:
        {"support": [float, ...], "resistance": [float, ...]}
    """
    if prices is None or len(prices) < 2 * order + 1:
        return {"support": [], "resistance": []}
    minima_idx, maxima_idx = find_local_extrema(prices, order=order)
    arr = np.asarray(prices, dtype=float)
    support_raw = [float(arr[i]) for i in minima_idx]
    resistance_raw = [float(arr[i]) for i in maxima_idx]

    def cluster(levels: list[float], tol: float) -> list[float]:
        if not levels:
            return []
        levels = sorted(levels)
        clusters: list[list[float]] = [[levels[0]]]
        for lvl in levels[1:]:
            if abs(lvl - clusters[-1][-1]) / max(clusters[-1][-1], 1e-9) <= tol:
                clusters[-1].append(lvl)
            else:
                clusters.append([lvl])
        return [round(float(sum(c) / len(c)), 2) for c in clusters]

    return {
        "support": cluster(support_raw, tolerance),
        "resistance": cluster(resistance_raw, tolerance),
    }


def multi_timeframe_levels(
    prices_1h: pd.Series,
    prices_1d: pd.Series,
    order: int = 5,
    tolerance: float = 0.02,
    match_tolerance: float = 0.03,
) -> dict[str, Any]:
    """Find support/resistance levels confirmed across 1h and 1d timeframes.

    Args:
        prices_1h: 1-hour close prices.
        prices_1d: 1-day close prices.
        order: extrema detection order.
        tolerance: clustering tolerance within a single timeframe.
        match_tolerance: max relative difference for cross-timeframe match.

    Returns:
        dict with support, resistance, strong_support, strong_resistance,
        and cross_matches (levels confirmed on both timeframes).
    """
    levels_1h = extract_levels(prices_1h, order=order, tolerance=tolerance)
    levels_1d = extract_levels(prices_1d, order=order, tolerance=tolerance)

    def match_levels(a: list[float], b: list[float]) -> list[float]:
        """Return levels from a that have a match in b (within tolerance)."""
        matched = []
        for lvl_a in a:
            for lvl_b in b:
                if abs(lvl_a - lvl_b) / max(abs(lvl_a), 1e-9) <= match_tolerance:
                    matched.append(lvl_a)
                    break
        return matched

    strong_support = match_levels(levels_1h["support"], levels_1d["support"])
    strong_resistance = match_levels(levels_1h["resistance"], levels_1d["resistance"])

    return {
        "levels_1h": levels_1h,
        "levels_1d": levels_1d,
        "strong_support": strong_support,
        "strong_resistance": strong_resistance,
        "cross_matches": len(strong_support) + len(strong_resistance),
    }


def compute_risk_reward(
    entry: float,
    stop: float,
    target: float,
) -> dict[str, Any]:
    """Compute risk:reward ratio and related metrics.

    Returns:
        dict with risk, reward, rr_ratio, and verdict (OK if rr >= 1.0).
    """
    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = reward / risk if risk > 0 else 0.0
    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "risk": round(risk, 2),
        "reward": round(reward, 2),
        "rr_ratio": round(rr, 2),
        "verdict": "OK" if rr >= 1.0 else "POOR",
    }

"""Volume anomaly detector: news + volume catalyst confirmation.

A price move is considered high-conviction only when accompanied by an
abnormal volume spike (>= threshold * SMA_volume_20d). Plain news without
volume confirmation is ignored — this filters out low-conviction chatter.

Output per ticker:
- current_volume, sma_volume_20d, volume_ratio
- is_anomaly (bool)
- alert_level: "HIGH_CONVICTION" | "MODERATE" | "NONE"
- catalyst_type: from news event if available
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

VOLUME_THRESHOLD_HIGH = 2.5
VOLUME_THRESHOLD_MODERATE = 1.5
SMA_PERIOD = 20


def compute_volume_anomaly(
    prices: pd.DataFrame,
    *,
    threshold_high: float = VOLUME_THRESHOLD_HIGH,
    threshold_moderate: float = VOLUME_THRESHOLD_MODERATE,
    sma_period: int = SMA_PERIOD,
) -> dict[str, Any]:
    """Compute volume anomaly for a single ticker from OHLCV data.

    Args:
        prices: DataFrame with 'Volume' column (and optionally 'Close').
        threshold_high: ratio above which volume is a high-conviction anomaly.
        threshold_moderate: ratio above which volume is a moderate anomaly.
        sma_period: look-back period for the SMA volume.

    Returns:
        dict with current_volume, sma_volume, volume_ratio, is_anomaly,
        alert_level, and reason.
    """
    if prices is None or prices.empty or "Volume" not in prices.columns:
        return {
            "current_volume": 0.0,
            "sma_volume": 0.0,
            "volume_ratio": 0.0,
            "is_anomaly": False,
            "alert_level": "NONE",
            "reason": "no volume data",
        }

    vol = prices["Volume"].astype(float).dropna()
    if len(vol) < sma_period + 1:
        return {
            "current_volume": float(vol.iloc[-1]) if len(vol) > 0 else 0.0,
            "sma_volume": 0.0,
            "volume_ratio": 0.0,
            "is_anomaly": False,
            "alert_level": "NONE",
            "reason": f"insufficient bars ({len(vol)} < {sma_period + 1})",
        }

    current = float(vol.iloc[-1])
    sma = float(vol.iloc[-sma_period - 1:-1].mean())
    if sma <= 0:
        return {
            "current_volume": current,
            "sma_volume": 0.0,
            "volume_ratio": 0.0,
            "is_anomaly": False,
            "alert_level": "NONE",
            "reason": "zero SMA volume",
        }

    ratio = current / sma
    if ratio >= threshold_high:
        level = "HIGH_CONVICTION"
        is_anomaly = True
    elif ratio >= threshold_moderate:
        level = "MODERATE"
        is_anomaly = True
    else:
        level = "NONE"
        is_anomaly = False

    return {
        "current_volume": current,
        "sma_volume": round(sma, 2),
        "volume_ratio": round(ratio, 2),
        "is_anomaly": is_anomaly,
        "alert_level": level,
        "reason": f"volume {ratio:.1f}x SMA20" if is_anomaly else f"volume {ratio:.1f}x SMA20 (below threshold)",
    }


def scan_volume_anomalies(
    prices_by_ticker: dict[str, pd.DataFrame],
    *,
    threshold_high: float = VOLUME_THRESHOLD_HIGH,
    threshold_moderate: float = VOLUME_THRESHOLD_MODERATE,
) -> list[dict[str, Any]]:
    """Scan multiple tickers for volume anomalies. Returns sorted by ratio desc."""
    results = []
    for ticker, prices in prices_by_ticker.items():
        r = compute_volume_anomaly(prices, threshold_high=threshold_high, threshold_moderate=threshold_moderate)
        r["ticker"] = ticker
        results.append(r)
    results.sort(key=lambda x: x["volume_ratio"], reverse=True)
    return results


def confirm_catalyst_with_volume(
    news_catalyst: dict[str, Any] | None,
    volume_result: dict[str, Any],
) -> dict[str, Any]:
    """Confirm a news catalyst with volume data.

    Returns a dict with confirmed (bool), alert_level, and combined reason.
    Only high-conviction volume confirms the catalyst.
    """
    if not news_catalyst:
        return {
            "confirmed": False,
            "alert_level": "NONE",
            "reason": "no catalyst to confirm",
        }
    if volume_result.get("alert_level") == "HIGH_CONVICTION":
        return {
            "confirmed": True,
            "alert_level": "HIGH_CONVICTION",
            "reason": f"catalyst + volume {volume_result['volume_ratio']:.1f}x → high conviction",
        }
    if volume_result.get("alert_level") == "MODERATE":
        return {
            "confirmed": False,
            "alert_level": "MODERATE",
            "reason": f"catalyst + volume {volume_result['volume_ratio']:.1f}x → moderate (below high threshold)",
        }
    return {
        "confirmed": False,
        "alert_level": "NONE",
        "reason": "catalyst present but no volume confirmation",
    }

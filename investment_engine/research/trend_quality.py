"""Trend quality: is a moving-average cross real, and is price already stretched?

Three deterministic questions, no LLM involved:

1. **Cross validity.** A 20/50 cross is only a trend change when the slow MA has
   stopped moving against it. A "false golden cross" happens while the 50-day MA
   is still falling; the cross is then a bounce inside a downtrend.
2. **Convergence zone.** When the 5/10/20/30/60 MAs compress into a narrow band
   and price leaves it on expanding volume, the move has confirmation. Without
   volume it is a drift. The lower bound of the zone is the risk reference.
3. **Structure.** Lower highs with a broken support describe distribution; higher
   lows with a broken resistance describe accumulation.

A fourth helper answers the operator question from the brief: *"is this already
too extended to buy?"* (distance above the 20-day MA and the recent run-up).

Everything works on a daily OHLCV DataFrame with lowercase columns
(``open``/``high``/``low``/``close``/``volume``) and degrades to an explicit
``insufficient_data`` status instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

MIN_BARS = 60


@dataclass(frozen=True)
class TrendThresholds:
    """Tunables, kept explicit so the gates can be reviewed and tested."""

    fast: int = 20
    slow: int = 50
    slope_lookback: int = 10
    #: Slow-MA move over the lookback, in percent. Below this the MA is "flat".
    flat_eps_pct: float = 0.05
    #: More than one cross inside this window means whipsaw, not a trend.
    whipsaw_bars: int = 20
    #: Maximum MA dispersion (percent of price) that still counts as compression.
    max_dispersion_pct: float = 1.5
    zone_lookback: int = 15
    breakout_volume_min: float = 1.5
    swing_window: int = 3
    structure_lookback: int = 60
    chase_dist_ma20_pct: float = 10.0
    chase_run_up_pct: float = 15.0
    chase_run_up_days: int = 5


def _clean(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    missing = {"close"} - set(df.columns)
    if missing:
        return None
    out = df.copy()
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out[out["close"].notna()]
    return out if len(out) else None


def _pct_change(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    base = float(series.iloc[-1 - periods])
    if base == 0:
        return None
    return (float(series.iloc[-1]) - base) / base * 100.0


def cross_state(
    df: pd.DataFrame | None, thresholds: TrendThresholds | None = None
) -> dict[str, Any]:
    """Classify the fast/slow MA cross and decide whether it is valid.

    Valid means: the slow MA is flat or already turning in the cross direction,
    and the pair has not been crossing back and forth inside the whipsaw window.
    """
    t = thresholds or TrendThresholds()
    empty = {
        "cross": "none",
        "valid": None,
        "bars_since_cross": None,
        "slow_slope_pct": None,
        "crosses_in_window": 0,
        "reason": "insufficient_data",
    }
    data = _clean(df)
    if data is None or len(data) < t.slow + t.slope_lookback + 1:
        return empty

    close = data["close"]
    fast_ma = close.rolling(t.fast).mean()
    slow_ma = close.rolling(t.slow).mean()
    diff = (fast_ma - slow_ma).dropna()
    if len(diff) < 2:
        return empty

    # Sign changes of (fast - slow) are crosses.
    signs = np.sign(diff.to_numpy())
    flips = np.where(np.diff(signs) != 0)[0]
    crosses_in_window = int(
        sum(1 for idx in flips if (len(diff) - 1 - idx) <= t.whipsaw_bars)
    )

    last_flip = int(flips[-1]) if len(flips) else None
    if last_flip is None:
        cross = "none"
        bars_since = None
    else:
        bars_since = len(diff) - 1 - last_flip
        cross = "golden" if signs[last_flip + 1] > 0 else "death"

    slow_slope = _pct_change(slow_ma.dropna(), t.slope_lookback)
    if slow_slope is None:
        return empty

    reason = "ok"
    valid: bool | None = True
    if cross == "none":
        valid = None
        reason = "no cross in range"
    elif crosses_in_window > 1:
        valid = False
        reason = f"whipsaw: {crosses_in_window} crosses in {t.whipsaw_bars} bars"
    elif cross == "golden" and slow_slope < -t.flat_eps_pct:
        valid = False
        reason = f"slow MA still declining ({slow_slope:+.2f}% over {t.slope_lookback} bars)"
    elif cross == "death" and slow_slope > t.flat_eps_pct:
        valid = False
        reason = f"slow MA still rising ({slow_slope:+.2f}% over {t.slope_lookback} bars)"

    return {
        "cross": cross,
        "valid": valid,
        "bars_since_cross": bars_since,
        "slow_slope_pct": round(slow_slope, 3),
        "crosses_in_window": crosses_in_window,
        "reason": reason,
        "price_above_fast": bool(float(close.iloc[-1]) > float(fast_ma.iloc[-1]))
        if not pd.isna(fast_ma.iloc[-1])
        else None,
        "price_above_slow": bool(float(close.iloc[-1]) > float(slow_ma.iloc[-1]))
        if not pd.isna(slow_ma.iloc[-1])
        else None,
    }


def convergence_zone(
    df: pd.DataFrame | None, thresholds: TrendThresholds | None = None
) -> dict[str, Any]:
    """Detect an MA compression zone and a volume-confirmed breakout.

    ``risk_level`` is the lower bound of the base: if the breakout fails and
    price returns below it, the setup is invalidated.
    """
    t = thresholds or TrendThresholds()
    periods = (5, 10, 20, 30, 60)
    empty = {
        "status": "insufficient_data",
        "in_zone": False,
        "dispersion_pct": None,
        "zone_high": None,
        "zone_low": None,
        "risk_level": None,
        "volume_ratio": None,
        "breakout": False,
        "reason": "insufficient_data",
    }
    data = _clean(df)
    if data is None or len(data) < max(periods) + 1:
        return empty

    close = data["close"]
    mas = {p: close.rolling(p).mean() for p in periods}
    last_mas = [float(mas[p].iloc[-1]) for p in periods if not pd.isna(mas[p].iloc[-1])]
    if not last_mas:
        return empty
    last_mas_series = [mas[p] for p in periods if not mas[p].isna().all()]

    price = float(close.iloc[-1])
    dispersion = (max(last_mas) - min(last_mas)) / price * 100.0 if price else None

    lookback = t.zone_lookback
    highs = pd.to_numeric(data.get("high", close), errors="coerce").fillna(close)
    lows = pd.to_numeric(data.get("low", close), errors="coerce").fillna(close)
    base_high = float(highs.iloc[-(lookback + 1):-1].max())
    base_low = float(lows.iloc[-(lookback + 1):-1].min())

    volume_ratio = None
    if "volume" in data.columns:
        vol = pd.to_numeric(data["volume"], errors="coerce")
        avg = vol.rolling(20).mean()
        if not pd.isna(avg.iloc[-1]) and float(avg.iloc[-1]) > 0:
            volume_ratio = round(float(vol.iloc[-1]) / float(avg.iloc[-1]), 2)

    in_zone = dispersion is not None and dispersion <= t.max_dispersion_pct
    above_base = price > base_high
    breakout = bool(above_base and (volume_ratio or 0) >= t.breakout_volume_min)

    # Was price actually coiled before it left the base? A breakout only matters
    # as a signal when the MAs were compressed; otherwise it is just an uptrend.
    was_compressed = False
    try:
        dispersion_series = (
            pd.concat(last_mas_series, axis=1).max(axis=1)
            - pd.concat(last_mas_series, axis=1).min(axis=1)
        ) / close * 100.0
        recent = dispersion_series.iloc[-lookback:]
        was_compressed = bool(
            recent.notna().any() and float(recent.min()) <= t.max_dispersion_pct
        )
    except Exception:
        was_compressed = in_zone

    if breakout:
        status = "BREAKOUT_CONFIRMED"
        reason = f"closed above {base_high:.2f} on volume {volume_ratio:.2f}x"
    elif above_base:
        status = "BREAKOUT_UNCONFIRMED"
        reason = (
            f"closed above {base_high:.2f} but volume {volume_ratio or 0:.2f}x "
            f"< {t.breakout_volume_min:.2f}x"
        )
    elif in_zone:
        status = "IN_ZONE"
        reason = f"MA dispersion {dispersion:.2f}% <= {t.max_dispersion_pct:.2f}%"
    else:
        status = "OUTSIDE"
        reason = f"MA dispersion {dispersion:.2f}%" if dispersion is not None else "no dispersion"

    return {
        "status": status,
        "in_zone": bool(in_zone),
        "was_compressed": bool(was_compressed),
        "dispersion_pct": round(dispersion, 3) if dispersion is not None else None,
        "zone_high": round(base_high, 4),
        "zone_low": round(base_low, 4),
        "risk_level": round(base_low, 4),
        "volume_ratio": volume_ratio,
        "breakout": breakout,
        "reason": reason,
    }


def structure_break(
    df: pd.DataFrame | None, thresholds: TrendThresholds | None = None
) -> dict[str, Any]:
    """Classify swing structure and whether support/resistance broke.

    Structure is read from equal-size chunks of recent bars (max high and min
    low per chunk). Chunking is deliberate: strict local extrema are too fragile
    on real quotes, where a swing rarely sits exactly at a bar boundary.
    """
    t = thresholds or TrendThresholds()
    empty = {
        "structure": "insufficient_data",
        "support": None,
        "resistance": None,
        "support_broken": False,
        "resistance_broken": False,
        "reason": "insufficient_data",
    }
    data = _clean(df)
    if data is None or len(data) < 12:
        return empty

    window = data.iloc[-t.structure_lookback:] if len(data) > t.structure_lookback else data
    highs = pd.to_numeric(window.get("high", window["close"]), errors="coerce").fillna(window["close"])
    lows = pd.to_numeric(window.get("low", window["close"]), errors="coerce").fillna(window["close"])
    price = float(window["close"].iloc[-1])

    chunks = 4
    size = len(window) // chunks
    if size < 3:
        return empty

    chunk_highs = [float(highs.iloc[i * size:(i + 1) * size].max()) for i in range(chunks)]
    chunk_lows = [float(lows.iloc[i * size:(i + 1) * size].min()) for i in range(chunks)]

    def trend_of(points: list[float]) -> str:
        if len(points) < 2:
            return "unknown"
        last = points[-3:] if len(points) >= 3 else points[-2:]
        span = max(abs(v) for v in last) or 1.0
        tol = span * 1e-4
        rising = all(b >= a - tol for a, b in zip(last, last[1:])) and last[-1] > last[0] + tol
        falling = all(b <= a + tol for a, b in zip(last, last[1:])) and last[-1] < last[0] - tol
        if rising:
            return "rising"
        if falling:
            return "falling"
        return "mixed"

    high_trend = trend_of(chunk_highs)
    low_trend = trend_of(chunk_lows)

    if high_trend == "rising" and low_trend == "rising":
        structure = "higher_highs_higher_lows"
    elif high_trend == "falling" and low_trend == "falling":
        structure = "lower_highs_lower_lows"
    elif high_trend == "falling" and low_trend == "mixed":
        structure = "lower_highs"
    elif low_trend == "rising" and high_trend == "mixed":
        structure = "higher_lows"
    else:
        structure = "mixed"

    # Recent support/resistance: the last two chunks, not the whole window.
    support = min(chunk_lows[-2:])
    resistance = max(chunk_highs[-2:])
    support_broken = price < support
    resistance_broken = price > resistance

    reason = f"chunk highs {high_trend}, chunk lows {low_trend}"
    return {
        "structure": structure,
        "support": round(support, 4),
        "resistance": round(resistance, 4),
        "support_broken": bool(support_broken),
        "resistance_broken": bool(resistance_broken),
        "reason": reason,
    }


def chase_risk(
    df: pd.DataFrame | None, thresholds: TrendThresholds | None = None
) -> dict[str, Any]:
    """How extended is price? Buying a vertical move is the most expensive error."""
    t = thresholds or TrendThresholds()
    empty = {"level": "UNKNOWN", "dist_ma20_pct": None, "run_up_pct": None, "reason": "insufficient_data"}
    data = _clean(df)
    if data is None or len(data) < max(20, t.chase_run_up_days) + 1:
        return empty

    close = data["close"]
    ma20 = float(close.rolling(20).mean().iloc[-1])
    price = float(close.iloc[-1])
    if pd.isna(ma20) or ma20 == 0:
        return empty

    dist = (price - ma20) / ma20 * 100.0
    run_up = _pct_change(close, t.chase_run_up_days)

    level = "LOW"
    reasons: list[str] = []
    if dist >= t.chase_dist_ma20_pct:
        level = "HIGH"
        reasons.append(f"{dist:+.1f}% above the 20-day MA")
    if run_up is not None and run_up >= t.chase_run_up_pct:
        level = "HIGH"
        reasons.append(f"{run_up:+.1f}% in {t.chase_run_up_days} sessions")
    if level != "HIGH" and (dist >= t.chase_dist_ma20_pct / 2 or (run_up or 0) >= t.chase_run_up_pct / 2):
        level = "MEDIUM"
        reasons.append("price extended but below the hard limit")

    return {
        "level": level,
        "dist_ma20_pct": round(dist, 3),
        "run_up_pct": round(run_up, 3) if run_up is not None else None,
        "reason": "; ".join(reasons) if reasons else "price near the 20-day MA",
    }


def assess(df: pd.DataFrame | None, thresholds: TrendThresholds | None = None) -> dict[str, Any]:
    """All four reads in one payload, ready to embed in a technical dict."""
    data = _clean(df)
    bars = len(data) if data is not None else 0
    if data is None or bars < MIN_BARS:
        return {
            "status": "insufficient_data",
            "bars": bars,
            "min_bars": MIN_BARS,
            "cross": cross_state(None),
            "zone": convergence_zone(None),
            "structure": structure_break(None),
            "chase": chase_risk(None),
        }
    return {
        "status": "ok",
        "bars": bars,
        "min_bars": MIN_BARS,
        "cross": cross_state(data, thresholds),
        "zone": convergence_zone(data, thresholds),
        "structure": structure_break(data, thresholds),
        "chase": chase_risk(data, thresholds),
    }


def buy_block_reason(quality: dict[str, Any] | None) -> str:
    """Return why a BUY must be withheld, or an empty string when it may stand.

    Only confident negatives block. Missing or partial data never does: a data
    gap must not silently freeze the portfolio.
    """
    if not isinstance(quality, dict) or quality.get("status") != "ok":
        return ""

    cross = quality.get("cross") or {}
    if cross.get("cross") == "golden" and cross.get("valid") is False:
        return f"false golden cross: {cross.get('reason', 'unconfirmed cross')}"

    structure = quality.get("structure") or {}
    if structure.get("structure") == "lower_highs_lower_lows" and structure.get("support_broken"):
        return "distribution: lower highs with support broken"

    zone = quality.get("zone") or {}
    if zone.get("status") == "BREAKOUT_UNCONFIRMED" and zone.get("was_compressed"):
        return f"breakout without volume: {zone.get('reason', '')}".strip()

    chase = quality.get("chase") or {}
    if chase.get("level") == "HIGH":
        return f"chase risk: {chase.get('reason', 'price extended')}"

    return ""

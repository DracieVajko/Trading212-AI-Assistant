"""Higher-timeframe context filter for day-trader plans.

The day-trader pack is intentionally short-term. This filter checks the plan
against the daily chart before it can become an actionable ticket:

- daily trend (SMA50/SMA200 alignment)
- recent one-day drop (falling-knife guard)
- entry vs nearest resistance
- stop vs nearest support
- stop distance vs ATR

It is advisory-only: no orders are placed here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


def _sma(series: pd.Series, n: int) -> float | None:
    if len(series) < n:
        return None
    return float(series.tail(n).mean())


def _rsi(series: pd.Series, n: int = 14) -> float | None:
    if len(series) < n + 1:
        return None
    delta = series.diff().dropna()
    gain = delta.clip(lower=0).tail(n).mean()
    loss = (-delta.clip(upper=0)).tail(n).mean()
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _atr(frame: pd.DataFrame, n: int = 14) -> float | None:
    if not {"high", "low", "close"}.issubset(frame.columns) or len(frame) < n + 1:
        return None
    h = frame["high"].astype(float)
    l = frame["low"].astype(float)
    c = frame["close"].astype(float)
    prev = c.shift(1)
    tr = pd.concat([(h - l), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return float(tr.tail(n).mean())


def evaluate_plan(
    plan: dict[str, Any],
    daily: pd.DataFrame,
    *,
    atr_multiple: float = 1.5,
    max_recent_drop_pct: float = 8.0,
) -> FilterResult:
    """Evaluate a long ORB plan against the daily chart. Never raises."""
    reasons: list[str] = []
    warnings: list[str] = []

    if daily is None or daily.empty or "close" not in daily.columns:
        return FilterResult(True, warnings=["daily data unavailable; context filter skipped"], metrics={})

    frame = daily.copy()
    close = frame["close"].dropna()
    if len(close) < 60:
        return FilterResult(True, warnings=["insufficient daily history; context filter skipped"], metrics={})

    try:
        entry = float(plan.get("entry") or 0)
        stop = float(plan.get("stop") or 0)
        target = float(plan.get("target") or 0)
    except (TypeError, ValueError):
        return FilterResult(True, warnings=["plan prices unreadable; context filter skipped"], metrics={})

    sma20 = _sma(close, 20)
    sma50 = _sma(close, 50)
    sma200 = _sma(close, 200)
    rsi = _rsi(close)
    atr = _atr(frame)
    last_close = float(close.iloc[-1])
    ret_1d = float(close.pct_change().iloc[-1]) if len(close) > 1 else 0.0

    metrics = {
        "close": round(last_close, 4),
        "sma20": round(sma20, 4) if sma20 else None,
        "sma50": round(sma50, 4) if sma50 else None,
        "sma200": round(sma200, 4) if sma200 else None,
        "rsi14": round(rsi, 2) if rsi is not None else None,
        "atr14": round(atr, 4) if atr else None,
        "ret_1d_pct": round(ret_1d * 100, 2),
    }

    # 1. Daily trend: a long ORB against a clear downtrend is a counter-trend
    #    trade, not a breakout.
    if sma50 and sma200 and sma50 < sma200 and last_close < sma200:
        reasons.append(
            f"daily trend bearish: close {last_close:.2f} < SMA200 {sma200:.2f}, "
            f"SMA50 {sma50:.2f} < SMA200"
        )
    elif sma200 and last_close < sma200:
        warnings.append(f"close {last_close:.2f} below SMA200 {sma200:.2f}")

    # 2. Falling knife: a large one-day drop often means news/regime damage.
    if ret_1d * 100 <= -max_recent_drop_pct:
        reasons.append(f"recent 1-day drop {ret_1d * 100:.1f}% (falling-knife guard)")
    elif ret_1d * 100 <= -5.0:
        warnings.append(f"recent 1-day drop {ret_1d * 100:.1f}% (counter-trend risk)")

    # 3. Resistance room: entering at/above nearby resistance leaves no room.
    try:
        from investment_engine.research.peak_valley import analyze_price_structure
        structure = analyze_price_structure(close)
        support = structure.nearest_support
        resistance = structure.nearest_resistance
        metrics["nearest_support"] = round(support, 4) if support else None
        metrics["nearest_resistance"] = round(resistance, 4) if resistance else None
    except Exception:
        support = resistance = None

    if resistance and entry >= resistance * 0.99:
        reasons.append(
            f"entry {entry:.2f} at/above nearest resistance {resistance:.2f}"
        )
    elif resistance and target > resistance:
        warnings.append(
            f"target {target:.2f} above nearest resistance {resistance:.2f}"
        )

    # 4. Stop placement: a stop inside support is likely to be hit by noise.
    if support and stop > support:
        reasons.append(
            f"stop {stop:.2f} above nearest support {support:.2f} (inside support zone)"
        )

    # 5. Stop distance vs daily ATR: too tight for the stock's normal range.
    if atr and (entry - stop) < atr_multiple * atr:
        reasons.append(
            f"stop distance {entry - stop:.2f} < {atr_multiple:.1f}x daily ATR {atr:.2f}"
        )

    # 6. Oversold-in-downtrend warning: RSI<30 below SMA50 is counter-trend.
    if rsi is not None and rsi < 30 and sma50 and last_close < sma50:
        warnings.append("oversold (RSI<30) in a downtrend — bounce may be counter-trend")

    return FilterResult(
        allowed=not reasons,
        reasons=reasons,
        warnings=warnings,
        metrics=metrics,
    )


def stop_distance_ok(
    entry: float,
    stop: float,
    atr: float | None,
    *,
    min_atr_multiple: float = 1.5,
    min_pct: float = 0.04,
) -> bool:
    """True if the stop is far enough from the entry for this stock."""
    try:
        dist = float(entry) - float(stop)
    except (TypeError, ValueError):
        return False
    if dist <= 0:
        return False
    floor = max(min_pct * float(entry), (min_atr_multiple * float(atr)) if atr else 0.0)
    return dist >= floor


def adjust_stop_for_fill(
    plan: dict[str, Any],
    actual_fill: float,
    atr: float | None = None,
    *,
    min_atr_multiple: float = 1.5,
    min_pct: float = 0.04,
) -> dict[str, Any]:
    """Recompute stop/target from the actual fill, keeping the plan's R:R.

    The original plan assumes entry == planned entry. When the real fill
    differs (market order slippage, late entry), the stop must move with it,
    otherwise it is too tight or too loose relative to the fill.
    """
    try:
        planned_entry = float(plan.get("entry") or 0)
        planned_stop = float(plan.get("stop") or 0)
        planned_target = float(plan.get("target") or 0)
        fill = float(actual_fill)
    except (TypeError, ValueError):
        return {"stop": planned_stop, "target": planned_target, "risk": planned_entry - planned_stop}

    risk = planned_entry - planned_stop
    if risk <= 0 or planned_entry <= 0:
        return {"stop": planned_stop, "target": planned_target, "risk": risk}

    rr = (planned_target - planned_entry) / risk
    risk_pct = risk / planned_entry

    atr_floor = (min_atr_multiple * float(atr)) if atr else 0.0
    pct_floor = min_pct * fill
    floor = max(atr_floor, pct_floor, risk_pct * fill * 0.5)

    new_risk = max(risk_pct * fill, floor)
    new_stop = round(fill - new_risk, 2)
    new_target = round(fill + rr * new_risk, 2)
    return {"stop": new_stop, "target": new_target, "risk": round(fill - new_stop, 2)}

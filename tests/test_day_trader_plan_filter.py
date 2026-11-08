from __future__ import annotations

import numpy as np
import pandas as pd

from investment_engine.day_trader.plan_filter import (
    adjust_stop_for_fill,
    evaluate_plan,
    stop_distance_ok,
)


def _daily_from_close(close: np.ndarray) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({
        "close": close,
        "high": close * 1.01,
        "low": close * 0.99,
    })


def test_bearish_downtrend_and_falling_knife_blocked():
    close = np.linspace(100, 45, 300)
    close[-1] = close[-2] * 0.79  # -21% day
    daily = _daily_from_close(close)
    plan = {"entry": 51.04, "stop": 47.31, "target": 54.77}
    res = evaluate_plan(plan, daily)
    assert not res.allowed
    assert any("bearish" in r for r in res.reasons)
    assert any("falling-knife" in r for r in res.reasons)


def test_uptrend_plan_allowed():
    close = np.linspace(40, 100, 300)
    daily = _daily_from_close(close)
    plan = {"entry": 100.0, "stop": 90.0, "target": 120.0}
    res = evaluate_plan(plan, daily)
    assert res.allowed, res.reasons
    assert res.metrics["sma200"] is not None


def test_stop_inside_support_blocked():
    close = np.linspace(80, 100, 300)
    daily = _daily_from_close(close)
    plan = {"entry": 100.0, "stop": 99.0, "target": 102.0}
    res = evaluate_plan(plan, daily)
    assert not res.allowed
    assert any("stop distance" in r for r in res.reasons)


def test_stop_distance_ok():
    assert stop_distance_ok(51.04, 47.31, 2.40) is True
    assert stop_distance_ok(51.04, 50.5, 2.40) is False  # too tight
    assert stop_distance_ok(51.04, 47.31, None) is True  # min_pct floor


def test_adjust_stop_for_fill_moves_stop_with_fill():
    plan = {"entry": 51.04, "stop": 47.31, "target": 54.77}
    out = adjust_stop_for_fill(plan, 48.81, atr=2.40)
    assert out["stop"] < 48.81
    assert out["risk"] >= 0
    assert out["target"] > out["stop"]
    rr = (out["target"] - 48.81) / (48.81 - out["stop"])
    assert 0.9 < rr < 1.1


def test_adjust_stop_for_fill_fallback_on_bad_input():
    plan = {"entry": 51.04, "stop": 47.31, "target": 54.77}
    out = adjust_stop_for_fill(plan, "not-a-number")
    assert out["stop"] == 47.31
    assert out["target"] == 54.77

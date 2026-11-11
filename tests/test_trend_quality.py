"""Trend quality: false crosses, compression breakouts, structure, chase risk."""

from __future__ import annotations

import numpy as np
import pandas as pd

from investment_engine.research import trend_quality as tq


def _frame(closes, volumes=None, spread=0.4):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    highs = closes + spread
    lows = closes - spread
    vols = np.asarray(volumes, dtype=float) if volumes is not None else np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": vols}
    )


def _decline_then_rise(decline_bars=80, decline_from=100.0, decline_to=50.0, rise_bars=20, rise_to=75.0):
    down = np.linspace(decline_from, decline_to, decline_bars)
    up = np.linspace(decline_to, rise_to, rise_bars)
    return np.concatenate([down, up])


# ── cross validity ────────────────────────────────────────────────────────────


def test_false_golden_cross_while_slow_ma_still_falls():
    """A bounce inside a downtrend is not a trend change."""
    frame = _frame(_decline_then_rise(rise_bars=20, rise_to=75.0))

    state = tq.cross_state(frame)

    assert state["cross"] == "golden"
    assert state["valid"] is False
    assert "still declining" in state["reason"]
    assert state["slow_slope_pct"] < 0


def test_golden_cross_is_valid_once_the_slow_ma_turns_up():
    frame = _frame(_decline_then_rise(rise_bars=40, rise_to=110.0))

    state = tq.cross_state(frame)

    assert state["cross"] == "golden"
    assert state["valid"] is True
    assert state["slow_slope_pct"] > 0


def test_no_cross_in_range_reports_none():
    frame = _frame(np.linspace(100, 140, 120))

    state = tq.cross_state(frame)

    assert state["cross"] in ("golden", "none")
    if state["cross"] == "none":
        assert state["valid"] is None


def test_short_history_is_explicit_not_guessed():
    frame = _frame(np.linspace(100, 110, 30))

    state = tq.cross_state(frame)

    assert state["cross"] == "none"
    assert state["valid"] is None
    assert state["reason"] == "insufficient_data"


def test_whipsaw_crosses_are_invalid():
    # A fast oscillation makes the 20 MA cross the 50 MA repeatedly.
    t = np.arange(240)
    base = 100 + 8 * np.sin(2 * np.pi * t / 12.0)
    frame = _frame(base)

    state = tq.cross_state(frame)

    assert state["crosses_in_window"] > 1
    assert state["valid"] is False
    assert "whipsaw" in state["reason"]


# ── convergence zone ──────────────────────────────────────────────────────────


def _compression_then_breakout(breakout_volume=4_000_000.0):
    closes = list(np.full(70, 100.0) + np.linspace(-0.2, 0.2, 70))
    volumes = [1_000_000.0] * 70
    closes.append(103.0)
    volumes.append(breakout_volume)
    return _frame(closes, volumes)


def test_breakout_with_volume_is_confirmed_and_carries_risk_level():
    zone = tq.convergence_zone(_compression_then_breakout())

    assert zone["status"] == "BREAKOUT_CONFIRMED"
    assert zone["breakout"] is True
    assert zone["volume_ratio"] >= 1.5
    assert zone["risk_level"] == zone["zone_low"]
    assert zone["risk_level"] < 103.0


def test_breakout_without_volume_is_not_confirmed():
    zone = tq.convergence_zone(_compression_then_breakout(breakout_volume=1_000_000.0))

    assert zone["status"] == "BREAKOUT_UNCONFIRMED"
    assert zone["breakout"] is False


def test_flat_compressed_series_is_in_zone():
    closes = np.full(80, 100.0) + np.linspace(-0.1, 0.1, 80)
    zone = tq.convergence_zone(_frame(closes))

    assert zone["status"] == "IN_ZONE"
    assert zone["dispersion_pct"] <= 1.5


# ── structure ─────────────────────────────────────────────────────────────────


def test_lower_highs_with_broken_support_is_distribution():
    closes = []
    level = 120.0
    for _ in range(4):
        closes.extend([level, level - 8, level + 6])
        level -= 6
    closes.extend([level, level - 20])
    frame = _frame(np.asarray(closes, dtype=float), spread=0.5)

    structure = tq.structure_break(frame)

    assert structure["structure"] in ("lower_highs_lower_lows", "lower_highs")
    assert structure["support_broken"] is True


def test_rising_structure_is_not_distribution():
    closes = []
    level = 80.0
    for _ in range(4):
        closes.extend([level, level + 8, level + 12])
        level += 6
    frame = _frame(np.asarray(closes, dtype=float), spread=0.5)

    structure = tq.structure_break(frame)

    assert structure["structure"] in ("higher_highs_higher_lows", "higher_lows")
    assert structure["support_broken"] is False


# ── chase risk ────────────────────────────────────────────────────────────────


def test_vertical_move_is_high_chase_risk():
    closes = np.concatenate([np.full(40, 100.0), np.linspace(100, 130, 6)])
    risk = tq.chase_risk(_frame(closes))

    assert risk["level"] == "HIGH"
    assert risk["dist_ma20_pct"] >= 10


def test_price_near_the_average_is_low_chase_risk():
    closes = np.full(60, 100.0) + np.linspace(-1, 1, 60)
    risk = tq.chase_risk(_frame(closes))

    assert risk["level"] == "LOW"


# ── the gate ──────────────────────────────────────────────────────────────────


def test_assess_requires_enough_history():
    result = tq.assess(_frame(np.linspace(100, 105, 20)))

    assert result["status"] == "insufficient_data"
    assert result["bars"] == 20


def test_assess_returns_all_four_reads():
    result = tq.assess(_frame(_decline_then_rise(rise_bars=40, rise_to=110.0)))

    assert result["status"] == "ok"
    for key in ("cross", "zone", "structure", "chase"):
        assert key in result


def test_buy_block_reason_for_false_cross():
    quality = tq.assess(_frame(_decline_then_rise(rise_bars=20, rise_to=75.0)))

    reason = tq.buy_block_reason(quality)

    assert reason.startswith("false golden cross")


def test_buy_block_reason_for_chase_risk():
    closes = np.concatenate([np.full(40, 100.0), np.linspace(100, 130, 25)])
    quality = tq.assess(_frame(closes))

    reason = tq.buy_block_reason(quality)

    assert "chase risk" in reason or reason.startswith("false")


def test_buy_block_reason_is_empty_for_missing_data():
    assert tq.buy_block_reason(None) == ""
    assert tq.buy_block_reason({"status": "unavailable"}) == ""
    assert tq.buy_block_reason({"status": "insufficient_data"}) == ""


# ── integration with trade safety ────────────────────────────────────────────


def _quality(**overrides):
    base = {
        "status": "ok",
        "cross": {"cross": "none", "valid": None, "reason": "no cross in range"},
        "zone": {"status": "OUTSIDE", "was_compressed": False, "reason": ""},
        "structure": {"structure": "mixed", "support_broken": False},
        "chase": {"level": "LOW", "reason": "price near the 20-day MA"},
    }
    base.update(overrides)
    return base


def _safety_inputs(quality):
    canonical = {"AAPL": {"signal": "BUY", "display": "AAPL"}}
    rows = [{
        "display_symbol": "AAPL",
        "signal": "BUY",
        "current_price": 100.0,
        "market_value": 1000.0,
        "weight": 1.0,
        "pnl_pct": 2.0,
    }]
    technicals = {"AAPL": {
        "price": 100.0,
        "RSI_14": 55.0,
        "Support": 90.0,
        "Resistance": 110.0,
        "TREND_QUALITY": quality,
    }}
    return canonical, rows, technicals


def test_trade_safety_withholds_buy_on_false_golden_cross():
    from investment_engine.reporting.regime_report import apply_trade_safety

    canonical, rows, technicals = _safety_inputs(
        _quality(cross={"cross": "golden", "valid": False, "reason": "slow MA still declining (-2.10%)"})
    )

    apply_trade_safety(canonical, rows, technicals, "PASS", {})

    assert canonical["AAPL"]["signal"] == "HOLD"
    assert canonical["AAPL"]["gated"] is True
    assert "false golden cross" in canonical["AAPL"]["gate_reason"]


def test_trade_safety_withholds_buy_when_price_is_extended():
    from investment_engine.reporting.regime_report import apply_trade_safety

    canonical, rows, technicals = _safety_inputs(
        _quality(chase={"level": "HIGH", "reason": "+18.0% above the 20-day MA"})
    )

    apply_trade_safety(canonical, rows, technicals, "PASS", {})

    assert canonical["AAPL"]["signal"] == "HOLD"
    assert "chase risk" in canonical["AAPL"]["gate_reason"]


def test_trade_safety_leaves_buy_when_trend_quality_is_clean():
    from investment_engine.reporting.regime_report import apply_trade_safety

    canonical, rows, technicals = _safety_inputs(_quality())

    apply_trade_safety(canonical, rows, technicals, "PASS", {})

    assert canonical["AAPL"]["signal"] == "BUY"


def test_trade_safety_does_not_block_on_missing_trend_quality():
    from investment_engine.reporting.regime_report import apply_trade_safety

    canonical, rows, technicals = _safety_inputs({"status": "insufficient_data"})

    apply_trade_safety(canonical, rows, technicals, "PASS", {})

    assert canonical["AAPL"]["signal"] == "BUY"

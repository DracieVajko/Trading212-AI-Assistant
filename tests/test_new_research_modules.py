"""Tests for new research modules: volume anomaly, multi-timeframe S/R, peer benchmark, valuation gap, capex/backlog."""

from __future__ import annotations

import numpy as np
import pandas as pd

from investment_engine.research.volume_anomaly import (
    compute_volume_anomaly,
    confirm_catalyst_with_volume,
    scan_volume_anomalies,
)
from investment_engine.research.multi_timeframe_sr import (
    compute_risk_reward,
    extract_levels,
    find_local_extrema,
    multi_timeframe_levels,
)
from investment_engine.research.peer_benchmark import benchmark_peers, sector_relative_strength
from investment_engine.research.valuation_gap import (
    analyze_valuation_gap,
    get_historical_avg,
    record_valuation,
)
from investment_engine.research.capex_backlog import analyze_capex_change, extract_capex_backlog


def _prices_with_volume(volumes):
    return pd.DataFrame({"Close": [100.0] * len(volumes), "Volume": volumes})


def test_volume_anomaly_high_conviction():
    vols = [1000] * 20 + [5000]
    r = compute_volume_anomaly(_prices_with_volume(vols))
    assert r["is_anomaly"] is True
    assert r["alert_level"] == "HIGH_CONVICTION"
    assert r["volume_ratio"] >= 2.5


def test_volume_anomaly_none_below_threshold():
    vols = [1000] * 20 + [1200]
    r = compute_volume_anomaly(_prices_with_volume(vols))
    assert r["is_anomaly"] is False
    assert r["alert_level"] == "NONE"


def test_volume_anomaly_empty():
    r = compute_volume_anomaly(pd.DataFrame())
    assert r["alert_level"] == "NONE"
    assert r["reason"] == "no volume data"


def test_volume_anomaly_insufficient_bars():
    r = compute_volume_anomaly(_prices_with_volume([1000] * 5))
    assert r["alert_level"] == "NONE"


def test_confirm_catalyst_with_volume_high():
    vol = {"alert_level": "HIGH_CONVICTION", "volume_ratio": 3.0}
    res = confirm_catalyst_with_volume({"title": "earnings beat"}, vol)
    assert res["confirmed"] is True
    assert res["alert_level"] == "HIGH_CONVICTION"


def test_confirm_catalyst_no_catalyst():
    res = confirm_catalyst_with_volume(None, {"alert_level": "NONE", "volume_ratio": 1.0})
    assert res["confirmed"] is False


def test_find_local_extrema_basic():
    s = pd.Series([1, 2, 3, 2, 1, 2, 3, 2, 1])
    mn, mx = find_local_extrema(s, order=2)
    assert len(mn) >= 1
    assert len(mx) >= 1


def test_extract_levels_returns_clustered():
    s = pd.Series([10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9, 10])
    levels = extract_levels(s, order=2)
    assert isinstance(levels["support"], list)
    assert isinstance(levels["resistance"], list)


def test_multi_timeframe_levels_cross_match():
    s = pd.Series([100, 98, 96, 98, 100, 102, 104, 102, 100, 98, 96, 98, 100])
    res = multi_timeframe_levels(s, s.copy())
    assert "strong_support" in res
    assert "strong_resistance" in res
    assert res["cross_matches"] >= 0


def test_compute_risk_reward_ok():
    rr = compute_risk_reward(100.0, 95.0, 110.0)
    assert rr["rr_ratio"] == 2.0
    assert rr["verdict"] == "OK"


def test_compute_risk_reward_poor():
    rr = compute_risk_reward(100.0, 95.0, 102.0)
    assert rr["verdict"] == "POOR"


def test_peer_benchmark_ranks_target():
    peers = {
        "AAPL": {"profit_margin": 0.25, "debt_to_equity": 0.5, "pe_ratio": 28.0},
        "MSFT": {"profit_margin": 0.30, "debt_to_equity": 0.3, "pe_ratio": 35.0},
        "GOOGL": {"profit_margin": 0.20, "debt_to_equity": 0.1, "pe_ratio": 22.0},
    }
    res = benchmark_peers("AAPL", peers, ["profit_margin", "debt_to_equity", "pe_ratio"])
    assert res["ticker"] == "AAPL"
    assert 0.0 <= res["competitive_advantage"] <= 1.0
    assert res["peer_count"] == 3


def test_peer_benchmark_missing_target():
    res = benchmark_peers("NOPE", {"AAPL": {"pe_ratio": 20.0}}, ["pe_ratio"])
    assert "error" in res


def test_sector_relative_strength_sorts():
    peers = {
        "A": {"profit_margin": 0.25, "pe_ratio": 28.0},
        "B": {"profit_margin": 0.30, "pe_ratio": 35.0},
    }
    res = sector_relative_strength(["A", "B"], peers, ["profit_margin", "pe_ratio"])
    assert len(res) == 2
    assert res[0]["competitive_advantage"] >= res[1]["competitive_advantage"]


def test_valuation_gap_detects_gap(tmp_path):
    db = tmp_path / "vg.db"
    for pe in [30.0, 28.0, 32.0, 29.0]:
        record_valuation("AAPL", pe_ratio=pe, db_path=db)
    res = analyze_valuation_gap("AAPL", current_pe=20.0, db_path=db)
    assert res["gap_detected"] is True
    assert res["gap_pct"] >= 20.0
    assert "VALUE_GAP" in res["verdict"]


def test_valuation_gap_no_gap(tmp_path):
    db = tmp_path / "vg.db"
    for pe in [30.0, 28.0, 32.0, 29.0]:
        record_valuation("AAPL", pe_ratio=pe, db_path=db)
    res = analyze_valuation_gap("AAPL", current_pe=29.0, db_path=db)
    assert res["gap_detected"] is False


def test_valuation_gap_fundamentals_deteriorated(tmp_path):
    db = tmp_path / "vg.db"
    for pe in [30.0, 28.0, 32.0, 29.0]:
        record_valuation("AAPL", pe_ratio=pe, db_path=db)
    res = analyze_valuation_gap("AAPL", current_pe=20.0, fundamentals_deteriorated=True, db_path=db)
    assert res["gap_detected"] is False
    assert "FUNDAMENTALS_DETERIORATED" in res["verdict"]


def test_valuation_gap_insufficient_history(tmp_path):
    db = tmp_path / "vg.db"
    record_valuation("AAPL", pe_ratio=30.0, db_path=db)
    res = analyze_valuation_gap("AAPL", current_pe=20.0, db_path=db)
    assert "INSUFFICIENT_HISTORY" in res["verdict"]


def test_capex_extract_basic():
    text = "Capital expenditures were $500 million in Q3. Order backlog of $1.2 billion."
    r = extract_capex_backlog(text)
    assert r["found"] is True
    assert r["capex_usd"] == 500_000_000.0
    assert r["backlog_usd"] == 1_200_000_000.0


def test_capex_extract_empty():
    r = extract_capex_backlog("")
    assert r["found"] is False
    assert r["capex_usd"] is None


def test_capex_analyze_strong():
    res = analyze_capex_change(1000.0, 500.0, current_backlog=200.0, previous_backlog=100.0)
    assert res["verdict"] == "STRONG"
    assert res["capex_change_pct"] == 100.0


def test_capex_analyze_decline():
    res = analyze_capex_change(400.0, 500.0)
    assert res["verdict"] == "DECLINE"


def test_capex_analyze_unknown():
    res = analyze_capex_change(None, 500.0)
    assert res["verdict"] == "UNKNOWN"

"""Valuation gap analyzer: mean reversion vs historical levels.

Tracks 5-year average P/E and EV/EBITDA per ticker in SQLite. When current
valuation drops significantly below the historical level (and fundamentals
haven't deteriorated), flags a "Value Gap".
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path("data") / "valuation_history.db"
GAP_THRESHOLD_PCT = 20.0  # current must be >= 20% below historical avg


def _safe(val: Any) -> float | None:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _get_conn(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS valuation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            ts TEXT NOT NULL,
            pe_ratio REAL,
            ev_ebitda REAL,
            price REAL,
            eps REAL
        )"""
    )
    conn.commit()
    return conn


def record_valuation(
    ticker: str,
    pe_ratio: float | None,
    ev_ebitda: float | None = None,
    price: float | None = None,
    eps: float | None = None,
    db_path: str | Path | None = None,
) -> None:
    """Record a valuation snapshot for a ticker."""
    ticker = ticker.upper().strip()
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO valuation_history (ticker, ts, pe_ratio, ev_ebitda, price, eps) VALUES (?,?,?,?,?,?)",
            (ticker, datetime.now().isoformat(), pe_ratio, ev_ebitda, price, eps),
        )
        conn.commit()
    finally:
        conn.close()


def get_historical_avg(
    ticker: str,
    metric: str = "pe_ratio",
    min_samples: int = 3,
    db_path: str | Path | None = None,
) -> float | None:
    """Return the historical average of a metric for a ticker.

    Returns None if insufficient samples.
    """
    ticker = ticker.upper().strip()
    if metric not in ("pe_ratio", "ev_ebitda"):
        return None
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            f"SELECT {metric} FROM valuation_history WHERE ticker=? AND {metric} IS NOT NULL",
            (ticker,),
        ).fetchall()
        values = [r[0] for r in rows if r[0] is not None]
        if len(values) < min_samples:
            return None
        return sum(values) / len(values)
    finally:
        conn.close()


def analyze_valuation_gap(
    ticker: str,
    current_pe: float | None,
    current_ev_ebitda: float | None = None,
    fundamentals_deteriorated: bool = False,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Analyze whether a ticker has a valuation gap (mean reversion opportunity).

    Returns:
        dict with gap_detected, gap_pct, historical_avg, current, verdict.
    """
    ticker = ticker.upper().strip()
    current_pe = _safe(current_pe)
    current_ev = _safe(current_ev_ebitda)

    hist_pe = get_historical_avg(ticker, "pe_ratio", db_path=db_path)
    hist_ev = get_historical_avg(ticker, "ev_ebitda", db_path=db_path)

    result: dict[str, Any] = {
        "ticker": ticker,
        "current_pe": current_pe,
        "historical_pe_avg": round(hist_pe, 2) if hist_pe else None,
        "current_ev_ebitda": current_ev,
        "historical_ev_ebitda_avg": round(hist_ev, 2) if hist_ev else None,
        "gap_detected": False,
        "gap_pct": 0.0,
        "gap_metric": None,
        "verdict": "NO_DATA",
    }

    if fundamentals_deteriorated:
        result["verdict"] = "FUNDAMENTALS_DETERIORATED - gap not valid"
        return result

    # Check P/E gap
    if current_pe is not None and hist_pe is not None and hist_pe > 0:
        gap_pct = (hist_pe - current_pe) / hist_pe * 100.0
        if gap_pct >= GAP_THRESHOLD_PCT:
            result["gap_detected"] = True
            result["gap_pct"] = round(gap_pct, 2)
            result["gap_metric"] = "pe_ratio"
            result["verdict"] = f"VALUE_GAP: P/E {gap_pct:.1f}% below 5yr avg"
            return result

    # Check EV/EBITDA gap
    if current_ev is not None and hist_ev is not None and hist_ev > 0:
        gap_pct = (hist_ev - current_ev) / hist_ev * 100.0
        if gap_pct >= GAP_THRESHOLD_PCT:
            result["gap_detected"] = True
            result["gap_pct"] = round(gap_pct, 2)
            result["gap_metric"] = "ev_ebitda"
            result["verdict"] = f"VALUE_GAP: EV/EBITDA {gap_pct:.1f}% below 5yr avg"
            return result

    if hist_pe is None and hist_ev is None:
        result["verdict"] = "INSUFFICIENT_HISTORY (need >= 3 samples)"
    else:
        result["verdict"] = "NO_GAP: valuation within normal range"

    return result

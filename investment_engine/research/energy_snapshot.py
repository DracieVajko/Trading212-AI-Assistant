"""Energy/commodity price snapshot (Phase 5E).

Benchmark-identified spot/futures prices via Yahoo Finance — separate from
news about the same commodities. An equity ETF price is never presented as
a commodity price. Never raises: per-benchmark failures degrade to an
explicit error entry, the run always continues.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# symbol: (label, currency, unit, venue, contract)
BENCHMARKS: dict[str, tuple[str, str, str, str, str]] = {
    "CL=F": ("WTI crude", "USD", "bbl", "NYMEX", "front-month futures"),
    "BZ=F": ("Brent crude", "USD", "bbl", "ICE", "front-month futures"),
    "NG=F": ("US natural gas (Henry Hub)", "USD", "MMBtu", "NYMEX", "front-month futures"),
    "HG=F": ("Copper", "USD", "lb", "COMEX", "front-month futures"),
    "GC=F": ("Gold", "USD", "troy oz", "COMEX", "front-month futures"),
}

_TIMEOUT_S = 15


def fetch_snapshot(symbols: list[str] | None = None,
                   timeout: int = _TIMEOUT_S) -> dict[str, Any]:
    """Fetch one price per benchmark. Returns {benchmarks: {...}, stats: {...}}.

    Each benchmark entry carries price + benchmark identity (label, currency,
    unit, venue, contract) + as_of, or an explicit error. Never raises.
    """
    wanted = [s for s in (symbols or list(BENCHMARKS)) if s in BENCHMARKS]
    out: dict[str, Any] = {"benchmarks": {}, "stats": {"attempted": 0, "ok": 0}}
    try:
        import yfinance as yf
    except ImportError:
        for sym in wanted:
            out["benchmarks"][sym] = {"error": "yfinance unavailable"}
        return out
    for sym in wanted:
        label, currency, unit, venue, contract = BENCHMARKS[sym]
        out["stats"]["attempted"] += 1
        try:
            info = yf.Ticker(sym).fast_info
            price = info.get("lastPrice", None)
            if price is None:
                price = info.get("regularMarketPrice", None)
            if price is None:
                raise ValueError("no price field")
            out["benchmarks"][sym] = {
                "label": label,
                "price": round(float(price), 2),
                "currency": currency,
                "unit": unit,
                "venue": venue,
                "contract": contract,
                "as_of": datetime.now(timezone.utc).date().isoformat(),
            }
            out["stats"]["ok"] += 1
        except Exception as exc:
            out["benchmarks"][sym] = {
                "label": label,
                "currency": currency,
                "unit": unit,
                "venue": venue,
                "contract": contract,
                "as_of": datetime.now(timezone.utc).date().isoformat(),
                "error": f"{type(exc).__name__}",
            }
    return out

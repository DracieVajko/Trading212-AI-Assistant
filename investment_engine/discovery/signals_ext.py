"""signals_ext.py - extra rules extracted from the tip-group lessons + hype-text detector.
Needs tip_screen.py next to it. Thresholds are defaults, NOT validated edges.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .tip_screen import _naive


# ------------------------------------------------ 50/200 SMA golden/death cross
def sma_cross_features(daily: pd.DataFrame, fast: int = 50, slow: int = 200,
                       lookback: int = 20) -> dict:
    """Classic golden cross (the group's weekly-MACD 'golden cross' is non-standard)."""
    c = _naive(daily)["Close"].dropna()
    if len(c) < slow + lookback + 5:
        return {"ok": False, "reason": f"{len(c)} bars < {slow + lookback + 5}"}
    diff = c.rolling(fast).mean() - c.rolling(slow).mean()
    up = (diff > 0) & (diff.shift(1) <= 0)
    dn = (diff < 0) & (diff.shift(1) >= 0)

    def since(mask: pd.Series):
        idx = np.flatnonzero(mask.values)
        return int(len(c) - 1 - idx[-1]) if len(idx) else None

    gc, dc = since(up), since(dn)
    return {"ok": True, "golden_cross_days_ago": gc, "death_cross_days_ago": dc,
            "golden_cross_recent": gc is not None and gc <= lookback,
            "fast_above_slow": bool(diff.iloc[-1] > 0)}


# ------------------------------------------------ Bollinger squeeze / breakout
def bollinger_features(daily: pd.DataFrame, n: int = 20, k: float = 2.0,
                       lookback: int = 252, squeeze_q: float = 0.2, recent: int = 10) -> dict:
    c = _naive(daily)["Close"].dropna()
    if len(c) < n + lookback:
        return {"ok": False, "reason": f"{len(c)} bars < {n + lookback}"}
    mid, sd = c.rolling(n).mean(), c.rolling(n).std(ddof=0)
    up, lo = mid + k * sd, mid - k * sd
    bw = (up - lo) / mid
    width = (up - lo).iloc[-1]
    hist = bw.iloc[-lookback:]
    thr = hist.quantile(squeeze_q)
    squeeze_recent = bool((bw.iloc[-recent:] <= thr).any())
    breakout = bool(c.iloc[-1] > up.iloc[-1])
    return {"ok": True,
            "pct_b": float((c.iloc[-1] - lo.iloc[-1]) / width) if width > 0 else float("nan"),
            "bandwidth_pctile": float((hist <= bw.iloc[-1]).mean()),
            "squeeze_now": bool(bw.iloc[-1] <= thr),
            "squeeze_recent": squeeze_recent,
            "breakout_up": breakout,
            "squeeze_then_breakout": bool(squeeze_recent and breakout)}


# ------------------------------------------------ 'upward channel' (log-price regression)
def channel_features(daily: pd.DataFrame, window: int = 120, min_r2: float = 0.6) -> dict:
    c = _naive(daily)["Close"].dropna()
    if len(c) < window:
        return {"ok": False, "reason": f"{len(c)} bars < {window}"}
    y = np.log(c.iloc[-window:].values)
    x = np.arange(window)
    slope, icpt = np.polyfit(x, y, 1)
    res = y - (slope * x + icpt)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float((res ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    sd = float(res.std(ddof=0))
    return {"ok": True,
            "slope_ann": float(np.exp(slope * 252) - 1),
            "r2": r2,
            "pos_sd": float(res[-1] / sd) if sd > 0 else 0.0,   # +2 = at upper channel edge
            "upward_channel": bool(slope > 0 and r2 >= min_r2)}


# ------------------------------------------------ fundamentals checklist (criterion 3)
def quality_score(info: dict) -> dict:
    """info = yfinance Ticker.info-like dict. Missing fields are skipped, not failed.
    NOTE: yfinance 'debtToEquity' is in percent (150 = 1.5x)."""
    def g(k):
        v = info.get(k)
        return v if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)) else None

    spec = {
        "revenue_growth>5%": (g("revenueGrowth"), lambda v: v > 0.05),
        "earnings_growth>0": (g("earningsGrowth"), lambda v: v > 0),
        "profit_margin>0": (g("profitMargins"), lambda v: v > 0),
        "fcf>0": (g("freeCashflow"), lambda v: v > 0),
        "debt_to_equity<150%": (g("debtToEquity"), lambda v: v < 150),
        "roe>10%": (g("returnOnEquity"), lambda v: v > 0.10),
    }
    checks = {k: (None if v is None else bool(f(v))) for k, (v, f) in spec.items()}
    done = [v for v in checks.values() if v is not None]
    return {"score": (sum(done) / len(done)) if done else 0.0,
            "coverage": len(done) / len(spec), "checks": checks}


# ------------------------------------------------ hype / FOMO text detector
HYPE_PATTERNS = {
    "fomo": r"(cannot|can'?t) afford to miss|don'?t miss|last chance|before it'?s too late|"
            r"act now|limited[- ]time|rare opportunit|extremely rare",
    "chase": r"chas(e|ing) the (rise|rally|market)|buy (the )?breakout now",
    "guarantee": r"guarantee[ds]?|risk[- ]free|sure thing|can'?t lose|no risk|100% (win|return)",
    "authority": r"insider (info|tip)|inside information|exclusive (tips?|access)|vip (group|access)",
    "contact": r"contact (us|me)|reach out|message (me|us)|add (me|us)|whatsapp|telegram|"
               r"join (our|the) (group|community)",
    "returns": r"\d{2,3}\s?% (weekly|monthly|per month|a week|per week)",
}
_HYPE_RE = {k: re.compile(v, re.I) for k, v in HYPE_PATTERNS.items()}


def hype_flags(text: str) -> dict:
    """Use on news/social text before it reaches the LLM. >=2 categories => high."""
    hit = {k: len(r.findall(text or "")) for k, r in _HYPE_RE.items()}
    cats = [k for k, v in hit.items() if v]
    return {"categories": cats, "n_categories": len(cats), "high": len(cats) >= 2, "counts": hit}

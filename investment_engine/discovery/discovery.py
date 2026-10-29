"""discovery.py - Stage 0 'Discovery': scores a universe and hands CANDIDATE / WATCH / REJECT to
Stage 2 (the agent), which does the full verify -> context -> research -> verdict workflow.
Discovery never emits BUY. Needs tip_screen.py, signals_ext.py, trackers.py (+ yfinance for yf_loader).
"""
from __future__ import annotations

import copy

import pandas as pd

from . import signals_ext as sx
from . import tip_screen as ts
from . import trackers as tr

DEFAULT_CONFIG = {
    "thresholds": {"candidate": 6.0, "watch": 4.0},
    "max_gain_from_low": 0.60,                 # 'limited prior appreciation'
    "min_dollar_vol": 5e6, "min_cap": 3e8, "penny": 5.0,
    "cramer": {"mode": "inverse", "weight": 0.5, "cap": 1.0, "lookback_days": 14},
    "investors": {   # add more: name -> {cik, mode, weight, cap}. CIKs: find on sec.gov, verify!
        "Berkshire Hathaway": {"cik": 1067983, "mode": "follow", "weight": 0.5, "cap": 1.0},
    },
    "insider": {"weight": 1.0, "senior_bonus": 0.5, "min_insiders": 3, "min_total": 100_000},
    "ext_cap": 1.5,                            # total external adjustment limit (abs)
}


def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


# ------------------------------------------------------------------ loaders
def yf_loader(ticker: str):
    import yfinance as yf
    t = yf.Ticker(ticker)
    return t.history(period="5y", auto_adjust=True), (t.info or {})


# ------------------------------------------------------------------ external signals
def build_ext(cfg: dict, cramer_events=(), investor_events=None, clusters: pd.DataFrame | None = None,
              hype_text: dict | None = None, asof=None) -> dict:
    """-> {ticker: {'cramer': x, 'investors': y, 'insider': z, 'hype': bool}} (adjustments, not verdicts)."""
    cfg = _merge(DEFAULT_CONFIG, cfg)
    ext: dict = {}

    def put(t, k, v):
        d = ext.setdefault(t, {"cramer": 0.0, "investors": 0.0, "insider": 0.0, "hype": False})
        d[k] = bool(v) if k == "hype" else d[k] + v

    c = cfg["cramer"]
    for t, v in tr.event_adjustments(cramer_events, c["mode"], c["weight"], c["cap"],
                                     c["lookback_days"], asof).items():
        put(t, "cramer", v)
    for name, evs in (investor_events or {}).items():
        ic = cfg["investors"].get(name, {"mode": "shadow", "weight": 0.0, "cap": 0.0})
        for t, v in tr.event_adjustments(evs, ic["mode"], ic["weight"], ic["cap"], 120, asof).items():
            put(t, "investors", v)
    if clusters is not None and len(clusters):
        ins = cfg["insider"]
        for _, r in clusters.iterrows():
            put(r["ticker"], "insider", ins["weight"] + (ins["senior_bonus"] if r["senior_buy"] else 0.0))
    for t, txt in (hype_text or {}).items():
        if sx.hype_flags(txt)["high"]:
            put(t, "hype", True)
    return ext


# ------------------------------------------------------------------ scoring
def _decide(base: float, ext_total: float, reject: list, cap_watch: list, cfg: dict):
    th = cfg["thresholds"]
    if reject:
        return "REJECT", reject
    total = base + ext_total
    if total >= th["candidate"] and base >= th["candidate"] - 1.0:   # external signals can't carry alone
        return ("WATCH", cap_watch) if cap_watch else ("CANDIDATE", [])
    return ("WATCH", cap_watch) if total >= th["watch"] else ("REJECT", ["score_below_watch"])


def score_candidate(ticker: str, daily: pd.DataFrame, regime: dict, info: dict | None,
                    ext: dict | None, cfg: dict | None = None, held: bool = False) -> dict:
    cfg = _merge(DEFAULT_CONFIG, cfg)
    info, ext = info or {}, ext or {}
    wk = ts.weekly_macd_features(daily)
    tf = ts.trend_features(daily, cfg["max_gain_from_low"])
    pump = ts.pump_risk_flags(daily, info.get("marketCap"), cfg["min_dollar_vol"], cfg["min_cap"], cfg["penny"])
    out = {"ticker": ticker, "held": held, "status": "REJECT", "score": 0.0, "base": 0.0,
           "ext": 0.0, "components": {}, "reasons": [], "flags": []}
    if not (wk["ok"] and tf["ok"] and pump["ok"]):
        out["reasons"] = ["insufficient_data"]
        return out

    ch, sc, bb = sx.channel_features(daily), sx.sma_cross_features(daily), sx.bollinger_features(daily)
    q = sx.quality_score(info)
    comp = {
        "trend": float(tf["above_sma200"]) + float(tf["sma200_rising"]) + float(ch.get("upward_channel", False)),
        "momentum": 1.5 * float(wk["signal_active"]) + 0.5 * float(wk["momentum_strengthening"]),
        "quality": 3.0 * q["score"] if q["coverage"] >= 0.5 else 0.0,
        "structure": float(tf["broke_out_of_downtrend"]) + float(tf["limited_prior_gain"]),
    }
    base = sum(comp.values())
    e = ext.get(ticker, {})
    ext_total = max(-cfg["ext_cap"], min(cfg["ext_cap"],
                    e.get("cramer", 0.0) + e.get("investors", 0.0) + e.get("insider", 0.0)))

    reject, cap_watch = [], []
    if pump["high_risk"]:
        reject += [f"pump_risk:{f}" for f in pump["flags"]]
    if not regime.get("ok") or not regime.get("risk_on"):
        cap_watch.append("regime_off")
    if not tf["limited_prior_gain"]:
        cap_watch.append("extended_wait_for_pullback")
    if e.get("hype"):
        cap_watch.append("hype_in_source_text")
    if q["coverage"] < 0.5:
        out["flags"].append("fundamentals_incomplete")
    if bb.get("ok") and bb["squeeze_then_breakout"]:
        out["flags"].append("bollinger_squeeze_breakout")
    if sc.get("ok") and sc["golden_cross_recent"]:
        out["flags"].append("sma50_200_golden_cross_recent")

    status, why = _decide(base, ext_total, reject, cap_watch, cfg)
    out.update({"status": status, "score": round(base + ext_total, 2), "base": round(base, 2),
                "ext": round(ext_total, 2), "components": {k: round(v, 2) for k, v in comp.items()},
                "reasons": why})
    return out


def run_discovery(universe, index_daily: pd.DataFrame, loader=yf_loader, ext: dict | None = None,
                  cfg: dict | None = None, held=()) -> pd.DataFrame:
    regime = ts.market_regime(index_daily)
    held = {h.upper() for h in held}
    rows = []
    for t in universe:
        try:
            daily, info = loader(t)
            rows.append(score_candidate(t, daily, regime, info, ext, cfg, held=t.upper() in held))
        except Exception as ex:  # one bad ticker must not kill the run
            rows.append({"ticker": t, "held": t.upper() in held, "status": "REJECT", "score": 0.0,
                         "base": 0.0, "ext": 0.0, "components": {}, "reasons": [f"error:{type(ex).__name__}"],
                         "flags": []})
    df = pd.DataFrame(rows)
    order = {"CANDIDATE": 0, "WATCH": 1, "REJECT": 2}
    return df.sort_values(["status", "score"], key=lambda s: s.map(order) if s.name == "status" else -s)\
             .reset_index(drop=True)

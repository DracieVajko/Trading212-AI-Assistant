"""trackers.py - external-signal trackers for the Discovery stage.
  1. configurable contrarian/follow rule (Cramer etc.) + ShadowBook that MEASURES the rule
  2. 13F tracker (SEC EDGAR): parse, quarter-over-quarter diff, CUSIP->ticker (OpenFIGI)
  3. insider-buying cluster detector (input: Form 4 transactions DataFrame)
Network functions need `requests` and are UNTESTED live (offline sandbox); parsers/logic are tested.
"""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

SEC_UA = "CHANGE-ME Your Name your@email.example"   # SEC requires a declared User-Agent
SEC_SLEEP = 0.25                                    # SEC fair access: max 10 req/s

_SIGN = {"follow": 1.0, "inverse": -1.0, "shadow": 0.0}
_ACT = {"buy": 1.0, "sell": -1.0, "mention": 0.0}


# =============================================================== 1. rule + shadow book
def event_adjustments(events, mode: str = "inverse", weight: float = 0.5, cap: float = 1.0,
                      lookback_days: int = 14, asof=None) -> dict:
    """events: iterable of {ticker, action: buy|sell|mention, date}. -> {ticker: score adjustment}.
    mode: inverse (do the opposite) | follow | shadow (log only, adjustment 0)."""
    if mode not in _SIGN:
        raise ValueError(f"mode must be one of {list(_SIGN)}")
    asof = pd.Timestamp(asof or pd.Timestamp.today()).normalize()
    raw: dict = {}
    for e in events:
        age = (asof - pd.Timestamp(e["date"]).normalize()).days
        if age < 0 or age > lookback_days:
            continue
        raw[e["ticker"]] = raw.get(e["ticker"], 0.0) + _ACT[e["action"]] * (1 - age / lookback_days)
    return {t: float(np.clip(v * _SIGN[mode] * weight, -cap, cap)) for t, v in raw.items()}


class ShadowBook:
    """Stores raw (follow-direction) signals per source and measures forward excess returns.
    Entry = first close strictly AFTER the signal date (no look-ahead)."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.rows = json.loads(self.path.read_text()) if self.path and self.path.exists() else []

    def add(self, source: str, ticker: str, action: str, date) -> None:
        side = _ACT.get(action, 0.0)
        if side == 0.0:
            return
        row = {"source": source, "ticker": ticker, "side": side,
               "date": str(pd.Timestamp(date).date())}
        if row not in self.rows:
            self.rows.append(row)
            if self.path:
                self.path.write_text(json.dumps(self.rows, indent=1))

    def evaluate(self, prices: dict, bench: pd.Series, horizons=(5, 21, 63)) -> pd.DataFrame:
        """prices: {ticker: Close Series}; bench: Close Series. Excess is in FOLLOW direction
        (inverse = negative of it). t-stat is overstated (overlapping, correlated events)."""
        bench = bench.sort_index()
        out = []
        for r in self.rows:
            s = prices.get(r["ticker"])
            if s is None or len(s) < 3:
                continue
            s = s.sort_index()
            i = int(s.index.searchsorted(pd.Timestamp(r["date"]), side="right"))
            for h in horizons:
                if i + h >= len(s):
                    continue
                d0, d1 = s.index[i], s.index[i + h]
                b0, b1 = bench.asof(d0), bench.asof(d1)
                if pd.isna(b0) or pd.isna(b1):
                    continue
                out.append({"source": r["source"], "horizon": h,
                            "excess": r["side"] * ((s.iloc[i + h] / s.iloc[i] - 1) - (b1 / b0 - 1))})
        if not out:
            return pd.DataFrame(columns=["source", "horizon", "n", "mean_excess", "hit_rate", "tstat"])
        df = pd.DataFrame(out)
        g = df.groupby(["source", "horizon"])["excess"]
        res = g.agg(n="size", mean_excess="mean", hit_rate=lambda x: float((x > 0).mean()), sd="std")
        res["tstat"] = res["mean_excess"] / (res["sd"] / np.sqrt(res["n"]))
        return res.drop(columns="sd").reset_index()


def suggest_mode(ev: pd.DataFrame, horizon: int = 21, min_n: int = 30, t: float = 3.0) -> dict:
    """Evidence gate: follow if t>=+t, inverse if t<=-t, else shadow (no score impact)."""
    out = {}
    for _, r in ev[ev["horizon"] == horizon].iterrows():
        out[r["source"]] = ("follow" if r["tstat"] >= t else "inverse" if r["tstat"] <= -t
                            else "shadow") if r["n"] >= min_n else "shadow"
    return out


# =============================================================== 2. 13F tracker
def _get(url: str, ua: str = SEC_UA):
    import requests
    r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=30)
    r.raise_for_status()
    time.sleep(SEC_SLEEP)
    return r


def list_13f(cik, ua: str = SEC_UA, n: int = 2) -> list:
    """Newest-first [(accession, filingDate, reportDate)] of original 13F-HR filings (amendments skipped)."""
    r = _get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", ua).json()["filings"]["recent"]
    rows = [(a, fd, rd) for f, a, fd, rd in
            zip(r["form"], r["accessionNumber"], r["filingDate"], r["reportDate"]) if f == "13F-HR"]
    return rows[:n]


def fetch_info_table_xml(cik, accession: str, ua: str = SEC_UA) -> str:
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    items = _get(base + "index.json", ua).json()["directory"]["item"]
    xmls = [i["name"] for i in items
            if i["name"].lower().endswith(".xml") and "primary_doc" not in i["name"].lower()]
    if not xmls:
        raise RuntimeError(f"no information-table XML in {base}")
    xmls.sort(key=lambda n: ("info" not in n.lower(), n))
    return _get(base + xmls[0], ua).text


def _txt(el, name: str) -> str:
    for c in el.iter():
        if c.tag.split("}")[-1] == name:
            return (c.text or "").strip()
    return ""


def parse_info_table(xml_text: str) -> pd.DataFrame:
    root = ET.fromstring(xml_text)
    rows = []
    for el in root.iter():
        if el.tag.split("}")[-1] != "infoTable":
            continue
        rows.append({"cusip": _txt(el, "cusip").upper(), "name": _txt(el, "nameOfIssuer"),
                     "value": float(_txt(el, "value") or 0),   # units differ across eras: use weights
                     "shares": float(_txt(el, "sshPrnamt") or 0),
                     "type": _txt(el, "sshPrnamtType"), "put_call": _txt(el, "putCall")})
    return pd.DataFrame(rows, columns=["cusip", "name", "value", "shares", "type", "put_call"])


def diff_13f(prev: pd.DataFrame, cur: pd.DataFrame, chg: float = 0.20) -> pd.DataFrame:
    """Quarter-over-quarter diff on common shares only (options/bonds excluded).
    Splits look like add/trim - sanity-check via d_weight. 13F = long US-listed only, quarter-end snapshot."""
    def agg(df):
        d = df[(df["put_call"] == "") & (df["type"].isin(["SH", ""]))]
        g = d.groupby("cusip").agg(name=("name", "first"), shares=("shares", "sum"), value=("value", "sum"))
        tot = g["value"].sum()
        g["weight"] = g["value"] / tot if tot > 0 else 0.0
        return g

    m = agg(cur).join(agg(prev), how="outer", lsuffix="_cur", rsuffix="_prev")
    m["name"] = m["name_cur"].fillna(m["name_prev"])
    for c in ("shares_cur", "shares_prev", "weight_cur", "weight_prev"):
        m[c] = m[c].fillna(0.0)

    def act(r):
        if r["shares_prev"] == 0 and r["shares_cur"] > 0:
            return "new"
        if r["shares_cur"] == 0 and r["shares_prev"] > 0:
            return "exited"
        if r["shares_cur"] > r["shares_prev"] * (1 + chg):
            return "added"
        if r["shares_cur"] < r["shares_prev"] * (1 - chg):
            return "trimmed"
        return "hold"

    m["action"] = m.apply(act, axis=1)
    m["d_weight"] = m["weight_cur"] - m["weight_prev"]
    cols = ["name", "action", "shares_prev", "shares_cur", "weight_prev", "weight_cur", "d_weight"]
    return m[cols].sort_values("d_weight", ascending=False)


def cusip_to_ticker(cusips, cache_path: str = "cusip_cache.json", api_key: str | None = None) -> dict:
    """OpenFIGI mapping (free; w/o key ~10 jobs/request, ~25 req/min - verify in their docs)."""
    import requests
    p = Path(cache_path)
    cache = json.loads(p.read_text()) if p.exists() else {}
    need = [c for c in dict.fromkeys(cusips) if c not in cache]
    hdr = {"Content-Type": "application/json"}
    if api_key:
        hdr["X-OPENFIGI-APIKEY"] = api_key
    step = 100 if api_key else 10
    for i in range(0, len(need), step):
        batch = need[i:i + step]
        body = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]
        r = requests.post("https://api.openfigi.com/v3/mapping", json=body, headers=hdr, timeout=30)
        r.raise_for_status()
        for c, res in zip(batch, r.json()):
            data = res.get("data") or []
            cache[c] = data[0].get("ticker") if data else None
        p.write_text(json.dumps(cache))
        time.sleep(0.3 if api_key else 2.5)
    return {c: cache.get(c) for c in cusips}


def investor_events(diff: pd.DataFrame, cusip_map: dict, source: str, filing_date) -> list:
    """Events dated at the FILING date (when it became public), not the quarter end."""
    ev = []
    for cusip, r in diff.iterrows():
        t = cusip_map.get(cusip)
        if not t or r["action"] == "hold":
            continue
        ev.append({"source": source, "ticker": t, "date": str(pd.Timestamp(filing_date).date()),
                   "action": "buy" if r["action"] in ("new", "added") else "sell"})
    return ev


def track_investor(cik, source: str, ua: str = SEC_UA, figi_key: str | None = None) -> list:
    """End-to-end (network): last two 13F-HR -> diff -> events."""
    f = list_13f(cik, ua, n=2)
    if len(f) < 2:
        return []
    cur = parse_info_table(fetch_info_table_xml(cik, f[0][0], ua))
    prev = parse_info_table(fetch_info_table_xml(cik, f[1][0], ua))
    d = diff_13f(prev, cur)
    return investor_events(d, cusip_to_ticker(list(d.index), api_key=figi_key), source, f[0][1])


# =============================================================== 3. insider clusters
def insider_clusters(tx: pd.DataFrame, asof=None, window_days: int = 30, min_insiders: int = 3,
                     min_total: float = 100_000.0) -> pd.DataFrame:
    """tx columns: ticker, insider, role, date, code, shares, price (Form 4; code 'P' = open-market buy)."""
    asof = pd.Timestamp(asof or pd.Timestamp.today()).normalize()
    d = tx.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d["code"] == "P") & (d["date"] <= asof) & (d["date"] > asof - pd.Timedelta(days=window_days))]
    if d.empty:
        return pd.DataFrame(columns=["ticker", "insiders", "total_value", "n_tx", "senior_buy", "last_date"])
    d = d.assign(value=d["shares"] * d["price"],
                 senior=d["role"].fillna("").str.contains(r"\b(?:CEO|CFO|President|Chair)", case=False, regex=True))
    g = d.groupby("ticker").agg(insiders=("insider", "nunique"), total_value=("value", "sum"),
                                n_tx=("value", "size"), senior_buy=("senior", "any"),
                                last_date=("date", "max"))
    g = g[(g["insiders"] >= min_insiders) & (g["total_value"] >= min_total)]
    return g.sort_values("total_value", ascending=False).reset_index()

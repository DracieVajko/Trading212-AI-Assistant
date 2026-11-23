"""Score past portfolio decisions by comparing stance to subsequent price action.

Reads the ``decisions`` table in ``history/history.db``, fetches the price of
a benchmark (default SPY) at decision time and now, and appends an outcome row
to ``history/decision_outcomes.jsonl``. Never overwrites: a decision is scored
once, then skipped on later runs.

This is the "did the decision age well?" feedback that complements the demo
trade scoring (which is per-trade). It never places orders or changes models.

Usage:
  py -3.12 scripts/score_decisions.py [--benchmark SPY] [--days 1]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
HISTORY_ROOT = ROOT / "history"
DB_PATH = HISTORY_ROOT / "history.db"
OUT_PATH = HISTORY_ROOT / "decision_outcomes.jsonl"


def _load_scored_ids() -> set[int]:
    if not OUT_PATH.exists():
        return set()
    ids: set[int] = set()
    for line in OUT_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(row, dict) and "decision_id" in row:
            try:
                ids.add(int(row["decision_id"]))
            except (TypeError, ValueError):
                pass
    return ids


def _price_at(ticker: str, when: datetime) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(start=when.date().isoformat(),
                                         end=(when + timedelta(days=5)).date().isoformat())
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    try:
        return float(hist["Close"].iloc[0])
    except Exception:
        return None


def _current_price(ticker: str) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(period="5d")
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    try:
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Score past portfolio decisions.")
    ap.add_argument("--benchmark", default="SPY")
    ap.add_argument("--min-age-days", type=int, default=1,
                    help="Only score decisions older than this many days.")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print("no history db"); return 0
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, ts, mode, run_id, symbol, action, reason, confidence FROM decisions ORDER BY id"
    ).fetchall()
    con.close()

    scored = _load_scored_ids()
    now = datetime.now(timezone.utc)
    new_rows: list[dict] = []
    for r in rows:
        did = int(r["id"])
        if did in scored:
            continue
        try:
            when = datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if (now - when).days < args.min_age_days:
            continue
        # Score the symbol's own move for per-symbol decisions; PORTFOLIO uses benchmark.
        scored_symbol = str(r["symbol"] or "").upper()
        ticker = args.benchmark if scored_symbol in ("PORTFOLIO", "", "NONE") else scored_symbol
        # Normalize broker ids like NVDA_US_EQ -> NVDA for yfinance.
        if ticker.endswith("_US_EQ"):
            ticker = ticker[: -len("_US_EQ")]
        entry = _price_at(ticker, when)
        current = _current_price(ticker)
        ret = None
        if entry and current and entry > 0:
            ret = round((current / entry - 1.0) * 100.0, 2)
        # Decision correctness (BUY/SELL/HOLD):
        #  BUY  -> positive return is good.
        #  SELL -> negative return after the sell is good (avoided loss).
        #  HOLD -> flat/small move is good; a large rally is a missed opportunity.
        action = str(r["action"]).upper()
        correct = None
        score = 0.0
        if ret is not None:
            if action == "BUY":
                correct = ret > 0
                score = max(-1.0, min(1.0, ret / 10.0))
            elif action == "SELL":
                correct = ret < 0
                score = max(-1.0, min(1.0, -ret / 10.0))
            else:  # HOLD / anything else
                correct = ret <= 2.0
                if ret > 5.0:
                    score = -min(1.0, (ret - 5.0) / 10.0)
                elif ret < -5.0:
                    score = min(1.0, (abs(ret) - 5.0) / 10.0)
                else:
                    score = 0.5
        new_rows.append({
            "decision_id": did,
            "ts": r["ts"],
            "mode": r["mode"],
            "run_id": r["run_id"],
            "symbol": r["symbol"],
            "action": r["action"],
            "benchmark": args.benchmark,
            "scored_ticker": ticker,
            "price_at_decision": entry,
            "price_now": current,
            "return_pct": ret,
            "correct": correct,
            "score": round(score, 3),
            "scored_at": now.isoformat(),
        })

    if new_rows:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUT_PATH.open("a", encoding="utf-8") as fh:
            for row in new_rows:
                fh.write(json.dumps(row, default=str) + "\n")
        print(f"scored {len(new_rows)} new decisions -> {OUT_PATH}")
    else:
        print("no new decisions to score")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
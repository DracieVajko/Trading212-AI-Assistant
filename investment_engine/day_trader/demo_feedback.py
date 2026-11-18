"""Demo trade feedback: score closed demo trades and feed the outcome back.

The demo branch learns from its own mistakes: every closed trade is scored
(P&L, hold time, risk/reward, stop adherence) and the latest scores are
injected into the next AI prompt as a compact feedback block. A losing trade
therefore becomes a visible "penalty" in the next decision context instead of
being forgotten.

P&L is computed from fill prices in the instrument's quote currency (usually
USD); it is a directional approximation, not an FX-adjusted EUR figure. The
sign and rough magnitude are what the feedback needs; the canonical history
row remains the source of truth.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .score_closed_trades import score_closed_demo_trades

ROOT = Path(__file__).resolve().parents[2]
SCORES_PATH = ROOT / "history" / "demo" / "scores.jsonl"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def normalize_orders(raw: Any) -> list[dict[str, Any]]:
    """Normalize broker order history rows into flat fill records."""
    items = raw.get("items") if isinstance(raw, dict) else raw
    out: list[dict[str, Any]] = []
    for order in items or []:
        if not isinstance(order, dict):
            continue
        qty = _num(order.get("filledQuantity", order.get("quantity", 0)))
        side = str(order.get("side") or "").upper()
        if not side:
            side = "SELL" if qty < 0 else "BUY"
        qty = abs(qty)
        ticker = str(
            order.get("ticker")
            or (order.get("instrument") or {}).get("ticker")
            or ""
        )
        if qty <= 0 or not ticker:
            continue
        price = _num(order.get("price", order.get("fillPrice", 0)))
        value = _num(order.get("filledValue", order.get("value", 0)))
        if not value and price:
            value = price * qty
        out.append({
            "symbol": ticker,
            "side": side,
            "quantity": qty,
            "price": price,
            "value": abs(value),
            "when": order.get("dateExecuted") or order.get("dateModified") or order.get("dateCreated"),
            "type": str(order.get("type") or "").lower(),
            "id": order.get("id"),
        })
    out.sort(key=lambda r: _dt(r.get("when")) or datetime.min.replace(tzinfo=timezone.utc))
    return out


def closed_trades_from_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FIFO-pair BUY and SELL fills per ticker into closed trades."""
    open_lots: dict[str, list[dict[str, Any]]] = {}
    closed: list[dict[str, Any]] = []
    for order in orders:
        sym = order["symbol"]
        if order["side"] == "BUY":
            open_lots.setdefault(sym, []).append(dict(order))
            continue
        qty_left = order["quantity"]
        while qty_left > 0 and open_lots.get(sym):
            lot = open_lots[sym][0]
            take = min(qty_left, lot["quantity"])
            entry_price = _num(lot.get("price"))
            exit_price = _num(order.get("price"))
            pnl = (exit_price - entry_price) * take if entry_price and exit_price else 0.0
            closed.append({
                "symbol": sym,
                "side": "BUY",
                "quantity": take,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_eur": round(pnl, 4),
                "executed_at": lot.get("when"),
                "closed_at": order.get("when"),
                "order_id": order.get("id"),
                "stop_loss_adhered": True if order.get("type") in ("stop", "stop_limit") else None,
                "risk_reward_ratio": 0.0,
            })
            lot["quantity"] -= take
            qty_left -= take
            if lot["quantity"] <= 1e-12:
                open_lots[sym].pop(0)
    return closed


def collect_and_score_demo_trades(
    client: Any,
    *,
    limit: int = 50,
    scores_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Read demo order history, pair closed trades and persist their scores.

    Never raises: broker/network problems yield an empty list so a demo run
    still completes (feedback is an enhancement, not a hard dependency).
    """
    try:
        raw = client.get_order_history(limit=limit)
    except Exception:
        return []
    orders = normalize_orders(raw)
    if not orders:
        return []
    closed = closed_trades_from_orders(orders)
    if not closed:
        return []
    try:
        return score_closed_demo_trades(closed, scores_path=scores_path)
    except Exception:
        return []


def recent_scores(limit: int = 5, path: str | Path | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path is not None else SCORES_PATH
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows[-limit:]


def aggregated_stats(path: str | Path | None = None) -> dict[str, Any]:
    """Aggregate win rate, avg score and best/worst per symbol over all scores."""
    p = Path(path) if path is not None else SCORES_PATH
    if not p.exists():
        return {}
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    if not rows:
        return {}
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol", "?"))
        score = (row.get("demo_score") or {}).get("score", 0)
        net = (row.get("demo_score") or {}).get("breakdown", {}).get("net_pnl_eur", row.get("pnl_eur", 0))
        bucket = by_symbol.setdefault(sym, {"count": 0, "wins": 0, "losses": 0,
                                           "score_sum": 0.0, "pnl_sum": 0.0})
        bucket["count"] += 1
        bucket["score_sum"] += float(score or 0)
        bucket["pnl_sum"] += float(net or 0)
        if float(net or 0) > 0:
            bucket["wins"] += 1
        elif float(net or 0) < 0:
            bucket["losses"] += 1
    for sym, b in by_symbol.items():
        b["win_rate"] = round(b["wins"] / b["count"], 3) if b["count"] else 0.0
        b["avg_score"] = round(b["score_sum"] / b["count"], 4) if b["count"] else 0.0
        b["avg_pnl"] = round(b["pnl_sum"] / b["count"], 2) if b["count"] else 0.0
    total = len(rows)
    total_wins = sum(1 for r in rows if float(((r.get("demo_score") or {}).get("breakdown", {}).get("net_pnl_eur", r.get("pnl_eur", 0)) or 0)) > 0)
    return {
        "total_closed": total,
        "overall_win_rate": round(total_wins / total, 3) if total else 0.0,
        "by_symbol": by_symbol,
    }


def feedback_block(limit: int = 5, path: str | Path | None = None) -> str:
    """Compact prompt block: recent closed demo trades and their scores."""
    rows = recent_scores(limit, path)
    if not rows:
        return ""
    positive = sum(1 for r in rows if _num((r.get("demo_score") or {}).get("score", 0)) > 0)
    negative = len(rows) - positive
    stats = aggregated_stats(path)
    lines = [
        f"DEMO TRADE FEEDBACK (last {len(rows)} closed): {positive} positive, {negative} negative.",
    ]
    if stats:
        lines.append(f"Overall win rate: {stats.get('overall_win_rate', 0)} over {stats.get('total_closed', 0)} closed trades.")
    lines.append("Treat negative outcomes as a penalty: do not repeat the same setup without fresh confirmation.")
    for row in rows:
        score = row.get("demo_score") or {}
        breakdown = score.get("breakdown") or {}
        pnl = breakdown.get("net_pnl_eur", row.get("pnl_eur", 0))
        lesson = row.get("lesson") or ""
        line = (f"- {row.get('symbol')} {row.get('side')}: net {pnl} EUR, "
                f"score {score.get('score')}, horizon {score.get('horizon')}, "
                f"stop adhered {row.get('stop_loss_adhered')}")
        if lesson:
            line += f"\n  LESSON: {lesson}"
        lines.append(line)
    if stats and stats.get("by_symbol"):
        lines.append("Per-symbol stats:")
        for sym, b in stats["by_symbol"].items():
            if b["count"] >= 2:
                lines.append(f"  {sym}: {b['wins']}W/{b['losses']}L win_rate={b['win_rate']} avg_score={b['avg_score']} avg_pnl={b['avg_pnl']}")
    return "\n".join(lines)

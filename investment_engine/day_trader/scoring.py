"""Demo trade scoring — short / medium / long term horizons."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DemoTradeScore:
    symbol: str
    side: str
    horizon: str  # "short" | "medium" | "long"
    score: float
    breakdown: dict[str, float]


def _hold_minutes(executed_at: str, closed_at: str | None) -> int:
    if not closed_at or not executed_at:
        return 0
    start = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
    return max(0, int((end - start).total_seconds() / 60))


def _horizon(minutes: int) -> str:
    if minutes <= 1440:  # <= 1 day
        return "short"
    if minutes <= 43200:  # <= 30 days
        return "medium"
    return "long"


def score_demo_trade(trade: dict) -> DemoTradeScore:
    """Score a demo trade. Returns DemoTradeScore with weighted breakdown.

    Weights: P&L after FX = 0.40, hold time = 0.20, risk:reward = 0.20,
    stop-loss adherence = 0.20. FX fees are subtracted from P&L before
    normalization.
    """
    pnl_eur = float(trade.get("pnl_eur", 0.0) or 0.0)
    fx_fee_eur = float(trade.get("fx_fee_eur", 0.0) or 0.0)
    net_pnl = pnl_eur - fx_fee_eur
    hold_min = _hold_minutes(trade.get("executed_at", ""), trade.get("closed_at"))
    horizon = _horizon(hold_min)
    stop_ok = bool(trade.get("stop_loss_adhered", False))
    rr = float(trade.get("risk_reward_ratio", 0.0) or 0.0)

    W_PNL = 0.40
    W_TIME = 0.20
    W_RR = 0.20
    W_SL = 0.20

    pnl_component = max(-1.0, min(1.0, net_pnl / 100.0))

    if horizon == "short":
        time_component = max(0.0, 1.0 - hold_min / 1440.0)
    elif horizon == "long":
        time_component = min(1.0, hold_min / 43200.0)
    else:
        time_component = 0.5

    rr_component = min(1.0, rr / 2.0) if rr > 0 else 0.0
    sl_component = 1.0 if stop_ok else -1.0

    score = (
        W_PNL * pnl_component
        + W_TIME * time_component
        + W_RR * rr_component
        + W_SL * sl_component
    )

    return DemoTradeScore(
        symbol=str(trade.get("symbol", "UNKNOWN")),
        side=str(trade.get("side", "BUY")),
        horizon=horizon,
        score=round(score, 4),
        breakdown={
            "pnl_component": round(pnl_component, 4),
            "time_component": round(time_component, 4),
            "rr_component": round(rr_component, 4),
            "stop_loss_component": round(sl_component, 4),
            "net_pnl_eur": round(net_pnl, 2),
        },
    )

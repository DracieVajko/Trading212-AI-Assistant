"""Execution guard for day-trader orders."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KILL_SWITCH = "KILL_SWITCH"


@dataclass
class GuardDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate(
    intent: dict[str, Any],
    config: Any,
    env: dict[str, str],
    recon_status: str = "UNKNOWN",
    account_currency: str = "EUR",
    kill_switch_path: str | Path | None = None,
    daily_orders: int = 0,
    daily_loss: float = 0.0,
    allowed_symbols: set[str] | None = None,
) -> GuardDecision:
    reasons: list[str] = []
    exec_cfg = getattr(config, "execution", None)
    if exec_cfg is None:
        return GuardDecision(False, ["no execution config"])

    if not getattr(exec_cfg, "enabled", False):
        reasons.append("execution disabled in config")
    env_name = getattr(exec_cfg, "environment", "demo")
    if env_name == "demo":
        if env.get("T212_DEMO_ORDER_ENABLED") != "1" and env.get("T212_ORDER_ENABLED") != "1":
            reasons.append("T212_DEMO_ORDER_ENABLED not set")
    else:
        if env.get("T212_LIVE_ORDER_ENABLED") != "1":
            reasons.append("T212_LIVE_ORDER_ENABLED not set")
    if env.get("T212_ORDER_ENV", "") != env_name:
        reasons.append("environment mismatch")
    if env_name == "live":
        if env.get("T212_LIVE_ACK") != "I_UNDERSTAND_LIVE_TRADING":
            reasons.append("live ack env missing")
        if env.get("T212_LIVE_ACK") != getattr(exec_cfg, "live_ack", ""):
            reasons.append("live ack mismatch")
        if getattr(exec_cfg, "auto_approve", False):
            reasons.append("auto_approve forbidden in live mode")
    if getattr(exec_cfg, "auto_approve", False) is False and not bool(intent.get("manual_approval")):
        # Unattended runs must not place orders unless explicitly auto-approved.
        reasons.append("auto_approve is false and no manual approval")

    ks = Path(kill_switch_path) if kill_switch_path else None
    if ks is not None and ks.exists():
        reasons.append("kill switch present")

    if str(recon_status).upper() != "PASS":
        reasons.append(f"reconciliation {recon_status}")

    if account_currency.upper() != "EUR":
        reasons.append(f"account currency {account_currency} not supported")

    side = str(intent.get("side", "")).upper()
    if side not in [s.upper() for s in getattr(exec_cfg, "allowed_sides", [])]:
        reasons.append(f"side {side} not allowed")

    unlimited = bool(getattr(exec_cfg, "unlimited", False)) and env_name == "demo"

    try:
        notional = float(intent.get("notional", 0) or 0)
    except (TypeError, ValueError):
        notional = 0.0
    if not unlimited and notional > float(getattr(exec_cfg, "max_order_eur", 0) or 0):
        reasons.append(f"order notional {notional:.2f} exceeds cap")

    if not unlimited and daily_orders >= int(getattr(exec_cfg, "max_daily_orders", 0) or 0):
        reasons.append("daily order limit reached")
    if not unlimited and daily_loss >= float(getattr(config.budget, "max_daily_loss", 0) or 0):
        reasons.append("daily loss limit reached")

    symbol = str(intent.get("symbol", "")).upper()
    if allowed_symbols is not None and symbol not in {s.upper() for s in allowed_symbols}:
        reasons.append(f"symbol {symbol} not in allowed set")

    # Deduplicate reasons while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return GuardDecision(allowed=not unique, reasons=unique)

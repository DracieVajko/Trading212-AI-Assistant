"""PIE-aware portfolio analysis and alert thresholds.

Trading 212 "Pies" are managed baskets (autoinvest). The API cannot buy/sell a
PIE directly, so this module:

  * aggregates every holding (pie + standalone) from the broker snapshot,
  * computes per-position and per-PIE P&L,
  * fires a single alert per threshold breach (take-profit +20% / stop-loss -8%
    by default, or an absolute override per symbol) and re-arms only after the
    position recovers back inside the band,
  * for stop-loss breaches suggests a partial trim (never auto-sells).

Alert state is persisted in ``data/pie_alerts_state.json`` so a re-run does not
spam. Notifications go through ``investment_engine.notifications`` (best-effort,
never raises).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from investment_engine.portfolio import t212_view

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data" / "pie_alerts_state.json"

DEFAULT_TP_PCT = 20.0
DEFAULT_SL_PCT = -8.0


def _state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except OSError as exc:
        logger.debug("pie_alerts: state save failed: %s", exc)


def _position_key(pos: dict) -> str:
    return str(pos.get("symbol") or pos.get("ticker") or "?").upper()


def _pct(pos: dict) -> float:
    try:
        return float(pos.get("pnl_pct", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _value(pos: dict) -> float:
    try:
        return float(pos.get("value_eur", pos.get("value", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _pnl(pos: dict) -> float:
    try:
        return float(pos.get("pnl_eur", pos.get("unrealized_pnl_eur", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _thresholds(pos: dict, config: dict | None) -> tuple[float, float]:
    """Return (take_profit_pct, stop_loss_pct) for a position.

    Supports absolute overrides via config: ``{"AAPL": {"tp_eur": 500, "sl_eur": -100}}``.
    Absolute overrides are converted to a percentage of current value.
    """
    tp = DEFAULT_TP_PCT
    sl = DEFAULT_SL_PCT
    cfg = (config or {}).get(_position_key(pos), {}) if isinstance(config, dict) else {}
    val = _value(pos)
    if isinstance(cfg, dict):
        if "tp_pct" in cfg:
            tp = float(cfg["tp_pct"])
        if "sl_pct" in cfg:
            sl = float(cfg["sl_pct"])
        if "tp_eur" in cfg and val > 0:
            tp = float(cfg["tp_eur"]) / val * 100.0
        if "sl_eur" in cfg and val > 0:
            sl = float(cfg["sl_eur"]) / val * 100.0
    return tp, sl


def analyze_pies(t212_data: dict, config: dict | None = None) -> dict[str, Any]:
    """Build per-PIE and per-position performance summary. Never raises."""
    positions = t212_view.authoritative_positions(t212_data)
    pies: dict[str, list[dict]] = {}
    standalone: list[dict] = []
    for pos in positions:
        pie_name = str(pos.get("pie_name") or "").strip()
        qty_in_pie = pos.get("pie_quantity") or pos.get("quantityInPies") or 0
        try:
            qty_in_pie = float(qty_in_pie)
        except (TypeError, ValueError):
            qty_in_pie = 0.0
        if pie_name and qty_in_pie > 0:
            pies.setdefault(pie_name, []).append(pos)
        else:
            standalone.append(pos)

    pie_summary: dict[str, Any] = {}
    for name, members in pies.items():
        tv = sum(_value(m) for m in members)
        tp = sum(_pnl(m) for m in members)
        pie_summary[name] = {
            "holdings": len(members),
            "value_eur": round(tv, 2),
            "pnl_eur": round(tp, 2),
            "pnl_pct": round(tp / tv * 100.0, 2) if tv else 0.0,
            "top_gainer": max(members, key=lambda m: _pct(m)).get("symbol"),
            "top_loser": min(members, key=lambda m: _pct(m)).get("symbol"),
        }

    return {
        "pies": pie_summary,
        "standalone_count": len(standalone),
        "standalone_value_eur": round(sum(_value(m) for m in standalone), 2),
        "standalone_pnl_eur": round(sum(_pnl(m) for m in standalone), 2),
        "positions": positions,
    }


def check_alerts(t212_data: dict, config: dict | None = None) -> list[dict[str, Any]]:
    """Return list of alert dicts for threshold breaches. Deduped via state file."""
    positions = t212_view.authoritative_positions(t212_data)
    state = _state()
    alerted: dict[str, str] = state.get("alerted", {}) or {}
    alerts: list[dict[str, Any]] = []
    new_alerted: dict[str, str] = dict(alerted)

    for pos in positions:
        sym = _position_key(pos)
        pct = _pct(pos)
        tp, sl = _thresholds(pos, config)
        val = _value(pos)
        pnl = _pnl(pos)

        # Take profit
        tp_key = f"{sym}:tp"
        if pct >= tp:
            if tp_key not in alerted:
                alerts.append({
                    "symbol": sym,
                    "type": "take_profit",
                    "pct": round(pct, 2),
                    "value_eur": round(val, 2),
                    "pnl_eur": round(pnl, 2),
                    "threshold_pct": tp,
                    "message": f"{sym} is up {pct:+.1f}% (>= {tp:.0f}% take-profit). Consider trimming.",
                })
                new_alerted[tp_key] = datetime.now(timezone.utc).isoformat()
        else:
            # re-arm when back below threshold
            new_alerted.pop(tp_key, None)

        # Stop loss
        sl_key = f"{sym}:sl"
        if pct <= sl:
            if sl_key not in alerted:
                alerts.append({
                    "symbol": sym,
                    "type": "stop_loss",
                    "pct": round(pct, 2),
                    "value_eur": round(val, 2),
                    "pnl_eur": round(pnl, 2),
                    "threshold_pct": sl,
                    "message": f"{sym} is down {pct:+.1f}% (<= {sl:.0f}% stop-loss). Consider partial trim; final decision is yours.",
                })
                new_alerted[sl_key] = datetime.now(timezone.utc).isoformat()
        else:
            new_alerted.pop(sl_key, None)

    # Persist state
    state["alerted"] = new_alerted
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    return alerts


def dispatch_alerts(alerts: list[dict[str, Any]]) -> None:
    """Send notifications for alerts. Never raises."""
    if not alerts:
        return
    try:
        from investment_engine.notifications import notify_urgent, notify_debug
    except Exception:
        return
    for a in alerts:
        msg = a["message"]
        if a["type"] == "stop_loss":
            notify_urgent(f"Stop-loss breach: {a['symbol']}", msg)
        else:
            notify_debug(f"Take-profit: {a['symbol']}", msg)


def pie_alert_block(t212_data: dict, config: dict | None = None) -> str:
    """Compact prompt block for PIE/per-position alerts."""
    alerts = check_alerts(t212_data, config)
    if not alerts:
        return ""
    lines = ["PIE / POSITION ALERTS:"]
    for a in alerts:
        lines.append(f"- [{a['type'].upper()}] {a['message']}")
    lines.append("Stop-loss alerts are suggestions only; final decision is yours.")
    return "\n".join(lines)

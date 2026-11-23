"""AI recommendation prompt building.

Extracted from ``main.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from investment_engine.portfolio import t212_view
from investment_engine.providers.generation import _model_for_stage, _try_lmstudio_stage
from investment_engine.run_state import STAGE_ATTRIBUTION as _STAGE_ATTRIBUTION

logger = logging.getLogger(__name__)


def _pie_summary_block(positions: list[dict[str, Any]]) -> str:
    """Compact PIE (Trading 212 basket) performance summary for the prompt."""
    pies: dict[str, list[dict]] = {}
    standalone: list[dict] = []
    for pos in positions or []:
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

    if not pies:
        return ""
    lines = ["PIE (Trading 212 basket) performance:"]
    for name, members in pies.items():
        total_val = sum(float(m.get("value_eur") or 0) for m in members)
        total_pnl = sum(float(m.get("pnl_eur") or 0) for m in members)
        avg_pnl_pct = (total_pnl / total_val * 100.0) if total_val else 0.0
        top_g = max(members, key=lambda m: float(m.get("pnl_pct") or 0))
        top_d = min(members, key=lambda m: float(m.get("pnl_pct") or 0))
        lines.append(
            f"- {name}: {len(members)} holdings, value {total_val:.2f} EUR, "
            f"P&L {total_pnl:+.2f} EUR ({avg_pnl_pct:+.1f}%), "
            f"best {top_g.get('symbol')} ({float(top_g.get('pnl_pct') or 0):+.1f}%), "
            f"worst {top_d.get('symbol')} ({float(top_d.get('pnl_pct') or 0):+.1f}%)"
        )
    if standalone:
        sv = sum(float(m.get("value_eur") or 0) for m in standalone)
        sp = sum(float(m.get("pnl_eur") or 0) for m in standalone)
        lines.append(f"- Standalone (outside pies): {len(standalone)} holdings, value {sv:.2f} EUR, P&L {sp:+.2f} EUR")
    lines.append("Note: PIEs are managed baskets on Trading 212; the API cannot buy/sell a PIE directly. "
                 "Recommend adjusting constituents or pie settings, or buy/sell the underlying tickers outside the pie.")
    return "\n".join(lines)


def _canonical_position(pos: dict) -> dict:
    """Extract canonical normalized position data for LLM prompts."""
    return {
        "symbol": pos.get("symbol"),
        "qty": pos.get("quantity"),
        "value_eur": pos.get("value_eur"),
        "pnl_pct": pos.get("pnl_pct"),
        "average_price_eur": pos.get("average_price_eur"),
        "current_price_eur": pos.get("current_price_eur"),
        "quote_currency": pos.get("quote_currency"),
        "price_unit": pos.get("price_unit"),
        "unrealized_pnl_eur": pos.get("pnl_eur"),
    }


def _build_ai_recommendations(
    regime_result,
    t212_data: dict,
    assets: list[dict[str, Any]],
    provider,
    settings_dict: dict,
    language: str
) -> dict:
    """Generate AI-powered trade recommendations based on regime, portfolio, and free cash."""

    if not regime_result or t212_view.status(t212_data) != "ok":
        return {"error": "Missing regime or T212 data"}

    # Reconciliation guard: account-level derived totals are unreliable when
    # reconciliation fails - but per-position broker data (qty/price/P&L) and cash
    # are still real. Run in degraded mode with a warning note for the LLM
    # instead of skipping AI recommendations entirely.
    reconciliation_ok = t212_view.reconciliation_ok(t212_data)
    recon_note = ""
    if not reconciliation_ok:
        logger.warning("T212 reconciliation FAILED - AI recommendations in degraded mode (position-level data only, no derived account returns)")
        recon_note = "\nWARNING: Account-level derived totals are UNRECONCILED - do NOT use account return figures. Base decisions ONLY on per-position data, regime and news below."

    summary = t212_view.account_summary(t212_data)
    positions = t212_view.authoritative_positions(t212_data)
    cash = t212_view.cash(t212_data)
    free_cash = cash.get("free", 0)
    total_equity = t212_view.total_equity(t212_data)

    pos_summary = []
    for pos in positions:
        canonical = _canonical_position(pos)
        # Validation: quantity > 0 but value_eur is 0 or missing
        if canonical["qty"] and canonical["qty"] > 0 and (canonical["value_eur"] is None or canonical["value_eur"] == 0):
            logger.warning(f"Position validation FAIL: {canonical['symbol']} qty={canonical['qty']} value_eur={canonical['value_eur']}")
            canonical["validation_status"] = "FAIL"
        else:
            canonical["validation_status"] = "PASS"
        pos_summary.append(canonical)

    pie_block = _pie_summary_block(positions)

    regime_summary = {
        "regime": regime_result.regime,
        "confidence": regime_result.confidence,
        "action": regime_result.implications.get("portfolio_action"),
        "cash_target_pct": regime_result.implications.get("cash_target_pct"),
        "dca_multiplier": regime_result.implications.get("dca_multiplier"),
        "tech_allocation": regime_result.implications.get("tech_allocation"),
        "crypto_allocation": regime_result.implications.get("crypto_allocation"),
    }

    key_levels = {
        "support": regime_result.price_structure.nearest_support,
        "resistance": regime_result.price_structure.nearest_resistance,
    }
    support_str = f"{key_levels['support']:.2f}" if key_levels['support'] else 'N/A'
    resistance_str = f"{key_levels['resistance']:.2f}" if key_levels['resistance'] else 'N/A'

    def _threshold(key: str, default: float) -> float:
        try:
            return float((settings_dict or {}).get(key, default))
        except (TypeError, ValueError, AttributeError):
            return default

    buy_threshold = _threshold("buy_threshold", 70)
    sell_threshold = _threshold("sell_threshold", 70)

    # Feed quality + LLM JSON sanitizer wiring happens in caller (main).
    # Build demo/live trade feedback block + earnings calendar.
    demo_feedback = str((t212_data or {}).get("demo_feedback") or "").strip()
    if not demo_feedback:
        try:
            from investment_engine.day_trader.demo_feedback import feedback_block as _dfb
            demo_feedback = _dfb()
        except Exception:
            demo_feedback = ""
    # Collect live-account feedback (read-only) so the live branch also learns.
    try:
        import os as _os
        from pathlib import Path as _Path
        from dotenv import load_dotenv as _ld
        _ld(str(_Path(__file__).resolve().parents[2] / "api.env"))
        from investment_engine.day_trader.broker.t212_orders import T212OrderClient
        from investment_engine.day_trader.demo_feedback import collect_and_score_trades
        _lk = _os.getenv("TRADING212_API_KEY", "")
        _ls = _os.getenv("TRADING212_API_SECRET", "")
        if _lk:
            _live_client = T212OrderClient("live", _lk, _ls)
            collect_and_score_trades(_live_client, mode="live")
    except Exception:
        pass
    try:
        from investment_engine.day_trader.demo_feedback import feedback_block as _dfb
        _live_fb = _dfb(mode="live")
        if _live_fb:
            demo_feedback = (demo_feedback + "\n\n" + _live_fb).strip() if demo_feedback else _live_fb
    except Exception:
        pass
    try:
        from investment_engine.research.earnings_calendar import earnings_block as _eb
        _eblock = _eb()
    except Exception:
        _eblock = ""
    _blocks = [b for b in (demo_feedback, _eblock) if b]
    demo_block = ("\n" + "\n\n".join(_blocks) + "\n") if _blocks else ""

    prompt = f"""You are a portfolio manager. Output ONLY valid JSON with specific trade actions.

PORTFOLIO:{recon_note}
- Equity: {total_equity:,.0f} EUR | Cash: {free_cash:,.0f} EUR | Cash Target: {regime_summary['cash_target_pct']}%
- Regime: {regime_summary['regime']} ({regime_summary['confidence']:.0%}) | Action: {regime_summary['action']}
- DCA Multiplier: {regime_summary['dca_multiplier']}x
- Signal thresholds: BUY at >= {buy_threshold:.0f}% conviction | SELL at >= {sell_threshold:.0f}% conviction
- Tech Allocation: {regime_summary['tech_allocation']} | Crypto: {regime_summary['crypto_allocation']}
- Support: {support_str} | Resistance: {resistance_str}

POSITIONS: {pos_summary}
{pie_block}
{demo_block}

REGIME GUIDANCE: {regime_summary['action']} - Tech: {regime_summary['tech_allocation']}, Crypto: {regime_summary['crypto_allocation']}

KEY LEVELS: support={key_levels['support']}, resistance={key_levels['resistance']}

Respond with JSON only."""

    # NOTE: _model_for_stage and _try_lmstudio_stage are imported for parity with
    # the original main.py wiring; the actual generation happens in the caller.
    _ = (_model_for_stage, _try_lmstudio_stage, _STAGE_ATTRIBUTION)

    return {"prompt": prompt, "pos_summary": pos_summary, "regime_summary": regime_summary}


# Public alias for cross-module use.
build_ai_recommendations = _build_ai_recommendations

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
    # reconciliation fails – but per-position broker data (qty/price/P&L) and cash
    # are still real. Run in degraded mode with a warning note for the LLM
    # instead of skipping AI recommendations entirely.
    reconciliation_ok = t212_view.reconciliation_ok(t212_data)
    recon_note = ""
    if not reconciliation_ok:
        logger.warning("T212 reconciliation FAILED - AI recommendations in degraded mode (position-level data only, no derived account returns)")
        recon_note = "\nWARNING: Account-level derived totals are UNRECONCILED – do NOT use account return figures. Base decisions ONLY on per-position data, regime and news below."
    
    summary = t212_view.account_summary(t212_data)
    positions = t212_view.authoritative_positions(t212_data)
    cash = t212_view.cash(t212_data)
    free_cash = cash.get("free", 0)
    total_equity = t212_view.total_equity(t212_data)
    
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

    def _threshold(key: str, default: float) -> float:
        try:
            return float((settings_dict or {}).get(key, default))
        except (TypeError, ValueError, AttributeError):
            return default

    buy_threshold = _threshold("buy_threshold", 60.0)
    sell_threshold = _threshold("sell_threshold", 65.0)
    
    support_str = f"{key_levels['support']:.2f}" if key_levels['support'] else 'N/A'
    resistance_str = f"{key_levels['resistance']:.2f}" if key_levels['resistance'] else 'N/A'
    
    prompt = f"""You are a portfolio manager. Output ONLY valid JSON with specific trade actions.

PORTFOLIO:{recon_note}
- Equity: {total_equity:,.0f} EUR | Cash: {free_cash:,.0f} EUR | Cash Target: {regime_summary['cash_target_pct']}%
- Regime: {regime_summary['regime']} ({regime_summary['confidence']:.0%}) | Action: {regime_summary['action']}
- DCA Multiplier: {regime_summary['dca_multiplier']}x
- Signal thresholds: BUY at >= {buy_threshold:.0f}% conviction | SELL at >= {sell_threshold:.0f}% conviction
- Tech Allocation: {regime_summary['tech_allocation']} | Crypto: {regime_summary['crypto_allocation']}
- Support: {support_str} | Resistance: {resistance_str}

POSITIONS: {pos_summary}

REGIME GUIDANCE: {regime_summary['action']} - Tech: {regime_summary['tech_allocation']}, Crypto: {regime_summary['crypto_allocation']}

OUTPUT ONLY VALID JSON:
{{
  "portfolio_actions": [{{"action": "hold", "asset": "SYMBOL", "reason": "reason based on regime/indicators/news"}}],
  "trades": [{{"side": "BUY", "asset": "SYMBOL", "qty": 0.0, "price": 0.0, "stop_loss": 0.0, "take_profit": 0.0, "risk_pct": 0.0, "reason": "specific reason: regime/indicators/news"}}],
  "position_updates": [{{"asset": "SYMBOL", "stop_loss": 0.0, "new_stop": 0.0, "take_profit": 0.0, "new_tp": 0.0, "reason": "reason"}}],
  "cash_deployment": {{"free_cash": 0.0, "deploy_amount": 0.0, "deploy_pct": 0.0, "reserve": 0.0, "targets": [{{"asset": "SYMBOL", "amount": 0.0, "price": 0.0, "max_risk": 0.0}}]}}
}}

RULES:
- Max 2% risk per trade, min 1:2 R:R, mandatory stops, 50/50 scale-out
- Only propose BUY/ADD when conviction >= {buy_threshold:.0f}%; only propose SELL/TRIM when conviction >= {sell_threshold:.0f}%
- PEAK_HOLD = prioritize SELLs, reduce new BUYs
- POTENTIAL_ACCUMULATION_ZONE = research accumulation candidates, size any idea per policy
- DECLINING = prepare watchlist, raise cash, no new positions
- NEUTRAL = normal DCA
- Use free cash for deployment, respect cash target
- Base decisions on: regime signals, technical indicators (RSI, MACD, moving averages), news sentiment, earnings
- Be concise, specific, actionable. No hedging language.
- Output ONLY valid JSON, no markdown, no extra text."""

    logger.info(
        "AI recommendations prompt: %d chars (~%d tokens), positions=%d",
        len(prompt), len(prompt) // 4, len(pos_summary),
    )
    try:
        _rec_ctx: dict = {"max_output_tokens": 1024}
        try:
            _rec_model = _model_for_stage(settings_dict, "ai_recommendations")
        except Exception:
            _rec_model = ((settings_dict or {}).get("decision_model")
                          if isinstance(settings_dict, dict)
                          else getattr(settings_dict, "decision_model", None))
        if _rec_model:
            _rec_ctx["model"] = _rec_model
        _rec_served, _rec_direct = (None, None)
        try:
            _rec_served, _rec_direct = _try_lmstudio_stage(provider, prompt, settings=settings_dict,
                                                          stage="ai_recommendations", tokens=1024)
        except Exception:
            _rec_served, _rec_direct = (None, None)
        if _rec_served and _rec_direct:
            result = _rec_direct
            try:
                from investment_engine.providers import attribution as _attr_rec
                _rec_record = _attr_rec.new_stage_record("ai_recommendations",
                                                         model_requested=_rec_served)
                _STAGE_ATTRIBUTION["ai_recommendations"] = _attr_rec.note_chain_winner(
                    _rec_record, "LM Studio", _rec_served, 0)
            except Exception:
                pass
        else:
            result = provider.generate(prompt, stage="ai_recommendations", context=_rec_ctx)
            try:
                from investment_engine.providers import attribution as _attr_rec
                _rec_record = _attr_rec.new_stage_record("ai_recommendations",
                                                         model_requested=_rec_ctx.get("model", ""))
                _STAGE_ATTRIBUTION["ai_recommendations"] = _attr_rec.apply_chain_hint(_rec_record, provider)
            except Exception:
                pass
        # Clean up response - remove any markdown code fences or extra text
        cleaned = result.strip()
        # Remove markdown code fences if present
        cleaned = cleaned.removeprefix("```json")
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.removesuffix("```")
        cleaned = cleaned.strip()
        # Use the new schema validation
        from investment_engine.schemas.ai_recommendations import (
            parse_ai_recommendations,
        )
        return parse_ai_recommendations(cleaned)
    except Exception as e:
        return {"error": f"AI recommendation failed: {e!s}", "raw_response": result[:500] if 'result' in locals() else "no response"}

# Public aliases for cross-module use (private names remain the
# implementation detail and stay available for in-module calls).
build_ai_recommendations = _build_ai_recommendations

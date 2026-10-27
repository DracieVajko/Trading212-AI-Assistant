"""Phase 7 action ladder: graduated exits instead of all-or-nothing.

Deterministic code (no LLM). For one held position and one verdict reason,
produces a sell ladder: which fraction now, what remains conditional, what
triggers the next tranche, and where the proceeds go.

Verdict reasons (AGENTS 10.9 subset implemented here):
  thesis_broken | thesis_weakened | concentration_over_cap |
  valuation_stretched | tactical_invalidation | better_alternative | cash_needed

Hard rules (no exceptions):
- A price decline alone, a gain alone, RSI extreme alone, or P&L vs cost
  basis are NEVER reasons. The caller supplies the reason; this module only
  sizes its consequence.
- No stop-based number is presented as a guaranteed maximum loss.
- Advisory output only ("not executed"); no order fields, no broker calls.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

VALID_REASONS = frozenset({
    "thesis_broken",
    "thesis_weakened",
    "concentration_over_cap",
    "valuation_stretched",
    "tactical_invalidation",
    "better_alternative",
    "cash_needed",
})

# Review horizons per reason (calendar days from the report date).
REVIEW_DAYS = {
    "thesis_broken": 0,
    "thesis_weakened": 30,
    "concentration_over_cap": 30,
    "valuation_stretched": 90,
    "tactical_invalidation": 14,
    "better_alternative": 30,
    "cash_needed": 7,
}

# Broker quantity precision (fractional-share venues).
QTY_PRECISION = 8


def round_qty(quantity: float) -> float:
    """Round down to broker-allowed precision (never round UP a sale)."""
    import math

    try:
        factor = 10 ** QTY_PRECISION
        return math.floor(float(quantity) * factor) / factor
    except (TypeError, ValueError):
        return 0.0


def load_trading_costs(path: str | None = None) -> tuple[float | None, float]:
    """Read (max_cost_pct, min_trade_value_eur) from the user profile.

    Returns (None, 1.0) when unconfigured: the cost gate then reports
    "unevaluable" instead of inventing a threshold. Never raises.
    """
    default_min = 1.0
    try:
        if not path:
            return None, default_min
        import yaml  # type: ignore

        with open(path, encoding="utf-8") as fh:
            profile = yaml.safe_load(fh) or {}
        costs = (profile or {}).get("trading_costs", {}) or {}
        max_pct = costs.get("max_cost_pct", None)
        min_val = costs.get("min_trade_value_eur", default_min)
        try:
            max_pct = float(max_pct) if max_pct is not None else None
        except (TypeError, ValueError):
            max_pct = None
        try:
            min_val = float(min_val)
        except (TypeError, ValueError):
            min_val = default_min
        return max_pct, min_val
    except Exception:
        return None, default_min


def tax_note_for(tax_facts: dict | None, holding_days: int | None = None) -> str:
    """One-line tax/holding-period note. 'unverified' when facts are missing."""
    facts = tax_facts if isinstance(tax_facts, dict) else {}
    holding_note = ""
    if isinstance(holding_days, (int, float)) and holding_days >= 0:
        holding_note = f"held ~{int(holding_days)}d; "
    for key in ("capital_gains", "holding_period", "withholding"):
        val = facts.get(key) if isinstance(facts, dict) else None
        if isinstance(val, str) and val and "unverified" not in val.lower():
            return f"{holding_note}{key}: {val[:120]}"
    return (holding_note or "") + "unverified: check the Slovak Financial Administration or a tax advisor"


def build_ladder(*,
                 ticker: str,
                 reason: str,
                 weight_pct: float,
                 cap_pct: float,
                 position_value_eur: float,
                 total_equity_eur: float,
                 quantity: float,
                 price_eur: float,
                 report_day: str = "",
                 target_weight_pct: float | None = None,
                 tranche2_trigger: dict[str, Any] | None = None,
                 cash_need_eur: float | None = None,
                 max_cost_pct: float | None = None,
                 min_trade_value_eur: float = 1.0,
                 fee_per_trade_eur: float = 0.0,
                 spread_bps: float = 0.0,
                 tax_facts: dict | None = None,
                 holding_days: int | None = None,
                 thesis_note: str = "") -> dict[str, Any]:
    """Build a graduated sell ladder for one held position. Never raises.

    Returns a dict with fraction_to_sell, quantity, estimated proceeds,
    cost %, tax note, lot rule, post-trade weights, tranche-2 trigger,
    wait branch, review date, materiality verdict and proceeds destination
    ranking. `action` is TRIM (partial), EXIT (100%) or HOLD; never AVOID
    (that verdict is for non-held candidates only).
    """
    try:
        return _build_ladder(
            ticker=ticker, reason=reason, weight_pct=weight_pct, cap_pct=cap_pct,
            position_value_eur=position_value_eur, total_equity_eur=total_equity_eur,
            quantity=quantity, price_eur=price_eur, report_day=report_day,
            target_weight_pct=target_weight_pct, tranche2_trigger=tranche2_trigger,
            cash_need_eur=cash_need_eur, max_cost_pct=max_cost_pct,
            min_trade_value_eur=min_trade_value_eur, fee_per_trade_eur=fee_per_trade_eur,
            spread_bps=spread_bps, tax_facts=tax_facts, holding_days=holding_days,
            thesis_note=thesis_note)
    except Exception as exc:
        return {"ticker": str(ticker or "?").upper(), "reason": str(reason or "?"),
                "action": "HOLD", "error": f"ladder failed safely: {type(exc).__name__}"}


def _build_ladder(*, ticker: str, reason: str, weight_pct: float, cap_pct: float,
                  position_value_eur: float, total_equity_eur: float,
                  quantity: float, price_eur: float, report_day: str,
                  target_weight_pct: float | None, tranche2_trigger: dict | None,
                  cash_need_eur: float | None, max_cost_pct: float | None,
                  min_trade_value_eur: float, fee_per_trade_eur: float,
                  spread_bps: float, tax_facts: dict | None,
                  holding_days: int | None, thesis_note: str) -> dict[str, Any]:
    ticker = str(ticker or "?").upper()
    reason = str(reason or "")
    if reason not in VALID_REASONS:
        return {"ticker": ticker, "reason": reason, "action": "HOLD",
                "verdict": "NO_ACTIONABLE_REASON",
                "note": f"unknown reason '{reason}'; no ladder without a valid verdict class"}
    try:
        weight = max(0.0, float(weight_pct or 0.0))
        cap = max(0.0, float(cap_pct or 0.0))
        position = max(0.0, float(position_value_eur or 0.0))
        equity = max(0.0, float(total_equity_eur or 0.0))
        qty = max(0.0, float(quantity or 0.0))
        price = max(0.0, float(price_eur or 0.0))
    except (TypeError, ValueError):
        return {"ticker": ticker, "reason": reason, "action": "HOLD",
                "verdict": "NO_ACTIONABLE_REASON", "note": "non-numeric inputs"}

    try:
        base_day = date.fromisoformat(str(report_day)[:10])
    except (ValueError, TypeError):
        from datetime import date as _d
        base_day = _d.today()
    review_after = (base_day + timedelta(days=REVIEW_DAYS[reason])).isoformat()

    # --- Fraction + target per verdict class (mechanical, no judgment) ---
    if reason == "concentration_over_cap":
        cap_value = cap / 100.0 * equity if equity > 0 else 0.0
        sell_value = max(0.0, position - cap_value)
        fraction = (sell_value / position) if position > 0 else 0.0
        wait = (f"hold remaining {position - sell_value:,.2f} EUR "
                f"({cap:.1f}% cap); re-check after rebalancing or material weight change")
        trigger2 = tranche2_trigger
    elif reason == "valuation_stretched":
        target = target_weight_pct if target_weight_pct is not None else max(0.0, weight * 0.75)
        target_value = float(target) / 100.0 * equity if equity > 0 else position * 0.75
        sell_value = max(0.0, min(position, position - target_value))
        if sell_value <= 0:
            # Fall back to the 25% guideline trim when no target binds.
            sell_value = position * 0.25
        fraction = (sell_value / position) if position > 0 else 0.0
        wait = ("hold remainder; re-add only on a defined re-add trigger "
                "(valuation re-rating or confirmed catalyst)")
        trigger2 = tranche2_trigger or {"metric": "price_or Thesis",
                                        "operator": "reassess-at",
                                        "level": "re-add trigger (define before acting)",
                                        "source": "analyst/price action",
                                        "check_date": review_after}
    elif reason == "thesis_weakened":
        sell_value = position * 0.5
        fraction = 0.5 if position > 0 else 0.0
        wait = "hold remaining 50% unless a downgrade trigger fires; then exit the rest"
        trigger2 = tranche2_trigger or {"metric": "downgrade_event",
                                        "operator": "fires",
                                        "level": "thesis-invalidating development",
                                        "source": "news/analyst",
                                        "check_date": review_after}
    elif reason == "thesis_broken":
        sell_value = position
        fraction = 1.0 if position > 0 else 0.0
        wait = "no wait branch: full exit (execution may split for liquidity only, never to wait for a bounce)"
        trigger2 = None
    elif reason == "tactical_invalidation":
        sell_value = position * 0.5
        fraction = 0.5 if position > 0 else 0.0
        wait = "hold remaining 50% for the second structural breach; P&L vs cost never triggers"
        trigger2 = tranche2_trigger or {"metric": "structure",
                                        "operator": "second-breach",
                                        "level": "next invalidation level",
                                        "source": "technical",
                                        "check_date": review_after}
    elif reason in ("better_alternative", "cash_needed"):
        need = float(cash_need_eur) if cash_need_eur is not None else None
        if need is None and target_weight_pct is None:
            return {"ticker": ticker, "reason": reason, "action": "HOLD",
                    "verdict": "NEEDS_TARGET",
                    "note": ("no cash target and no target weight supplied — "
                             "research-only until the rotation size is defined"),
                    "review_after": review_after}
        if need is not None:
            sell_value = max(0.0, min(position, need))
        else:
            target_value = float(target_weight_pct) / 100.0 * equity if equity > 0 else 0.0
            sell_value = max(0.0, position - target_value)
        fraction = (sell_value / position) if position > 0 else 0.0
        wait = "remainder held; redeploy only into candidates that pass the full buy gate"
        trigger2 = tranche2_trigger
    else:  # pragma: no cover - guarded by VALID_REASONS above
        sell_value, fraction, wait, trigger2 = 0.0, 0.0, "", None

    sell_qty = round_qty(qty * fraction) if qty > 0 else 0.0
    # Proceeds from the rounded quantity at the snapshot price.
    proceeds = round(sell_qty * price, 2) if price > 0 else round(sell_value, 2)
    try:
        cost_eur = float(fee_per_trade_eur or 0.0) + proceeds * float(spread_bps or 0.0) / 10000.0
    except (TypeError, ValueError):
        cost_eur, fee_per_trade_eur, spread_bps = 0.0, 0.0, 0.0
    cost_pct = (cost_eur / proceeds * 100.0) if proceeds > 0 else 0.0
    cost_assessed = bool(fee_per_trade_eur or spread_bps)

    keep_value = round(position - proceeds, 2)
    keep_weight = (keep_value / equity * 100.0) if equity > 0 else 0.0

    # --- Materiality gate ---
    if proceeds < float(min_trade_value_eur or 0.0):
        return {"ticker": ticker, "reason": reason, "action": "HOLD",
                "verdict": "BELOW_MATERIALITY",
                "note": (f"trade value €{proceeds:,.2f} below minimum "
                         f"€{float(min_trade_value_eur or 0.0):,.2f}: no action"),
                "fraction_to_sell": 0.0, "review_after": review_after}
    if max_cost_pct is not None and cost_assessed and cost_pct > float(max_cost_pct):
        return {"ticker": ticker, "reason": reason, "action": "HOLD",
                "verdict": "BELOW_MATERIALITY",
                "note": (f"estimated cost {cost_pct:.2f}% exceeds cap "
                         f"{float(max_cost_pct):.2f}%: no action"),
                "fraction_to_sell": 0.0, "review_after": review_after}

    action = "EXIT" if fraction >= 1.0 else ("TRIM" if fraction > 0 else "HOLD")
    return {
        "ticker": ticker,
        "reason": reason,
        "action": action,
        "verdict": "PLAN",
        "fraction_to_sell": round(fraction, 4),
        "quantity": sell_qty,
        "quantity_held": round(max(0.0, qty - sell_qty), 8),
        "estimated_proceeds_eur": proceeds,
        "estimated_cost_eur": round(cost_eur, 2),
        "estimated_cost_pct": round(cost_pct, 3),
        "cost_basis_note": ("no fee schedule configured — cost unassessed"
                            if not cost_assessed else "fee + spread estimate"),
        "tax_note_per_lot": tax_note_for(tax_facts if isinstance(tax_facts, dict) else None,
                                         holding_days),
        "lots_first": ("FIFO assumed; single-lot approximation "
                       "(quantity + average price only — no lot breakdown available)"),
        "post_trade_value_eur": keep_value,
        "post_trade_weight_pct": round(keep_weight, 2),
        "cap_pct": cap,
        "within_cap_after": keep_weight <= cap + 1e-9,
        "tranche_2_trigger": trigger2,
        "wait_branch": wait,
        "review_after": review_after,
        "thesis_note": thesis_note or "",
        "proceeds_destinations": rank_destinations(
            free_cash_eur=None, underweights=None, broad_fund_ok=False,
            capped_holdings=None, thesis_intact=True),
    }


def rank_destinations(free_cash_eur: float | None = None,
                      underweights: list[dict] | None = None,
                      broad_fund_ok: bool = False,
                      capped_holdings: list[str] | None = None,
                      thesis_intact: bool = True) -> list[dict]:
    """Ranked proceeds destinations. Non-cash entries are candidates only —
    each must pass the full buy gate before becoming a recommendation.
    """
    out = [{
        "rank": 1,
        "destination": "hold_cash",
        "status": "DEFAULT",
        "condition_to_change": ("deploy when a gated BUY candidate appears; "
                                "otherwise cash waits"),
    }]
    rank = 2
    for uw in (underweights or []):
        if isinstance(uw, dict) and uw.get("ticker"):
            out.append({"rank": rank, "destination": f"underweight:{uw['ticker']}",
                        "status": "CANDIDATE_NOT_EVALUATED",
                        "condition_to_change": "must pass the full buy gate first"})
            rank += 1
    if broad_fund_ok:
        out.append({"rank": rank, "destination": "broad_low_cost_fund",
                    "status": "CANDIDATE_NOT_EVALUATED",
                    "condition_to_change": "must pass the full buy gate first"})
        rank += 1
    if thesis_intact:
        for holding in (capped_holdings or []):
            out.append({"rank": rank, "destination": f"existing_holding:{holding}",
                        "status": "CANDIDATE_NOT_EVALUATED",
                        "condition_to_change": "must be under cap with intact thesis + pass buy gate"})
            rank += 1
    return out

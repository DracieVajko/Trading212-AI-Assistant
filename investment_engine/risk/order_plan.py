"""Phase 7 advisory order plans. INFORMATIONAL ONLY — never executed.

Every plan carries human_confirmation_required=true and the advisory guard.
No venue, order-type, or execution fields exist by design. This module must
never gain network/client imports (guarded by tests).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ADVISORY_GUARD = "> Advisory only — not executed. Confirm manually outside this program."

_GROUP_SLEEVE = {
    "TECH_PIE": "thematic",
    "SHORT_TERM_TRADING": "tactical",
    "LONG_RUN_DCA": "long_term",
    "CRYPTO": "crypto",
}


def sleeve_for_group(group: str | None) -> str:
    return _GROUP_SLEEVE.get(str(group or "").upper(), "unknown")


#: Plans below this notional are noise, not advice (probed 2026-10-10:
#: "EGT TRIM ~€0.00"). Such decisions land in `blocked` with a reason.
MIN_NOTIONAL_EUR = 1.00


def trim_sizing_eur(*, weight_pct: float, cap_pct: float, total_equity: float,
                    policy: dict[str, Any]) -> dict[str, Any]:
    """Position-based TRIM sizing (BUY headroom math does not apply to sells).

    Overweight → trim-to-cap exceedance; otherwise a policy fraction of the
    position (trims.trim_fraction_pct, default 50.0). Never negative.
    """
    try:
        equity = max(0.0, float(total_equity))
    except (TypeError, ValueError):
        equity = 0.0
    try:
        position_value = max(0.0, float(weight_pct) / 100.0 * equity)
    except (TypeError, ValueError):
        position_value = 0.0
    try:
        cap_value = max(0.0, float(cap_pct)) / 100.0 * equity
    except (TypeError, ValueError):
        cap_value = 0.0
    if position_value > cap_value:
        return {"notional_eur": round(position_value - cap_value, 2),
                "binding_constraint": "trim-to-cap",
                "inputs": {"position_value_eur": round(position_value, 2),
                           "cap_value_eur": round(cap_value, 2)}}
    _frac_raw = (policy.get("trims", {}) or {}).get("trim_fraction_pct", 50.0)
    try:
        frac = 50.0 if _frac_raw is None else float(_frac_raw)
    except (TypeError, ValueError):
        frac = 50.0
    return {"notional_eur": round(position_value * frac / 100.0, 2),
            "binding_constraint": "trim-fraction",
            "inputs": {"position_value_eur": round(position_value, 2),
                       "trim_fraction_pct": frac}}


def build_plans(*, committee_decisions: list[dict[str, Any]],
                portfolio_rows: list[dict[str, Any]],
                recon_status: str, free_cash: float, total_equity: float,
                earnings_status: dict[str, Any], report_day: str,
                news_events: list[dict[str, Any]], regime: str,
                risk_posture: str, policy: dict[str, Any],
                sleeves: dict[str, str] | None = None,
                sector_headroom_eur: float = float("inf"),
                hold_thesis: dict[str, Any] | None = None,
                upstream_ok: bool = True) -> dict[str, Any]:
    """Build advisory plans for committee BUY/TRIM decisions that pass gates.

    upstream_ok=False means the committee skill failed upstream, so an empty
    decision list is UPSTREAM_SKILL_FAILURE, not "no candidates".
    """
    from investment_engine.risk import eligibility as _elig
    from investment_engine.risk import sizing as _sizing
    from investment_engine.risk.policy import REQUIRES_USER_VALUE, is_deferred

    sleeves = sleeves or {}
    profile_block = (policy.get("profile")
                     if isinstance(policy.get("profile"), dict) else {})
    profile_name = str(profile_block.get("name") or "custom")
    profile_buy_sleeves = {str(s) for s in (profile_block.get("allowed_buy_sleeves") or [])}
    profile_sell_sleeves = {str(s) for s in (profile_block.get("allowed_sell_sleeves") or [])}
    profile_allow_sells = bool(profile_block.get("allow_sells", True))
    risk_pct = float(policy.get("risk_per_trade_pct", 2.0) or 2.0)
    adverse = float(policy.get("adverse_move_assumption", 0.25) or 0.25)
    eb = policy.get("earnings_blackout", {}) or {}
    cap_default = float((policy.get("concentration", {}) or {}).get("default_max_position_pct", 20.0) or 20.0)
    stops_scope = str((policy.get("stops", {}) or {}).get("scope", "tactical-only"))
    core_trims = (policy.get("core_trims", REQUIRES_USER_VALUE))

    cash_cfg = policy.get("cash", {}) or {}
    funding_cfg = policy.get("funding", {}) or {}
    allow_trim_funding = bool(funding_cfg.get("allow_trim_funding", False))
    if "fund_buys_from_planned_trims" in cash_cfg:
        allow_trim_funding = bool(cash_cfg.get("fund_buys_from_planned_trims"))
    try:
        reserve_pct = float(cash_cfg.get("mandatory_floor_pct", 0.0) or 0.0)
    except (TypeError, ValueError):
        reserve_pct = 0.0
    reserve_eur = max(0.0, reserve_pct / 100.0 * max(0.0, float(total_equity or 0.0)))
    avg_cfg = policy.get("averaging_down", {}) or {}
    avg_sleeves = {str(s) for s in (avg_cfg.get("allowed_sleeves") or
                                    ["long_term", "core", "thematic"])}
    avg_tickers = {str(t).upper() for t in (avg_cfg.get("allowed_tickers") or [])}
    require_thesis_avg = bool(avg_cfg.get("require_hold_thesis", True))
    _thesis_all = hold_thesis if isinstance(hold_thesis, dict) else {}

    rows = {str(r.get("display_symbol") or r.get("ticker") or "").upper(): r
            for r in (portfolio_rows or []) if isinstance(r, dict)}
    plans, blocked = [], []
    decisions_in = [d for d in (committee_decisions or []) if isinstance(d, dict)]
    if not decisions_in and not upstream_ok:
        evaluation_status = "UPSTREAM_SKILL_FAILURE"
    elif not decisions_in:
        evaluation_status = "NO_CANDIDATES_PRODUCED"
    else:
        evaluation_status = ""  # decided below after gate evaluation

    def _attempt(decision: dict[str, Any], direction: str,
                 cash_available: float) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Evaluate one decision; returns (plan, blocked_entry)."""
        ticker = str(decision.get("ticker", "")).upper()
        row = rows.get(ticker)
        if row is None:
            return None, {"ticker": ticker, "reason": "not an owned holding"}
        sleeve = (sleeves or {}).get(ticker, "unknown")
        # User-declared hold thesis: never plan an exit on a thesis ticker.
        _note = _thesis_all.get(ticker)
        if direction == "TRIM" and _note:
            return None, {"ticker": ticker, "reason": f"hold-thesis — HOLD ({_note})"}
        # Deferred: core trim permission unknown → HOLD+REVIEW text, no plan.
        if direction == "TRIM" and sleeve in ("long_term", "core") and is_deferred(core_trims):
            return None, {"ticker": ticker,
                          "reason": "core trim permission pending user confirmation — HOLD+REVIEW"}
        # Deferred: unknown sleeve → research only (no sizing guesses).
        if sleeve == "unknown":
            return None, {"ticker": ticker, "reason": "sleeve unknown — research only, no sizing"}
        # Profile overlay: select the sleeves this strategy may touch. A
        # profile can block a candidate, never create one.
        if direction == "TRIM":
            if not profile_allow_sells:
                return None, {"ticker": ticker, "source": "profile",
                              "direction": direction,
                              "reason": f"profile '{profile_name}': exits are manual only"}
            if profile_sell_sleeves and sleeve not in profile_sell_sleeves:
                return None, {"ticker": ticker, "source": "profile",
                              "direction": direction,
                              "reason": f"profile '{profile_name}' does not sell sleeve={sleeve}"}
        elif profile_buy_sleeves and sleeve not in profile_buy_sleeves:
            return None, {"ticker": ticker, "source": "profile",
                          "direction": direction,
                          "reason": (f"profile '{profile_name}' adds only to: "
                                     f"{', '.join(sorted(profile_buy_sleeves))}")}
        try:
            weight = float(row.get("weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0.0
        needs_levels = sleeve == "tactical" and "tactical" in stops_scope
        gates = _elig.evaluate(
            direction, ticker=ticker, recon_status=recon_status, free_cash=cash_available,
            weight=weight, cap_pct=cap_default, earnings_status=earnings_status,
            report_day=report_day, before_bdays=int(eb.get("before_bdays", 5) or 5),
            after_bdays=int(eb.get("after_bdays", 2) or 2),
            mapping_status=str(row.get("external_mapping_status", "")),
            needs_levels=needs_levels, news_events=news_events, regime=regime,
            risk_posture=risk_posture, sleeve=sleeve)
        failed = [g for g in gates if not g["pass"]]
        # Mapping gate downgrades levels to RESEARCH instead of blocking outright.
        hard_failed = [g for g in failed if g["rule"] != "mapping-verified"]
        if hard_failed:
            return None, {"ticker": ticker,
                          "reason": "; ".join(f"{g['rule']}: {g['reason']}" for g in hard_failed)}
        sizing = _sizing.indicative_notional_eur(
            weight_pct=weight, cap_pct=cap_default, total_equity=total_equity,
            risk_pct=risk_pct, adverse_move=adverse,
            sector_headroom_eur=sector_headroom_eur, deployable_cash_eur=cash_available)
        if direction == "TRIM":
            # Sells are not funded by cash: size from the position itself.
            sizing = trim_sizing_eur(weight_pct=weight, cap_pct=cap_default,
                                     total_equity=total_equity, policy=policy)
            if sizing["notional_eur"] < MIN_NOTIONAL_EUR:
                return None, {"ticker": ticker,
                              "reason": f"trim size below minimum (€{sizing['notional_eur']:,.2f})"}
        tech = {}
        stop_hint = limit_hint = None
        if needs_levels and all(g["pass"] for g in gates if g["rule"] == "mapping-verified"):
            stop_hint, limit_hint = "from canonical Support", "from canonical Resistance"
        rationale = [e for e in (decision.get("basis", []) or [])]
        for event in news_events or []:
            if isinstance(event, dict) and str(event.get("ticker", "")).upper() == ticker:
                rationale.extend(str(i) for i in event.get("item_ids", [])[:2])
        plan: dict[str, Any] = {
            "ticker": ticker,
            "direction": direction,
            "indicative_notional_eur": sizing["notional_eur"],
            "binding_constraint": sizing["binding_constraint"],
            "sizing_inputs": sizing["inputs"],
            "stop_hint": stop_hint,
            "limit_hint": limit_hint,
            "expires": "next scheduled run",
            "rationale_ids": rationale[:6],
            "policy_checks": gates,
            "confidence": 0.55,
            "sleeve": sleeve,
            "human_confirmation_required": True,
        }
        # Phase 7 ladder detail (additive, never changes the plan itself).
        # Verdict class is derived from the decision + gate context, never
        # from price moves or RSI alone.
        if direction == "TRIM":
            try:
                from investment_engine.risk import action_ladder as _lad
                _reason = "concentration_over_cap" if weight > cap_default else "thesis_weakened"
                _row_qty = float(row.get("quantity", 0) or 0.0)
                _row_px = float(row.get("current_price_eur", 0) or row.get("price_eur", 0) or 0.0)
                _ladder = _lad.build_ladder(
                    ticker=ticker, reason=_reason, weight_pct=weight, cap_pct=cap_default,
                    position_value_eur=float(row.get("market_value", row.get("value_eur", 0)) or 0.0),
                    total_equity_eur=float(total_equity or 0.0),
                    quantity=_row_qty, price_eur=_row_px,
                    report_day=str(report_day or ""))
                plan["ladder"] = {k: v for k, v in _ladder.items()
                                  if k not in ("proceeds_destinations",)}
            except Exception:
                pass
            # Funding transparency (advisory only): what the sale would free.
            plan["estimated_proceeds_eur"] = plan["indicative_notional_eur"]
            try:
                _mv = float(row.get("market_value", row.get("value_eur", 0)) or 0.0)
                _upnl = float(row.get("unrealized_pnl", 0) or 0.0)
                if _mv > 0:
                    plan["realizes_pnl_estimate_eur"] = round(
                        _upnl * min(1.0, plan["indicative_notional_eur"] / _mv), 2)
            except (TypeError, ValueError):
                pass
        return plan, None

    trim_decisions, buy_decisions = [], []
    for decision in decisions_in:
        action = str(decision.get("action", "HOLD")).upper()
        if action in ("TRIM", "SELL"):
            trim_decisions.append(decision)
        elif action in ("BUY", "ACCUMULATE"):
            buy_decisions.append(decision)

    # Phase 1: valid trims first — their proceeds are the only funding the
    # policy may release for adds (never margin, never imaginary cash).
    trim_tickers: set[str] = set()
    trim_proceeds = 0.0
    for decision in trim_decisions:
        plan, blk = _attempt(decision, "TRIM", free_cash)
        if blk:
            blocked.append(blk)
        if plan:
            plans.append(plan)
            trim_tickers.add(plan["ticker"])
            trim_proceeds += float(plan.get("indicative_notional_eur") or 0.0)

    # Phase 2: buys share one pool: free cash (minus the policy floor) plus
    # trim proceeds when the policy allows it. Never overcommit the pool.
    pool = max(0.0, float(free_cash or 0.0) - reserve_eur)
    if allow_trim_funding:
        pool += trim_proceeds
    allocated = 0.0
    for decision in buy_decisions:
        ticker = str(decision.get("ticker", "")).upper()
        if ticker in trim_tickers:
            blocked.append({"ticker": ticker,
                            "reason": "same-ticker trim+buy churn — choose one direction"})
            continue
        row = rows.get(ticker)
        if row is not None:
            try:
                pnl_pct = float(row.get("pnl_pct", 0) or 0.0)
            except (TypeError, ValueError):
                pnl_pct = 0.0
            if pnl_pct < 0:
                sleeve = (sleeves or {}).get(ticker, "unknown")
                if sleeve not in avg_sleeves:
                    blocked.append({"ticker": ticker,
                                    "reason": f"averaging down not allowed for sleeve={sleeve}"})
                    continue
                if avg_tickers:
                    if ticker not in avg_tickers:
                        blocked.append({"ticker": ticker,
                                        "reason": "averaging down not allowed: ticker not in "
                                                  "policy averaging_down.allowed_tickers"})
                        continue
                elif require_thesis_avg and not _thesis_all.get(ticker):
                    blocked.append({"ticker": ticker,
                                    "reason": "averaging down requires a declared hold thesis"})
                    continue
        available = max(0.0, pool - allocated)
        plan, blk = _attempt(decision, "BUY", available)
        if blk:
            blocked.append(blk)
        if plan:
            plan["funding"] = {
                "free_cash_eur": round(float(free_cash or 0.0), 2),
                "trim_proceeds_eur": round(trim_proceeds if allow_trim_funding else 0.0, 2),
                "reserve_eur": round(reserve_eur, 2),
                "available_pool_eur": round(pool, 2),
                "source": ("planned_trims" if allow_trim_funding and trim_proceeds > 0
                           else "free_cash"),
            }
            plans.append(plan)
            allocated += float(plan.get("indicative_notional_eur") or 0.0)

    if not evaluation_status:
        if plans:
            evaluation_status = "PLANS_GENERATED"
        elif blocked:
            evaluation_status = "ALL_BLOCKED"
        else:
            evaluation_status = "NO_ACTIONABLE_SIGNAL"
    profile_blocked = [b for b in blocked if b.get("source") == "profile"]
    profile_effects = {
        "buy_candidates_blocked": sum(1 for b in profile_blocked
                                      if b.get("direction") == "BUY"),
        "sell_candidates_blocked": sum(1 for b in profile_blocked
                                       if b.get("direction") == "TRIM"),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "advisory_guard": ADVISORY_GUARD,
        "plans": plans,
        "blocked": blocked,
        "evaluation_status": evaluation_status,
        "decisions_received": len(decisions_in),
        "policy_profile": profile_block,
        "profile_effects": profile_effects,
        "funding": {
            "trim_funding_enabled": allow_trim_funding,
            "free_cash_eur": round(float(free_cash or 0.0), 2),
            "trim_proceeds_eur": round(trim_proceeds, 2),
            "reserve_eur": round(reserve_eur, 2),
            "deployable_pool_eur": round(pool, 2),
        },
        "policy_version": str(policy.get("policy_version", "")),
    }


def render(bundle: dict[str, Any]) -> str:
    """Markdown section for the AI context file (never the human brief)."""
    from investment_engine.risk.profiles import describe_line

    lines = ["## Advisory Order Plans (not executed)", ADVISORY_GUARD, ""]
    profile = bundle.get("policy_profile") or {}
    if isinstance(profile, dict) and profile:
        lines += [describe_line(profile), ""]
    for plan in bundle.get("plans", []) or []:
        lines.append(
            f"- **{plan.get('ticker')}** {plan.get('direction')} "
            f"~€{plan.get('indicative_notional_eur', 0):,.2f} "
            f"(binding: {plan.get('binding_constraint')}, sleeve: {plan.get('sleeve')})")
    for blocked in bundle.get("blocked", []) or []:
        lines.append(f"- {blocked.get('ticker')}: no plan — {blocked.get('reason')}")
    if not bundle.get("plans") and not bundle.get("blocked"):
        lines.append("No advisory plans this run.")
    return "\n".join(lines)

"""TraderAgent v1: concrete trade proposal from debate + technicals.

Advisory only: never places orders. Entry/stop/target are derived
deterministically from verified price, support/resistance and ATR. Position
size honours the supplied risk budget. Optional LLM enrichment may phrase the
rationale but cannot change the numbers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from investment_engine.skills import contracts
from investment_engine.skills import registry as _registry

SKILL = "trader_agent"
VERSION = "v1"

_DEFAULT_STOP_PCT = 7.0   # matches custom_rules stop_loss_pct
_TARGET_R = 2.0           # 2R default


def _extract_json_object(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except (TypeError, ValueError):
                    pass
    return None


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _proposal(tick: str, debate: dict[str, Any], tech: dict[str, Any] | None,
              risk_budget: float) -> dict[str, Any]:
    tech = tech or {}
    verdict = str(debate.get("verdict", "NO_SIGNAL"))
    price = _num(tech.get("price"))
    atr = _num(tech.get("atr"))
    support = _num(tech.get("support"))
    resistance = _num(tech.get("resistance"))
    stop_loss_pct = _num(tech.get("stop_loss_pct")) or _DEFAULT_STOP_PCT

    action = {"BULL": "BUY", "BEAR": "SELL"}.get(verdict, "HOLD")
    proposal: dict[str, Any] = {
        "ticker": tick,
        "action": action,
        "verdict": verdict,
        "conviction": float(debate.get("confidence", 0.0) or 0.0),
        "entry": price,
        "stop": None,
        "target": None,
        "risk_per_share": None,
        "quantity": 0.0,
        "reason": "",
        "advisory_only": True,
    }

    if action == "HOLD" or price is None or price <= 0:
        proposal["action"] = "HOLD"
        proposal["reason"] = "no actionable verdict or missing price"
        return proposal

    # Stop: support minus one ATR when support is known, else percentage stop.
    if action == "BUY":
        if support is not None and atr is not None and support < price:
            stop = support - atr
        else:
            stop = price * (1.0 - stop_loss_pct / 100.0)
        target = resistance if (resistance is not None and resistance > price) else price + _TARGET_R * (price - stop)
    else:  # SELL / short-side proposal (advisory)
        if resistance is not None and atr is not None and resistance > price:
            stop = resistance + atr
        else:
            stop = price * (1.0 + stop_loss_pct / 100.0)
        target = support if (support is not None and support < price) else price - _TARGET_R * (stop - price)

    stop = round(float(stop), 2)
    target = round(float(target), 2)
    risk_per_share = abs(price - stop)
    qty = 0.0
    if risk_budget > 0 and risk_per_share > 0:
        qty = round(risk_budget / risk_per_share, 4)

    proposal.update({
        "entry": round(price, 2),
        "stop": stop,
        "target": target,
        "risk_per_share": round(risk_per_share, 4),
        "quantity": qty,
        "reward_risk": round(abs(target - price) / risk_per_share, 2) if risk_per_share > 0 else None,
        "reason": f"{verdict} verdict; stop {stop} target {target}",
    })
    return proposal


def run(inputs: dict[str, Any], provider=None, settings=None, language: str = "English") -> dict[str, Any]:
    debates = [d for d in (inputs.get("debates", []) or []) if isinstance(d, dict)]
    technicals = inputs.get("technicals", {}) or {}
    try:
        risk_budget = float(inputs.get("risk_budget", 0.0) or 0.0)
    except (TypeError, ValueError):
        risk_budget = 0.0

    if not debates:
        return contracts.insufficient_output(SKILL, VERSION, "no debate verdicts supplied")

    proposals: list[dict[str, Any]] = []
    for debate in debates:
        tick = str(debate.get("ticker", "")).upper()
        if not tick:
            continue
        tech = technicals.get(tick) if isinstance(technicals, dict) else None
        proposals.append(_proposal(tick, debate, tech if isinstance(tech, dict) else None, risk_budget))

    if not proposals:
        return contracts.insufficient_output(SKILL, VERSION, "no valid tickers in debates")

    basis = [f"proposals={len(proposals)}", "deterministic-levels"]
    enriched = False
    llm_invoked = False
    llm_call_succeeded = False
    validation = "not_attempted"
    if provider is not None:
        try:
            snapshot = {p["ticker"]: {k: p[k] for k in ("action", "entry", "stop", "target", "quantity")}
                        for p in proposals}
            prompt = (
                _registry.load_prompt(SKILL, VERSION)
                + "\n\nPROPOSALS (verified, do not change numbers):\n"
                + json.dumps(snapshot, default=str)[:6000]
            )
            llm_invoked = True
            raw = provider.generate(prompt, stage="trader", context={"max_output_tokens": 700})
            llm_call_succeeded = True
            json_text = _extract_json_object(raw)
            parsed = json.loads(json_text) if json_text else None
            if isinstance(parsed, dict) and isinstance(parsed.get("proposals"), list):
                known = {p["ticker"] for p in proposals}
                good = all(str(x.get("ticker", "")).upper() in known for x in parsed["proposals"])
                if good:
                    by_ticker = {p["ticker"]: p for p in proposals}
                    for item in parsed["proposals"]:
                        tick = str(item.get("ticker", "")).upper()
                        if tick in by_ticker:
                            by_ticker[tick]["rationale"] = str(item.get("rationale", ""))[:300]
                    enriched = True
                    validation = "passed"
                    basis.append("llm-enriched")
                else:
                    validation = "failed: unknown ticker"
            else:
                validation = "failed: no proposals list"
        except Exception as exc:
            llm_call_succeeded = False
            validation = f"failed: {type(exc).__name__}"

    if enriched:
        basis = [b for b in basis if b != "deterministic-levels"]
        execution_type, execution_reason, fallback_reason = "LLM", "LLM_EXECUTED", ""
    elif llm_invoked and llm_call_succeeded:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_INVALID_OUTPUT"
        fallback_reason = f"llm output rejected ({validation}); deterministic levels used"
    elif llm_invoked:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_PROVIDER_FAILURE"
        fallback_reason = f"llm call failed ({validation}); deterministic levels used"
    else:
        execution_type, execution_reason, fallback_reason = "DETERMINISTIC", "DETERMINISTIC_BY_DESIGN", ""

    return {
        "skill": SKILL,
        "version": VERSION,
        "execution_type": execution_type,
        "execution_reason": execution_reason,
        "fallback_reason": fallback_reason,
        "status": "OK",
        "reason": "",
        "confidence": contracts.confidence(0.7 if enriched else 0.6, basis),
        "unverified": [p["ticker"] for p in proposals if p["action"] == "HOLD"],
        "data": {
            "proposals": proposals,
            "risk_budget": risk_budget,
            "enriched": enriched,
            "llm_invocation": {"invoked": llm_invoked, "call_succeeded": llm_call_succeeded,
                               "validation": validation},
        },
    }


def render(output: dict[str, Any]) -> str:
    lines = []
    for p in (output.get("data", {}) or {}).get("proposals", []) or []:
        if p.get("action") == "HOLD":
            lines.append(f"- **{p.get('ticker')}**: HOLD ({p.get('reason', '')})")
            continue
        lines.append(
            f"- **{p.get('ticker')}**: {p.get('action')} entry {p.get('entry')} "
            f"stop {p.get('stop')} target {p.get('target')} qty {p.get('quantity')} "
            f"(R:R {p.get('reward_risk')}) — advisory only"
        )
    return "\n".join(lines) if lines else "No trade proposals."

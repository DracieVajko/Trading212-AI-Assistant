"""ResearcherDebate v1: bull vs bear structured debate over analyst outputs.

Deterministic case-building from the analyst skill outputs (technical,
sentiment, news events, equity research). Optional LLM enrichment may phrase
the debate and verdict; it may not add tickers or invent evidence.
"""

from __future__ import annotations

import json
import re
from typing import Any

from investment_engine.skills import contracts
from investment_engine.skills import registry as _registry

SKILL = "researcher_debate"
VERSION = "v1"


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


def _collect(analyst_outputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """Build per-ticker bull/bear points deterministically from analyst outputs."""
    cases: dict[str, dict[str, list[str]]] = {}

    def case(tick: str) -> dict[str, list[str]]:
        return cases.setdefault(tick, {"bull": [], "bear": []})

    tech = analyst_outputs.get("technical_analyst", {}) or {}
    for read in (tech.get("data", {}) or {}).get("reads", []) or []:
        tick = str(read.get("ticker", "")).upper()
        if not tick:
            continue
        if read.get("momentum") == "OVERSOLD":
            case(tick)["bull"].append("RSI oversold")
        if read.get("momentum") == "OVERBOUGHT":
            case(tick)["bear"].append("RSI overbought")
        if str(read.get("trend", "")).endswith("_UP") or read.get("trend") == "UP":
            case(tick)["bull"].append("MACD/ADX trend up")
        if str(read.get("trend", "")).endswith("_DOWN") or read.get("trend") == "DOWN":
            case(tick)["bear"].append("MACD/ADX trend down")
        if read.get("level_proximity") == "NEAR_RESISTANCE":
            case(tick)["bear"].append("price at resistance")
        if read.get("level_proximity") == "NEAR_SUPPORT":
            case(tick)["bull"].append("price at support")

    senti = analyst_outputs.get("sentiment_analyst", {}) or {}
    for read in (senti.get("data", {}) or {}).get("reads", []) or []:
        tick = str(read.get("ticker", "")).upper()
        if not tick:
            continue
        if read.get("stance") == "BULLISH":
            case(tick)["bull"].append(f"positive sentiment ({read.get('confidence')})")
        elif read.get("stance") == "BEARISH":
            case(tick)["bear"].append(f"negative sentiment ({read.get('confidence')})")

    news = analyst_outputs.get("news_event_analyst", {}) or {}
    for event in (news.get("data", {}) or {}).get("events", []) or []:
        tick = str(event.get("ticker", "")).upper()
        if not tick:
            continue
        if event.get("severity") == "high" and event.get("impact") in ("direct", "indirect"):
            case(tick)["bear"].append(f"high-severity {event.get('type', 'event')}")
        if event.get("type") == "EARNINGS" and event.get("state") == "CONFIRMED":
            case(tick)["bull"].append("confirmed earnings event")

    research = analyst_outputs.get("equity_research_analyst", {}) or {}
    rdata = research.get("data", {}) or {}
    for item in (rdata.get("ideas") or []) if isinstance(rdata, dict) else []:
        if not isinstance(item, dict):
            continue
        tick = str(item.get("ticker", "")).upper()
        if not tick:
            continue
        if str(item.get("stance", "")).upper() == "BULL":
            case(tick)["bull"].append(str(item.get("thesis", "research bullish"))[:120])
        elif str(item.get("stance", "")).upper() == "BEAR":
            case(tick)["bear"].append(str(item.get("thesis", "research bearish"))[:120])

    return cases


def _verdict(bull: int, bear: int) -> str:
    if bull == 0 and bear == 0:
        return "NO_SIGNAL"
    if bull > bear:
        return "BULL"
    if bear > bull:
        return "BEAR"
    return "BALANCED"


def run(inputs: dict[str, Any], provider=None, settings=None, language: str = "English") -> dict[str, Any]:
    analyst_outputs = inputs.get("analyst_outputs", {}) or {}
    cases = _collect(analyst_outputs)
    if not cases:
        return contracts.insufficient_output(
            SKILL, VERSION, "no analyst points to debate"
        )

    debates: list[dict[str, Any]] = []
    for tick, points in sorted(cases.items()):
        bull = len(points["bull"])
        bear = len(points["bear"])
        debates.append({
            "ticker": tick,
            "bull_points": points["bull"],
            "bear_points": points["bear"],
            "bull_count": bull,
            "bear_count": bear,
            "verdict": _verdict(bull, bear),
            "confidence": round(abs(bull - bear) / max(1, bull + bear), 2),
        })

    basis = [f"tickers={len(debates)}", "deterministic-case-building"]
    enriched = False
    llm_invoked = False
    llm_call_succeeded = False
    validation = "not_attempted"
    if provider is not None:
        try:
            payload = {d["ticker"]: {"bull": d["bull_points"], "bear": d["bear_points"]} for d in debates}
            prompt = (
                _registry.load_prompt(SKILL, VERSION)
                + "\n\nDEBATE EVIDENCE (verified):\n"
                + json.dumps(payload, default=str)[:8000]
            )
            llm_invoked = True
            raw = provider.generate(prompt, stage="researchers", context={"max_output_tokens": 900})
            llm_call_succeeded = True
            json_text = _extract_json_object(raw)
            parsed = json.loads(json_text) if json_text else None
            if isinstance(parsed, dict) and isinstance(parsed.get("debates"), list):
                known = {d["ticker"] for d in debates}
                good = all(str(x.get("ticker", "")).upper() in known for x in parsed["debates"])
                if good:
                    by_ticker = {d["ticker"]: d for d in debates}
                    for item in parsed["debates"]:
                        tick = str(item.get("ticker", "")).upper()
                        if tick in by_ticker:
                            by_ticker[tick]["bull_summary"] = str(item.get("bull_summary", ""))[:300]
                            by_ticker[tick]["bear_summary"] = str(item.get("bear_summary", ""))[:300]
                            by_ticker[tick]["llm_verdict"] = str(item.get("verdict", ""))[:20]
                    enriched = True
                    validation = "passed"
                    basis.append("llm-enriched")
                else:
                    validation = "failed: unknown ticker"
            else:
                validation = "failed: no debates list"
        except Exception as exc:
            llm_call_succeeded = False
            validation = f"failed: {type(exc).__name__}"

    if enriched:
        basis = [b for b in basis if b != "deterministic-case-building"]
        execution_type, execution_reason, fallback_reason = "LLM", "LLM_EXECUTED", ""
    elif llm_invoked and llm_call_succeeded:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_INVALID_OUTPUT"
        fallback_reason = f"llm output rejected ({validation}); deterministic cases used"
    elif llm_invoked:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_PROVIDER_FAILURE"
        fallback_reason = f"llm call failed ({validation}); deterministic cases used"
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
        "confidence": contracts.confidence(0.68 if enriched else 0.55, basis),
        "unverified": [d["ticker"] for d in debates if d["verdict"] == "NO_SIGNAL"],
        "data": {
            "debates": debates,
            "enriched": enriched,
            "llm_invocation": {"invoked": llm_invoked, "call_succeeded": llm_call_succeeded,
                               "validation": validation},
        },
    }


def render(output: dict[str, Any]) -> str:
    lines = []
    for d in (output.get("data", {}) or {}).get("debates", []) or []:
        lines.append(
            f"- **{d.get('ticker')}**: {d.get('verdict')} "
            f"(bull {d.get('bull_count')}/bear {d.get('bear_count')}, conf {d.get('confidence')})"
        )
    return "\n".join(lines) if lines else "No debates."

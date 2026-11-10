"""TechnicalAnalyst v1: grounded technical read from verified indicators.

Deterministic classification from the indicator snapshot (RSI, MACD, ADX,
ATR, support/resistance). Optional LLM enrichment may summarise the read,
but it never invents price levels: unknown values are reported as unknown.
"""

from __future__ import annotations

import json
import re
from typing import Any

from investment_engine.skills import contracts
from investment_engine.skills import registry as _registry

SKILL = "technical_analyst"
VERSION = "v1"

_RSI_OVERSOLD = 30.0
_RSI_OVERBOUGHT = 70.0
_ADX_TREND = 25.0


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # reject NaN


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


def _indicator_read(row: dict[str, Any], tech: dict[str, Any] | None) -> dict[str, Any]:
    """Deterministic technical read for one holding."""
    tech = tech or {}
    rsi = _num(tech.get("RSI_14") or tech.get("RSI"))
    macd_hist = _num(tech.get("MACD_HIST") or tech.get("MACD_HISTOGRAM"))
    adx = _num(tech.get("ADX"))
    atr = _num(tech.get("ATR_14") or tech.get("ATR"))

    price = _num(row.get("current_price") or row.get("price") or row.get("currentPrice"))
    support = _num(row.get("support") or row.get("support_eur"))
    resistance = _num(row.get("resistance") or row.get("resistance_eur"))

    signals: list[str] = []
    momentum = "UNKNOWN"
    if rsi is not None:
        if rsi <= _RSI_OVERSOLD:
            momentum = "OVERSOLD"
            signals.append(f"RSI {rsi:.1f} oversold")
        elif rsi >= _RSI_OVERBOUGHT:
            momentum = "OVERBOUGHT"
            signals.append(f"RSI {rsi:.1f} overbought")
        else:
            momentum = "NEUTRAL"
            signals.append(f"RSI {rsi:.1f} neutral")

    trend = "UNKNOWN"
    if adx is not None:
        if adx >= _ADX_TREND:
            trend = "TRENDING"
        else:
            trend = "RANGE"
        if macd_hist is not None:
            direction = "UP" if macd_hist > 0 else ("DOWN" if macd_hist < 0 else "FLAT")
            trend = f"{trend}_{direction}"
        signals.append(f"ADX {adx:.1f}")
    elif macd_hist is not None:
        trend = "UP" if macd_hist > 0 else ("DOWN" if macd_hist < 0 else "FLAT")
        signals.append(f"MACD hist {macd_hist:+.3f}")

    proximity = "UNKNOWN"
    if price is not None and price > 0 and (support is not None or resistance is not None):
        try:
            if resistance is not None and abs(price - resistance) / price <= 0.02:
                proximity = "NEAR_RESISTANCE"
            elif support is not None and abs(price - support) / price <= 0.02:
                proximity = "NEAR_SUPPORT"
            else:
                proximity = "MID_RANGE"
        except ZeroDivisionError:
            proximity = "UNKNOWN"

    return {
        "ticker": str(row.get("display_symbol") or row.get("ticker") or "?").upper(),
        "weight_pct": _num(row.get("weight")) or 0.0,
        "rsi": rsi,
        "macd_hist": macd_hist,
        "adx": adx,
        "atr": atr,
        "price": price,
        "support": support,
        "resistance": resistance,
        "momentum": momentum,
        "trend": trend,
        "level_proximity": proximity,
        "signals": signals,
        "data_completeness": round(
            sum(v is not None for v in (rsi, macd_hist, adx, atr, price, support, resistance)) / 7.0, 2
        ),
    }


def run(inputs: dict[str, Any], provider=None, settings=None, language: str = "English") -> dict[str, Any]:
    rows = [r for r in (inputs.get("portfolio_rows", []) or []) if isinstance(r, dict)]
    technicals = inputs.get("technicals", {}) or {}
    if not rows:
        return contracts.insufficient_output(SKILL, VERSION, "no portfolio rows supplied")

    reads: list[dict[str, Any]] = []
    for row in rows:
        disp = str(row.get("display_symbol") or row.get("ticker") or "").upper()
        tech = technicals.get(disp) if isinstance(technicals, dict) else None
        reads.append(_indicator_read(row, tech if isinstance(tech, dict) else None))

    # Only holdings with any real indicator count as analysed.
    analysed = [r for r in reads if r["data_completeness"] > 0.0]
    if not analysed:
        return contracts.insufficient_output(
            SKILL, VERSION, "no technical indicators available for any holding"
        )

    basis = [f"holdings={len(reads)}", f"with_indicators={len(analysed)}", "deterministic-indicators"]
    enriched = False
    llm_invoked = False
    llm_call_succeeded = False
    validation = "not_attempted"
    if provider is not None:
        try:
            payload = {
                "holdings": [
                    {k: r[k] for k in ("ticker", "rsi", "macd_hist", "adx", "momentum", "trend",
                                       "level_proximity", "signals")}
                    for r in analysed
                ]
            }
            prompt = (
                _registry.load_prompt(SKILL, VERSION)
                + "\n\nINDICATOR SNAPSHOT (verified values only):\n"
                + json.dumps(payload, default=str)[:6000]
            )
            llm_invoked = True
            raw = provider.generate(prompt, stage="technical", context={"max_output_tokens": 700})
            llm_call_succeeded = True
            json_text = _extract_json_object(raw)
            parsed = json.loads(json_text) if json_text else None
            if isinstance(parsed, dict) and isinstance(parsed.get("reads"), list):
                # LLM may only annotate tickers present in the snapshot.
                known = {r["ticker"] for r in analysed}
                good = all(str(x.get("ticker", "")).upper() in known for x in parsed["reads"])
                if good:
                    by_ticker = {r["ticker"]: r for r in reads}
                    for item in parsed["reads"]:
                        tick = str(item.get("ticker", "")).upper()
                        if tick in by_ticker:
                            by_ticker[tick]["llm_note"] = str(item.get("note", ""))[:200]
                    enriched = True
                    validation = "passed"
                    basis.append("llm-enriched")
                else:
                    validation = "failed: unknown ticker"
            else:
                validation = "failed: no reads list"
        except Exception as exc:
            llm_call_succeeded = False
            validation = f"failed: {type(exc).__name__}"

    if enriched:
        basis = [b for b in basis if b != "deterministic-indicators"]
        execution_type, execution_reason, fallback_reason = "LLM", "LLM_EXECUTED", ""
    elif llm_invoked and llm_call_succeeded:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_INVALID_OUTPUT"
        fallback_reason = f"llm output rejected ({validation}); deterministic indicators used"
    elif llm_invoked:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_PROVIDER_FAILURE"
        fallback_reason = f"llm call failed ({validation}); deterministic indicators used"
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
        "unverified": [r["ticker"] for r in reads if r["data_completeness"] == 0.0],
        "data": {
            "reads": reads,
            "enriched": enriched,
            "llm_invocation": {"invoked": llm_invoked, "call_succeeded": llm_call_succeeded,
                               "validation": validation},
        },
    }


def render(output: dict[str, Any]) -> str:
    lines = []
    for read in (output.get("data", {}) or {}).get("reads", []) or []:
        if read.get("data_completeness", 0) == 0:
            lines.append(f"- **{read.get('ticker')}**: no technical data")
            continue
        lines.append(
            f"- **{read.get('ticker')}**: {read.get('momentum')}/{read.get('trend')} "
            f"({read.get('level_proximity')}) — {', '.join(read.get('signals', [])) or 'n/a'}"
        )
    return "\n".join(lines) if lines else "No technical reads."

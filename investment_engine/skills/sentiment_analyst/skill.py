"""SentimentAnalyst v1: aggregated market mood per ticker.

Deterministic keyword-based stance counting over news items and social posts.
Optional LLM enrichment may phrase the read, but counts and stance come from
the evidence; the model cannot add or drop tickers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from investment_engine.skills import contracts
from investment_engine.skills import registry as _registry

SKILL = "sentiment_analyst"
VERSION = "v1"

_BULLISH = (
    "beat", "beats", "upgrade", "upgraded", "surge", "surges", "rally", "record",
    "growth", "buyback", "raises guidance", "outperform", "strong", "bullish",
    "jumps", "soars", "gains", "positive", "profit", "wins",
)
_BEARISH = (
    "miss", "misses", "downgrade", "downgraded", "plunge", "plunges", "fall", "falls",
    "cut", "cuts guidance", "underperform", "weak", "bearish", "slides", "sinks",
    "loss", "losses", "negative", "lawsuit", "probe", "recall", "warning",
)


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


def _ticker_of(item: dict[str, Any], default: str = "GENERAL") -> str:
    tags = item.get("ticker_tags") or []
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        if str(tag).strip():
            return str(tag).strip().upper()
    tick = item.get("ticker") or item.get("symbol")
    return str(tick).strip().upper() if tick else default


def _score_text(text: str) -> tuple[int, int]:
    low = text.lower()
    bull = sum(1 for k in _BULLISH if k in low)
    bear = sum(1 for k in _BEARISH if k in low)
    return bull, bear


def run(inputs: dict[str, Any], provider=None, settings=None, language: str = "English") -> dict[str, Any]:
    news = [i for i in (inputs.get("decision_items", []) or []) if isinstance(i, dict)]
    social = [i for i in (inputs.get("social_items", []) or []) if isinstance(i, dict)]
    items = news + social
    if not items:
        return contracts.insufficient_output(SKILL, VERSION, "no news or social items supplied")

    per_ticker: dict[str, dict[str, int]] = {}
    for item in items:
        tick = _ticker_of(item)
        text = f"{item.get('title', '')} {item.get('text', '')}"
        bull, bear = _score_text(text)
        bucket = per_ticker.setdefault(tick, {"bullish": 0, "bearish": 0, "neutral": 0, "items": 0})
        bucket["items"] += 1
        if bull > bear:
            bucket["bullish"] += 1
        elif bear > bull:
            bucket["bearish"] += 1
        else:
            bucket["neutral"] += 1

    reads: list[dict[str, Any]] = []
    for tick, counts in sorted(per_ticker.items()):
        total = max(1, counts["items"])
        net = counts["bullish"] - counts["bearish"]
        if net > 0:
            stance = "BULLISH"
        elif net < 0:
            stance = "BEARISH"
        else:
            stance = "NEUTRAL"
        confidence = round(abs(net) / total, 2)
        reads.append({
            "ticker": tick,
            "stance": stance,
            "bullish": counts["bullish"],
            "bearish": counts["bearish"],
            "neutral": counts["neutral"],
            "items": counts["items"],
            "confidence": confidence,
        })

    basis = [f"items={len(items)}", f"tickers={len(reads)}", "deterministic-keyword-scoring"]
    enriched = False
    llm_invoked = False
    llm_call_succeeded = False
    validation = "not_attempted"
    if provider is not None:
        try:
            snapshot = {r["ticker"]: {k: r[k] for k in ("stance", "bullish", "bearish", "neutral", "confidence")}
                        for r in reads}
            prompt = (
                _registry.load_prompt(SKILL, VERSION)
                + "\n\nSENTIMENT COUNTS (verified):\n"
                + json.dumps(snapshot, default=str)[:6000]
            )
            llm_invoked = True
            raw = provider.generate(prompt, stage="sentiment", context={"max_output_tokens": 600})
            llm_call_succeeded = True
            json_text = _extract_json_object(raw)
            parsed = json.loads(json_text) if json_text else None
            if isinstance(parsed, dict) and isinstance(parsed.get("reads"), list):
                known = {r["ticker"] for r in reads}
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
        basis = [b for b in basis if b != "deterministic-keyword-scoring"]
        execution_type, execution_reason, fallback_reason = "LLM", "LLM_EXECUTED", ""
    elif llm_invoked and llm_call_succeeded:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_INVALID_OUTPUT"
        fallback_reason = f"llm output rejected ({validation}); deterministic counts used"
    elif llm_invoked:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_PROVIDER_FAILURE"
        fallback_reason = f"llm call failed ({validation}); deterministic counts used"
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
        "confidence": contracts.confidence(0.65 if enriched else 0.5, basis),
        "unverified": [r["ticker"] for r in reads if r["items"] <= 1],
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
        lines.append(
            f"- **{read.get('ticker')}**: {read.get('stance')} "
            f"(bull {read.get('bullish')}/bear {read.get('bearish')}/neutral {read.get('neutral')}, "
            f"conf {read.get('confidence')})"
        )
    return "\n".join(lines) if lines else "No sentiment reads."

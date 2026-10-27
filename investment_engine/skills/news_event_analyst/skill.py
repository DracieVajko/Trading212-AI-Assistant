"""NewsEventAnalyst v1: deterministic event grouping + optional LLM enrichment.

Evidence enforced BEFORE any prompt render: each claimed event needs a fresh
decision-grade item. LLM enrichment (when a provider is passed and succeeds)
may refine labels; its citations are validated against known item IDs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from investment_engine.skills import contracts
from investment_engine.skills import registry as _registry

SKILL = "news_event_analyst"
VERSION = "v1"

_TYPE_KEYWORDS = (
    ("EARNINGS", ("earnings", "eps", "results", "quarter")),
    ("GUIDANCE", ("guidance", "outlook", "forecast")),
    ("ANALYST", ("upgrade", "downgrade", "price target", "rating", "analyst")),
    ("POLICY", ("tariff", "regulation", "white house", "trump", "sanction", "export control")),
    ("MACRO", ("fed", "rate", "inflation", "jobs", "gdp", "ecb")),
    ("CORPORATE", ("merger", "acquisition", "ceo", "dividend", "buyback", "split")),
    ("SECTOR", ("sector", "industry")),
)


def _extract_json_object(text: str) -> str | None:
    """Extract the first JSON object from text, handling markdown fences and preamble."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    # Try to find JSON object in markdown code fences
    import re
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    # Try to find bare JSON object with balanced braces
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i+1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except (TypeError, ValueError):
                        pass
    return None


def _classify_type(title: str) -> str:
    low = title.lower()
    for label, keywords in _TYPE_KEYWORDS:
        if any(k in low for k in keywords):
            return label
    return "OTHER"


# Policy stage vocabulary: a mention is not an implementation.
# Order matters: enacted forms beat proposal forms beat mere mentions.
_POLICY_STAGE_KEYWORDS = (
    ("law", ("signed into law", "becomes law", "enacted")),
    ("order", ("executive order", "issues order", "imposes", "imposed")),
    ("proposal", ("proposes", "proposal", "plans to", "considering", "urges")),
    ("statement", ("says", "said", "warns", "criticizes", "claims", "announces")),
)


def _policy_stage(title: str) -> str:
    """Enacted vs proposed vs merely said. Empty string for non-policy items."""
    low = title.lower()
    for stage, keywords in _POLICY_STAGE_KEYWORDS:
        if any(k in low for k in keywords):
            return stage
    return ""


def _deterministic_events(items: list[dict[str, Any]],
                          weights: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Group items into events with analytical depth (deterministic).

    Phase 6: every event carries what-is-new, portfolio linkage, direct vs
    indirect/unconfirmed impact, counterevidence state, uncertainty and an
    attention priority — all derived from the evidence, never invented.
    """
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        tags = item.get("ticker_tags") or ["GENERAL"]
        by_ticker.setdefault(str(tags[0]).upper(), []).append(item)
    events = []
    weights = weights or {}
    for ticker, group in sorted(by_ticker.items()):
        pubs = {str(i.get("publisher", "")).lower() for i in group}
        state = "CONFIRMED" if len(pubs) >= 2 else "UNVERIFIED"
        best = sorted(group, key=lambda i: (i.get("source_tier", 3), -(i.get("relevance_score", 0) or 0)))[0]
        severities = {"EARNINGS": "high", "GUIDANCE": "high", "ANALYST": "medium",
                      "POLICY": "high", "MACRO": "medium", "CORPORATE": "medium"}
        etype = _classify_type(str(best.get("title", "")))
        relevance = str(best.get("portfolio_relevance", "unconfirmed") or "unconfirmed")
        event: dict[str, Any] = {
            "ticker": ticker,
            "type": etype,
            "item_ids": [str(i.get("id")) for i in group],
            "severity": severities.get(etype, "low"),
            "state": state,
            "what_is_new": str(best.get("title", ""))[:200],
            "in_portfolio": ticker in weights,
            "portfolio_weight_pct": round(float(weights.get(ticker, 0.0) or 0.0), 2),
            "impact": "direct" if relevance == "direct" else ("indirect" if relevance == "indirect" else "unconfirmed"),
            "counterevidence": [] if state == "CONFIRMED" else ["single-source: no counterevidence available"],
            "uncertainty": ("multi-source, corroborated" if state == "CONFIRMED"
                            else "single-source, unconfirmed"),
            "attention_priority": ("high" if severities.get(etype, "low") == "high" and state == "CONFIRMED"
                                    else ("medium" if severities.get(etype, "low") in ("high", "medium") else "low")),
        }
        if etype == "POLICY":
            event["policy_stage"] = _policy_stage(str(best.get("title", "")))
        events.append(event)
    return events


def run(inputs: dict[str, Any], provider=None, settings=None, language: str = "English") -> dict[str, Any]:
    items = [i for i in (inputs.get("decision_items", []) or []) if isinstance(i, dict)]
    ok, reason = contracts.require_evidence(items, min_items=1)
    if not ok:
        out = contracts.insufficient_output(SKILL, VERSION, reason)
        out["execution_type"] = "FALLBACK"
        out["fallback_reason"] = reason
        return out

    # Portfolio weights for the affected-holding linkage (display -> weight).
    _weights: dict[str, float] = {}
    try:
        for _r in (inputs.get("portfolio_rows", []) or []):
            if isinstance(_r, dict):
                _d = str(_r.get("display_symbol") or _r.get("ticker") or "").strip().upper()
                if _d:
                    _weights[_d] = float(_r.get("weight", 0) or 0.0)
    except (TypeError, ValueError):
        pass
    events = _deterministic_events(items, _weights)
    basis = [f"items={len(items)}", f"events={len(events)}", "deterministic-grouping"]
    enriched = False
    # Invocation provenance: distinguishes "LLM never called" from
    # "LLM called but output rejected". Filled below, reported in data.
    llm_invoked = False
    llm_call_succeeded = False
    validation = "not_attempted"
    repair_attempted = False
    if provider is not None:
        def _parse_payload(text: Any) -> dict[str, Any] | None:
            """Parse an LLM response into a JSON object, else None."""
            if not isinstance(text, str):
                return None
            json_text = _extract_json_object(text)
            if not json_text:
                return None
            try:
                candidate = json.loads(json_text)
            except (TypeError, ValueError):
                return None
            return candidate if isinstance(candidate, dict) else None

        def _events_of(candidate: dict[str, Any] | None) -> list[Any] | None:
            found = (candidate or {}).get("events")
            return found if isinstance(found, list) else None

        def _repair(repair_prompt: str) -> dict[str, Any] | None:
            """Issue the single budgeted repair call (callers guard the budget)."""
            nonlocal llm_call_succeeded
            repair_raw = provider.generate(
                repair_prompt, stage="news_events",
                context={"max_output_tokens": 800})
            llm_call_succeeded = True
            return _parse_payload(repair_raw)

        try:
            prompt = (_registry.load_prompt(SKILL, VERSION)
                      + f"\n\nEVIDENCE ({len(items)} items):\n"
                      + "\n".join(f"- [{i.get('id')}] {i.get('title', '')[:120]} ({i.get('publisher', '')})"
                                  for i in items[:12]))
            llm_invoked = True
            raw = provider.generate(prompt, stage="news_events",
                                    context={"max_output_tokens": 800})
            llm_call_succeeded = True
            parsed = _parse_payload(raw)

            if _events_of(parsed) is None:
                # ONE budgeted repair attempt: ask for bare JSON only.
                # A second failure falls back to the deterministic grouping
                # with the validation reason preserved (never silent).
                repair_attempted = True
                try:
                    parsed = _repair("Return ONLY the JSON object, no prose, no fences.")
                except Exception:
                    parsed = None
                    llm_call_succeeded = False
                if _events_of(parsed) is None:
                    validation = "failed: no events list after repair"

            if _events_of(parsed) is not None:
                known = {str(i.get("id")) for i in items}
                good, why = contracts.validate_citations({"data": parsed}, known)
                if not good and not repair_attempted:
                    # One budgeted repair for hallucinated citations too:
                    # spell out the only IDs the model is allowed to cite.
                    repair_attempted = True
                    valid_ids = ", ".join(sorted(known))
                    try:
                        parsed = _repair(
                            "Your previous JSON cited item_ids that are not in the "
                            "evidence. Use ONLY these item ids: "
                            f"{valid_ids}. Return ONLY the JSON object, no prose, "
                            "no fences.")
                    except Exception:
                        parsed = None
                        llm_call_succeeded = False
                    if _events_of(parsed) is None:
                        good, why = False, "no events list after repair"
                    else:
                        good, why = contracts.validate_citations({"data": parsed}, known)
                if good:
                    events = parsed["events"]
                    enriched = True
                    basis.append("llm-enriched")
                    validation = "passed" + (" (after 1 repair)" if repair_attempted else "")
                else:
                    validation = f"failed: {why}"
        except Exception as exc:
            llm_call_succeeded = False
            validation = f"failed: {type(exc).__name__}"
    if enriched:
        basis = [b for b in basis if b != "deterministic-grouping"]
        execution_type, execution_reason, fallback_reason = "LLM", "LLM_EXECUTED", ""
    elif llm_invoked and llm_call_succeeded:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_INVALID_OUTPUT"
        fallback_reason = f"llm output rejected ({validation}); deterministic grouping used"
    elif llm_invoked:
        execution_type, execution_reason = "FALLBACK", "FALLBACK_PROVIDER_FAILURE"
        fallback_reason = f"llm call failed ({validation}); deterministic grouping used"
    else:
        execution_type, execution_reason = "DETERMINISTIC", "DETERMINISTIC_BY_DESIGN"
        fallback_reason = ""
    return {
        "skill": SKILL,
        "version": VERSION,
        "execution_type": execution_type,
        "execution_reason": execution_reason,
        "fallback_reason": fallback_reason,
        "status": "OK",
        "reason": "",
        "confidence": contracts.confidence(0.7 if enriched else 0.55, basis),
        "unverified": [e["ticker"] for e in events if e.get("state") == "UNVERIFIED"],
        "data": {"events": events, "enriched": enriched,
                 "llm_invocation": {"invoked": llm_invoked,
                                     "call_succeeded": llm_call_succeeded,
                                     "validation": validation}},
    }


def render(output: dict[str, Any]) -> str:
    """Markdown section for the AI context file."""
    lines = []
    for event in (output.get("data", {}) or {}).get("events", []) or []:
        lines.append(
            f"- **{event.get('ticker')}** [{event.get('type')}/{event.get('state')}] "
            f"severity={event.get('severity')} evidence={len(event.get('item_ids', []))}")
    return "\n".join(lines) if lines else "No classified events."
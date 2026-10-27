"""EquityResearchAnalyst v1: deterministic thesis templates (+ optional polish).

Mapping gate enforced in code: technical observations render only for
VERIFIED rows. No price targets, no averaging-down endorsement, no sizes.

Phase 6 analytical depth: thesis comparison (CONFIRMED/CHANGED/UNASSESSED/
INSUFFICIENT_EVIDENCE), bull/base/bear scenarios with evidence links,
and explicit "what would change my view" section.
"""

from __future__ import annotations

from typing import Any

from investment_engine.skills import contracts

SKILL = "equity_research_analyst"
VERSION = "v1"


def _tech_line(display: str, technicals: dict[str, Any] | None) -> str:
    tech = (technicals or {}).get(display, {}) if isinstance(technicals, dict) else {}
    if not isinstance(tech, dict):
        return ""
    rsi = tech.get("RSI_14")
    parts = []
    try:
        if rsi is not None and float(rsi) >= 70:
            parts.append(f"RSI {float(rsi):.0f} overbought")
        elif rsi is not None and float(rsi) <= 30:
            parts.append(f"RSI {float(rsi):.0f} oversold")
    except (TypeError, ValueError):
        pass
    for key in ("Support", "Resistance"):
        if tech.get(key) is not None:
            parts.append(f"{key} {tech[key]}")
    return "; ".join(parts)


def _thesis_status(thesis: str, prev_thesis: str | None) -> str:
    """Compare current thesis with previous run's thesis."""
    if prev_thesis is None:
        return "UNASSESSED"
    if thesis == prev_thesis:
        return "CONFIRMED"
    return "CHANGED"


def _build_scenarios(catalysts: list[str], risks: list[str], thesis: str) -> dict[str, Any]:
    """Build bull/base/bear scenarios with evidence-linked catalysts/risks."""
    bull = "thesis intact; catalysts play out"
    if catalysts:
        bull += f": {catalysts[0][:120]}"
    base = f"{thesis} — monitor risks and next catalyst"
    bear = "risks materialize"
    if risks:
        bear += f": {risks[0][:120]}"
    return {
        "bull": bull,
        "base": base,
        "bear": bear,
        "note": "template-shaped, not a forecast; no price targets",
    }


def _what_would_change(earn: Any, risks: list[str], catalysts: list[str]) -> list[str]:
    """Explicit 'what would change my view' — specific evidence triggers."""
    triggers: list[str] = []
    if isinstance(earn, (list, tuple)) and earn:
        triggers.append(f"earnings {earn[0]} ({earn[1] if len(earn) > 1 else 'dated'})")
    if risks:
        triggers.append(f"invalidation: {risks[0][:120]}")
    if catalysts:
        triggers.append(f"new catalyst: {catalysts[0][:80]}")
    if not triggers:
        triggers.append("new material evidence")
    return triggers


def run(inputs: dict[str, Any], provider=None, settings=None, language: str = "English") -> dict[str, Any]:
    rows = [r for r in (inputs.get("portfolio_rows", []) or []) if isinstance(r, dict)]
    if not rows:
        out = contracts.insufficient_output(SKILL, VERSION, "no portfolio rows")
        out["execution_type"] = "FALLBACK"
        out["fallback_reason"] = "no portfolio rows"
        return out
    technicals = inputs.get("technicals", {}) or {}
    earnings = inputs.get("earnings_status", {}) or {}
    items = [i for i in (inputs.get("corpus_items", []) or []) if isinstance(i, dict)]
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for tag in item.get("ticker_tags", []) or []:
            by_ticker.setdefault(str(tag).upper(), []).append(item)

    # Previous run thesis lookup (from result._run_status_inputs or similar)
    prev_theses: dict[str, str] = {}
    try:
        prev_result = inputs.get("previous_run") or {}
        for note in (prev_result.get("equity_notes", {}) or {}).get("data", {}).get("notes", []) or []:
            if isinstance(note, dict):
                prev_theses[str(note.get("ticker", "")).upper()] = str(note.get("thesis", "HOLD"))
    except Exception:
        pass

    notes = []
    unverified: list[str] = []
    for row in rows:
        disp = str(row.get("display_symbol") or row.get("ticker") or "?").upper()
        signal = str(row.get("signal", "HOLD")).upper()
        mapping = str(row.get("external_mapping_status", ""))
        verified = mapping == "VERIFIED"
        thesis = {"BUY": "ACCUMULATE", "SELL": "TRIM"}.get(signal, "HOLD")
        prev_thesis = prev_theses.get(disp)
        thesis_status = _thesis_status(thesis, prev_thesis)
        catalysts, risks, evidence_ids = [], [], []
        for item in by_ticker.get(disp, [])[:3]:
            evidence_ids.append(str(item.get("id")))
            catalysts.append(f"{str(item.get('title', ''))[:100]} ({item.get('publisher', '')})")
        tech_line = _tech_line(disp, technicals) if verified else ""
        if not verified:
            unverified.append(f"{disp}: technicals withheld ({mapping or 'unknown mapping'})")
        earn = earnings.get(disp)
        if isinstance(earn, (list, tuple)) and earn:
            risks.append(f"earnings {earn[0]} ({earn[1] if len(earn) > 1 else 'dated'})")
        try:
            pnl = float(row.get("pnl_pct", 0) or 0)
            if pnl < 0:
                risks.append(f"position P&L {pnl:+.1f}% — review, no averaging-down endorsement")
        except (TypeError, ValueError):
            pass
        scenarios = _build_scenarios(catalysts, risks, thesis)
        what_would_change = _what_would_change(earn, risks, catalysts)
        what_changed = ("new evidence this run: " + "; ".join(catalysts[:2])
                        if catalysts else "no new corpus evidence this run")
        note = {"ticker": disp, "thesis": thesis, "thesis_status": thesis_status,
                "prev_thesis": prev_thesis or "N/A",
                "catalysts": catalysts[:3], "risks": risks[:3],
                "evidence_ids": evidence_ids,
                # Phase 6 analytical depth (deterministic, evidence-linked).
                # No price targets, no invented scenarios — bull/base/bear are
                # explicitly template-shaped around the observed catalysts
                # and risks, marked as such.
                "what_changed": what_changed,
                "scenarios": scenarios,
                "what_would_change": what_would_change,
                "valuation_limits": "no price target issued (policy: targets are opinions, never facts)",
                }
        if tech_line:
            note["technicals"] = tech_line
        notes.append(note)

    known = {str(i.get("id")) for i in items}
    good, why = contracts.validate_citations({"data": {"notes": notes}}, known)
    return {
        "skill": SKILL,
        "version": VERSION,
        "execution_type": "DETERMINISTIC",
        "execution_reason": "DETERMINISTIC_BY_DESIGN",
        "fallback_reason": "",
        "status": "OK" if good else "DEGRADED",
        "reason": "" if good else why,
        "confidence": contracts.confidence(0.6, [f"notes={len(notes)}", "template"]),
        "unverified": unverified,
        "data": {"notes": notes},
    }


def render(output: dict[str, Any]) -> str:
    """Markdown section for the AI context file."""
    lines = []
    for note in (output.get("data", {}) or {}).get("notes", []) or []:
        lines.append(f"- **{note.get('ticker')}** — {note.get('thesis')}")
    return "\n".join(lines) if lines else "No equity notes."
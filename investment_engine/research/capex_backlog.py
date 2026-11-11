"""CapEx and order backlog tracker for SEC EDGAR filings.

Extracts capital expenditure and order backlog figures from quarterly/annual
filing text (10-Q / 10-K / 8-K) using regex. The LLM layer may refine the
extraction; this module provides the deterministic baseline.
"""

from __future__ import annotations

import re
from typing import Any

# Regex patterns for CapEx and backlog mentions.
_CAPEX_PATTERNS = [
    r"capital expenditures?\s+(?:of|were|totaled|amounted to)?\s*\$?\s*([\d,.]+\s*(?:million|billion|M|B)?)",
    r"capex\s*[:=]?\s*\$?\s*([\d,.]+\s*(?:million|billion|M|B)?)",
    r"invested\s+\$?\s*([\d,.]+\s*(?:million|billion|M|B)?)\s+in\s+capital",
]
_BACKLOG_PATTERNS = [
    r"order backlog\s+(?:of|was|reached|totaled|stood at)?\s*\$?\s*([\d,.]+\s*(?:million|billion|M|B)?)",
    r"backlog\s*[:=]?\s*\$?\s*([\d,.]+\s*(?:million|billion|M|B)?)",
    r"unfilled orders?\s+(?:of|were|totaled)?\s*\$?\s*([\d,.]+\s*(?:million|billion|M|B)?)",
]
_GUIDANCE_PATTERNS = [
    r"capex\s+guidance\s+(?:of|is|was)?\s*\$?\s*([\d,.]+\s*(?:million|billion|M|B)?)",
    r"expected\s+capital expenditures?\s+(?:of|to be)?\s*\$?\s*([\d,.]+\s*(?:million|billion|M|B)?)",
]


def _to_number(text: str) -> float | None:
    """Parse a number string like '1.2 billion' or '500 million'."""
    if not text:
        return None
    t = text.strip().lower().replace(",", "")
    multiplier = 1.0
    if "billion" in t or t.endswith("b"):
        multiplier = 1e9
        t = t.replace("billion", "").replace("b", "").strip()
    elif "million" in t or t.endswith("m"):
        multiplier = 1e6
        t = t.replace("million", "").replace("m", "").strip()
    try:
        return float(t) * multiplier
    except ValueError:
        return None


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_capex_backlog(text: str) -> dict[str, Any]:
    """Extract CapEx, backlog and guidance from filing text.

    Returns:
        dict with capex_usd, backlog_usd, guidance_usd, snippets, found.
    """
    if not text:
        return {"capex_usd": None, "backlog_usd": None, "guidance_usd": None,
                "found": False, "snippets": []}

    capex_raw = _first_match(text, _CAPEX_PATTERNS)
    backlog_raw = _first_match(text, _BACKLOG_PATTERNS)
    guidance_raw = _first_match(text, _GUIDANCE_PATTERNS)

    capex = _to_number(capex_raw) if capex_raw else None
    backlog = _to_number(backlog_raw) if backlog_raw else None
    guidance = _to_number(guidance_raw) if guidance_raw else None

    snippets: list[str] = []
    for pat in _CAPEX_PATTERNS + _BACKLOG_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            snippets.append(text[max(0, m.start() - 60):m.end() + 60].replace("\n", " ").strip())
            if len(snippets) >= 5:
                break
        if len(snippets) >= 5:
            break

    found = capex is not None or backlog is not None or guidance is not None
    return {
        "capex_usd": capex,
        "backlog_usd": backlog,
        "guidance_usd": guidance,
        "found": found,
        "snippets": snippets,
    }


def analyze_capex_change(
    current_capex: float | None,
    previous_capex: float | None,
    current_backlog: float | None = None,
    previous_backlog: float | None = None,
) -> dict[str, Any]:
    """Analyze CapEx and backlog changes between quarters.

    Returns verdict: STRONG (massive increase), MODERATE, NEUTRAL, DECLINE, or UNKNOWN.
    """
    if current_capex is None or previous_capex is None or previous_capex <= 0:
        return {"verdict": "UNKNOWN", "capex_change_pct": None, "backlog_change_pct": None,
                "reason": "missing capex data"}

    capex_change = (current_capex - previous_capex) / previous_capex * 100.0
    backlog_change = None
    if current_backlog is not None and previous_backlog and previous_backlog > 0:
        backlog_change = (current_backlog - previous_backlog) / previous_backlog * 100.0

    if capex_change >= 50.0 or (backlog_change is not None and backlog_change >= 30.0):
        verdict = "STRONG"
        reason = f"CapEx +{capex_change:.1f}%"
        if backlog_change is not None:
            reason += f", backlog +{backlog_change:.1f}%"
    elif capex_change >= 10.0:
        verdict = "MODERATE"
        reason = f"CapEx +{capex_change:.1f}%"
    elif capex_change <= -10.0:
        verdict = "DECLINE"
        reason = f"CapEx {capex_change:.1f}%"
    else:
        verdict = "NEUTRAL"
        reason = f"CapEx {capex_change:+.1f}%"

    return {
        "verdict": verdict,
        "capex_change_pct": round(capex_change, 2),
        "backlog_change_pct": round(backlog_change, 2) if backlog_change is not None else None,
        "reason": reason,
    }

"""Phase 5 completion — small, focused helpers (no new collectors).

This module is the single place for:
- assigning a concrete research domain to an adapter output (so deep-dive
  sections stop showing generic "No coverage");
- tagging analyst items as single-revision vs consensus vs opinion;
- classifying policy items as statement/proposal/order/law/implementation;
- classifying trial items as phase/endpoint/risk-aware.

Everything here is deterministic and offline (no I/O, no network, no LLM).
"""

from __future__ import annotations

from typing import Any


DOMAINS = (
    "energy_prices",
    "renewables_batteries",
    "healthcare_biotech",
    "crypto",
    "analyst",
    "policy",
    "social",
    "discovery",
)

# Keyword -> domain tag. First match wins; unknown -> general.
_DOMAIN_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("wti", "energy_prices"), ("brent", "energy_prices"),
    ("crude oil", "energy_prices"), ("natural gas", "energy_prices"),
    ("uranium", "energy_prices"), ("copper", "energy_prices"),
    ("battery", "renewables_batteries"), ("lithium", "renewables_batteries"),
    ("solar", "renewables_batteries"), ("wind", "renewables_batteries"),
    ("renewable", "renewables_batteries"), ("grid", "renewables_batteries"),
    ("hydrogen", "renewables_batteries"),
    ("fda", "healthcare_biotech"), ("clinical trial", "healthcare_biotech"),
    ("biotech", "healthcare_biotech"), ("pharma", "healthcare_biotech"),
    ("pdufa", "healthcare_biotech"), ("drug", "healthcare_biotech"),
    ("bitcoin", "crypto"), ("ethereum", "crypto"), ("crypto", "crypto"),
    ("stablecoin", "crypto"), ("etf flow", "crypto"),
    ("analyst", "analyst"), ("price target", "analyst"),
    ("upgrade", "analyst"), ("downgrade", "analyst"), ("rating", "analyst"),
    ("tariff", "policy"), ("white house", "policy"), ("trump", "policy"),
    ("export control", "policy"), ("sanction", "policy"),
    ("reddit", "social"), ("stocktwits", "social"), ("forum", "social"),
)


def domain_for(title: str = "", category: str = "", tags: list[str] | None = None) -> str:
    """Return the research domain of an item, or 'general'."""
    hay = " ".join([str(title or ""), str(category or ""), " ".join(tags or [])]).lower()
    for keyword, domain in _DOMAIN_KEYWORDS:
        if keyword in hay:
            return domain
    return "general"


def analyst_kind(title: str = "") -> str:
    """Single revision vs consensus vs opinion vs quant forecast."""
    low = str(title or "").lower()
    if "consensus" in low or "survey" in low:
        return "consensus"
    if "price target" in low or "upgrade" in low or "downgrade" in low:
        return "revision"
    if "forecast" in low or "model" in low:
        return "quant"
    return "opinion"


def trial_phase(title: str = "") -> str:
    """Extract trial phase when present; else 'unknown'."""
    import re

    low = str(title or "").lower()
    for phase in ("phase 1", "phase 2", "phase 3", "phase 4", "phase i", "phase ii", "phase iii"):
        if phase in low:
            return phase
    m = re.search(r"phase\s*(\d)", low)
    return f"phase {m.group(1)}" if m else "unknown"


def weak_match_rules() -> tuple[str, ...]:
    """Rules for dropping weak news-to-holding matches. Documentation, not code."""
    return (
        "A ticker substring match alone is never a direct link.",
        "A company-name match alone is sufficient only if the name appears in the title.",
        "Sector/theme exposure is indirect, never direct.",
        "Macro items (SPY/BTC/TRUMP buckets) are indirect unless they name the holding.",
        "Social-only evidence cannot justify an actionable plan.",
    )
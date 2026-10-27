"""Healthcare/FDA event extraction (WP4b).

Event types: regulatory, trial, safety, reimbursement, patent, M&A, earnings.
Phase/endpoint/limits extracted when available.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Event type taxonomy
EVENT_TYPES = {
    "regulatory": ["fda", "ema", "pmda", "approval", "clearance", "crl", "nda", "bla", "snda", "priority review", "fast track", "breakthrough therapy", "orphan drug", "accelerated approval"],
    "trial": ["phase 1", "phase 2", "phase 3", "phase i", "phase ii", "phase iii", "phase iv", "topline", "primary endpoint", "secondary endpoint", "enrollment", "recruitment", "pivotal", "interim", "data readout", "readout"],
    "safety": ["safety", "adverse", "ae", "sae", "toxicity", "tolerability", "dose limiting", "dlts", "black box", "warning", "recall", "suspension"],
    "reimbursement": ["reimbursement", "coverage", "formulary", "payer", "cms", "nicer", "hosp", "access", "pricing", "ndc", "j code"],
    "patent": ["patent", "ip", "intellectual property", "exclusivity", "patent cliff", "extension", "invalidation", "litigation", "settlement"],
    "m_a": ["merger", "acquisition", "buyout", "takeover", "tender offer", "spinout", "divestiture", "asset purchase", "licensing deal", "collaboration", "partnership", "strategic alliance"],
    "earnings": ["earnings", "quarterly", "guidance", "revenue", "eps", "sales", "results", "conference call"],
}

# Phase patterns
PHASE_PATTERN = re.compile(r"\bphase\s+([1-4]|[iv]+)\b", re.IGNORECASE)
ENDPOINT_PATTERN = re.compile(r"\b(primary|secondary|exploratory)\s+endpoint\b", re.IGNORECASE)

# Known biotech/pharma tickers for disambiguation (sample)
BIOTECH_KEYWORDS = {
    "biotech", "pharma", "pharmaceutical", "therapeutics", "biosciences",
    "life sciences", "gene therapy", "cell therapy", "antibody", "vaccine",
    "oncology", "immunology", "neurology", "cardiology", "rare disease",
    "orphan", "precision medicine", "crispr", "mrna", "adc", "bispecific"
}


def classify_event(text: str) -> list[str]:
    """Return list of event types matched in text."""
    low = text.lower()
    matched = []
    for etype, keywords in EVENT_TYPES.items():
        if any(kw in low for kw in keywords):
            matched.append(etype)
    return matched


def extract_phase(text: str) -> str | None:
    m = PHASE_PATTERN.search(text)
    return m.group(1).upper() if m else None


def extract_endpoint(text: str) -> str | None:
    m = ENDPOINT_PATTERN.search(text)
    return m.group(1).lower() if m else None


def is_biotech_context(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in BIOTECH_KEYWORDS)


def extract_event(text: str, symbol: str, source: str, url: str, published_at: str | None) -> dict[str, Any] | None:
    """Extract structured event from text. Returns None if not biotech-relevant."""
    if not is_biotech_context(text):
        return None

    event_types = classify_event(text)
    if not event_types:
        return None

    phase = extract_phase(text)
    endpoint = extract_endpoint(text)

    return {
        "type": "healthcare_event",
        "subtypes": event_types,
        "symbol": symbol,
        "phase": phase,
        "endpoint": endpoint,
        "source": source,
        "url": url,
        "published_at": published_at,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_events_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all healthcare events from a corpus item."""
    title = str(item.get("title", "") or "")
    extract = str(item.get("clean_extract", "") or "")
    text = f"{title} {item.get('raw_extract_if_available', '')}".strip()
    symbol = str(item.get("ticker_tags", [""])[0] if item.get("ticker_tags") else "").upper()

    events = []
    for source_field in ("title", "clean_extract", "raw_extract_if_available"):
        text = str(item.get(source_field, "") or "")
        if not text:
            continue
        evt = extract_event(text, item.get("ticker_tags", [""])[0] if item.get("ticker_tags") else "",
                           item.get("publisher", "unknown"), item.get("canonical_url", ""),
                           item.get("published_at_utc"))
        if evt:
            events.append(evt)

    # Deduplicate by (subtype, phase, endpoint)
    seen = set()
    deduped = []
    for e in events:
        key = (tuple(sorted(e["subtypes"])), e.get("phase"), e.get("endpoint"))
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return deduped


if __name__ == "__main__":
    # Quick self-test
    test_text = "FDA grants breakthrough therapy designation for Phase 3 trial of novel antibody in oncology"
    print(classify_event(test_text))
    print(extract_phase(test_text))
    print(extract_endpoint(test_text))
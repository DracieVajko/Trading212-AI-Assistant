"""Trump/policy event objects (WP4e).

Structured event objects with actor, source, time, stage, direct-vs-inferred exposure.
No longer just keyword buckets — proper event objects.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Policy event taxonomy
POLICY_EVENT_TYPES = {
    "tariff": ["tariff", "tariffs", "import duty", "import duties", "customs duty", "trade barrier", "trade war", "section 301", "section 232"],
    "china_taiwan": ["taiwan", "china", "taiwan strait", "one china", "tsmc", "semiconductor", "chip act", "chips act", "export control", "entity list"],
    "rare_earths": ["rare earth", "rare earths", "critical mineral", "critical minerals", "lithium", "cobalt", "nickel", "graphite", "manganese"],
    "uranium_nuclear": ["uranium", "nuclear", "nuclear energy", "small modular reactor", "smr", "advanced reactor", "enrichment", "yellowcake"],
    "oil_lng": ["oil", "crude", "wti", "brent", "lng", "liquefied natural gas", "natural gas", "opec", "opec+", "production cut", "strategic petroleum reserve"],
    "ev_batteries": ["electric vehicle", "ev", "battery", "batteries", "gigafactory", "charging", "charging infrastructure", "ira tax credit", "ev tax credit"],
    "defense": ["defense", "defence", "pentagon", "military", "arms", "weapons", "missile", "fighter", "bomber", "submarine", "aircraft carrier", "nato"],
    "pharma_pricing": ["drug pricing", "drug price", "medicare negotiation", "inflation reduction act", "ira", "medicare part d", "drug price negotiation"],
    "crypto": ["crypto", "bitcoin", "ethereum", "stablecoin", "sec crypto", "crypto regulation", "digital asset", "defi", "staking", "crypto exchange"],
}

# Actor patterns
ACTOR_PATTERNS = {
    "trump": [r"\btrump\b", r"\bdonald trump\b", r"\bformer president\b"],
    "biden": [r"\bbiden\b", r"\bpresident biden\b", r"\bwhite house\b", r"\badministration\b"],
    "congress": [r"\bcongress\b", r"\bsenate\b", r"\bhouse\b", r"\brepresentatives\b", r"\blegislation\b", r"\bbill\b"],
    "sec": [r"\bsec\b", r"\bsecurities and exchange\b", r"\bchair\b", r"\bgensler\b"],
    "cftc": [r"\bcftc\b", r"\bcommodity futures\b"],
    "fed": [r"\bfed\b", r"\bfederal reserve\b", r"\bpowell\b", r"\binterest rate\b", r"\bfomc\b"],
    "treasury": [r"\btreasury\b", r"\bsecretary\b", r"\byellen\b"],
    "china": [r"\bchina\b", r"\bbeijing\b", r"\bxi jinping\b", r"\bccp\b"],
    "eu": [r"\beu\b", r"\beuropean union\b", r"\bbrussels\b", r"\bvon der leyen\b"],
}

# Policy stage taxonomy
STAGE_KEYWORDS = {
    "statement": ["said", "stated", "announced", "declared", "tweeted", "posted", "remark", "comment", "speech", "address"],
    "proposal": ["proposed", "proposal", "plan", "proposed rule", "nprm", "notice of proposed", "draft", "framework"],
    "order": ["executive order", "eo ", "directive", "presidential directive", "ordered", "directs"],
    "regulation": ["regulation", "rule", "final rule", "rulemaking", "rulemaking", "cfr", "code of federal regulations"],
    "law": ["signed into law", "enacted", "legislation", "act", "statute", "public law", "pl "],
    "implementation": ["implemented", "implementation", "effective", "effective date", "compliance date", "enforcement"],
}

# Direct mention vs sector inference
DIRECT_PATTERNS = {
    "company": [r"\b[a-z]{1,5}\b"],  # Ticker-like - validated separately
    "sector": ["sector", "industry", "industries", "companies", "firms"],
}

SECTOR_INFERENCE = {
    "semiconductor": ["semiconductor", "chip", "foundry", "fab", "tsmc", "intel", "amd", "nvidia", "asml", "lithography"],
    "energy": ["oil", "gas", "lng", "crude", "pipeline", "refinery", "drilling", "offshore"],
    "defense": ["defense", "defence", "lockheed", "boeing", "raytheon", "northrop", "general dynamics"],
    "auto": ["electric vehicle", "ev", "tesla", "ford", "gm", "rivian", "lucid", "battery", "gigafactory"],
    "pharma": ["pharma", "biotech", "drug", "medicine", "fda", "clinical trial", "pipeline"],
    "crypto": ["crypto", "bitcoin", "ethereum", "stablecoin", "defi", "exchange", "sec crypto"],
    "banking": ["bank", "jpmorgan", "citi", "wells fargo", "bank of america", "goldman", "morgan stanley"],
    "tech": ["ai", "artificial intelligence", "cloud", "azure", "aws", "google cloud", "semiconductor"],
}


def classify_policy_topic(text: str) -> list[str]:
    """Return list of policy topics matched in text."""
    low = text.lower()
    matched = []
    for topic, keywords in POLICY_EVENT_TYPES.items():
        if any(kw in low for kw in keywords):
            matched.append(topic)
    return matched


def detect_actor(text: str) -> list[str]:
    """Detect policy actors mentioned in text."""
    low = text.lower()
    actors = []
    for actor, patterns in ACTOR_PATTERNS.items():
        if any(re.search(p, low) for p in patterns):
            actors.append(actor)
    return actors


def detect_stage(text: str) -> list[str]:
    """Detect policy stage(s) from text."""
    low = text.lower()
    stages = []
    for stage, keywords in STAGE_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            stages.append(stage)
    return stages


def infer_sector_exposure(text: str) -> list[str]:
    """Infer sector exposure from text (indirect inference)."""
    low = text.lower()
    sectors = []
    for sector, keywords in SECTOR_INFERENCE.items():
        if any(kw in low for kw in keywords):
            sectors.append(sector)
    return sectors


def is_direct_mention(text: str, tickers: list[str]) -> bool:
    """Check if text directly mentions a tracked ticker."""
    low = text.lower()
    for ticker in tickers:
        if ticker and ticker.lower() in low:
            return True
    return False


def extract_policy_event(text: str, source: str, url: str, published_at: str | None,
                         tracked_tickers: list[str] | None = None) -> list[dict]:
    """Extract structured policy events from text."""
    topics = classify_policy_topic(text)
    if not topics:
        return []

    actors = detect_actor(text)
    stages = detect_stage(text)
    sectors = infer_sector_exposure(text)
    direct = is_direct_mention(text, tracked_tickers or [])

    events = []
    for topic in topics:
        evt = {
            "type": "policy_event",
            "topic": topic,
            "actors": actors,
            "stages": stages,
            "sectors": sectors,
            "direct_mention": direct,
            "source": source,
            "url": url,
            "published_at": published_at,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        events.append(evt)
    return events


def extract_events_from_item(item: dict) -> list[dict]:
    """Extract all policy events from a corpus item."""
    title = str(item.get("title", "") or "")
    extract = str(item.get("clean_extract", "") or "")
    text = f"{title} {item.get('raw_extract_if_available', '')}".strip()

    events = []
    for source_field in ("title", "clean_extract", "raw_extract_if_available"):
        text = str(item.get(source_field, "") or "")
        if not text:
            continue
        events.extend(extract_policy_event(
            text,
            item.get("publisher", "unknown"),
            item.get("canonical_url", ""),
            item.get("published_at_utc"),
            tracked_tickers=[t.upper() for t in item.get("ticker_tags", [])]
        ))

    # Deduplicate by (topic, stage)
    seen = set()
    deduped = []
    for e in events:
        key = (e["topic"], tuple(sorted(e["stages"])))
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return deduped


if __name__ == "__main__":
    test = "Trump announces 25% tariff on Chinese semiconductors; Biden administration reviewing export controls on advanced chips"
    print("Topics:", classify_policy_topic(test))
    print("Actors:", detect_actor(test))
    print("Stages:", detect_stage(test))
    print("Sectors:", infer_sector_exposure(test))
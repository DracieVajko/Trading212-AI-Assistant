"""Static sector/theme/region backfill for corpus items (Phase 2).

Keyword-based, deterministic, no network, no LLM. Fills `sector_tags` and
`region_tags` so downstream sections (energy, healthcare, crypto) have
something to aggregate. Unknown stays empty — never invented.
"""

from __future__ import annotations

# Lowercase keyword -> sector tags. Order matters only for determinism
# (sorted output); matching is substring on title+extract.
_SECTOR_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("semiconductor", ("technology", "semiconductors")),
    ("chip", ("technology", "semiconductors")),
    ("gpu", ("technology", "semiconductors")),
    ("ai ", ("technology", "ai")),
    ("artificial intelligence", ("technology", "ai")),
    ("cloud", ("technology", "cloud")),
    ("data center", ("technology", "datacenters")),
    ("datacenter", ("technology", "datacenters")),
    ("oil", ("energy", "oil")),
    ("crude", ("energy", "oil")),
    ("wti", ("energy", "oil")),
    ("brent", ("energy", "oil")),
    ("opec", ("energy", "oil")),
    ("natural gas", ("energy", "gas")),
    ("lng", ("energy", "gas")),
    ("uranium", ("energy", "uranium")),
    ("nuclear", ("energy", "uranium")),
    ("lithium", ("materials", "batteries", "lithium")),
    ("battery", ("materials", "batteries")),
    ("batteries", ("materials", "batteries")),
    ("solar", ("energy", "renewables", "solar")),
    ("wind", ("energy", "renewables")),
    ("grid", ("energy", "grid")),
    ("hydrogen", ("energy", "hydrogen")),
    ("copper", ("materials", "copper")),
    ("gold", ("materials", "gold")),
    ("silver", ("materials", "silver")),
    ("pharma", ("healthcare", "pharma")),
    ("biotech", ("healthcare", "biotech")),
    ("fda", ("healthcare", "fda")),
    ("clinical trial", ("healthcare", "trials")),
    ("drug", ("healthcare", "pharma")),
    ("vaccine", ("healthcare", "pharma")),
    ("bitcoin", ("crypto", "btc")),
    ("ethereum", ("crypto", "eth")),
    ("crypto", ("crypto",)),
    ("etf flow", ("crypto", "flows")),
    ("tariff", ("policy", "trade")),
    ("white house", ("policy",)),
    ("trump", ("policy",)),
    ("fed", ("macro", "rates")),
    ("ecb", ("macro", "rates")),
    ("inflation", ("macro",)),
    ("rate cut", ("macro", "rates")),
    ("rate hike", ("macro", "rates")),
    ("earnings", ("earnings",)),
    ("guidance", ("earnings", "guidance")),
    ("analyst", ("analyst",)),
    ("price target", ("analyst",)),
    ("upgrade", ("analyst",)),
    ("downgrade", ("analyst",)),
)

# Lowercase keyword -> region tags.
_REGION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("china", ("CN",)),
    ("chinese", ("CN",)),
    ("europe", ("EU",)),
    ("european", ("EU",)),
    ("ecb", ("EU",)),
    ("germany", ("EU", "DE")),
    ("france", ("EU", "FR")),
    ("united states", ("US",)),
    ("u.s.", ("US",)),
    ("fed", ("US",)),
    ("white house", ("US",)),
    ("taiwan", ("TW",)),
    ("japan", ("JP",)),
    ("korea", ("KR",)),
    ("india", ("IN",)),
    ("uk ", ("GB",)),
    ("britain", ("GB",)),
    ("london", ("GB",)),
)


def tags_for(title: str = "", extract: str = "") -> tuple[list[str], list[str]]:
    """Return (sector_tags, region_tags) for a corpus item. Deterministic."""
    text = f"{title or ''} {extract or ''}".lower()
    sectors: set[str] = set()
    regions: set[str] = set()
    for keyword, tags in _SECTOR_KEYWORDS:
        if keyword in text:
            sectors.update(tags)
    for keyword, tags in _REGION_KEYWORDS:
        if keyword in text:
            regions.update(tags)
    return sorted(sectors), sorted(regions)

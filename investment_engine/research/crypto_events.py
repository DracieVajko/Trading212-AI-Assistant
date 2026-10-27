"""Crypto market event extraction (WP4c).

Event taxonomy: protocol events, regulation, exchange/custody/stablecoin risks,
ETF flows (where licensed/publicly accessible).

Robust asset identity via provider-specific symbols (BTC-USD, ETH-USD, etc.).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Crypto event taxonomy
CRYPTO_EVENT_TYPES = {
    "protocol": ["upgrade", "fork", "hard fork", "soft fork", "governance proposal", "vote", "dao", "proposal", "execution", "timelock", "mainnet", "testnet", "launch", "mainnet launch"],
    "regulation": ["sec", "cftc", "finra", "regulation", "regulation", "enforcement", "wells notice", "subpoena", "guidance", "framework", "legislation", "bill", "act", "license", "license", "registration", "compliance"],
    "exchange": ["listing", "removal from listing", "halt", "trading halt", "suspension", "new pairs", "trading pairs", "margin", "leverage", "futures", "options", "perp", "perpetual", "spot", "otc", "custody", "custodian", "prime broker"],
    "stablecoin": ["depeg", "peg", "reserve", "attestation", "audit", "redemption", "mint", "burn", "collateral", "overcollateralized", "algorithmic", "terra", "usdt", "usdc", "busd", "dai", "frax", "lusd"],
    "protocol_risk": ["hack", "exploit", "vulnerability", "bug", "audit", "audit report", "formal verification", "bounty", "bug bounty", "slashing", "validator", "staking", "unstaking", "liquidation", "liquid staking", "restaking"],
    "etf_flows": ["etf", "etf approval", "etf launch", "etf filing", "s-1", "19b-4", "spot etf", "futures etf", "flows", "inflows", "outflows", "aum", "assets under management"],
    "macro": ["fed", "interest rate", "inflation", "cpi", "pce", "gdp", "employment", "nfp", "dollar index", "dxy", "yield curve", "treasury"],
}

# Major crypto symbols for disambiguation
CRYPTO_SYMBOLS = {
    "BTC", "BTC-USD", "BTC-USDT", "ETH", "ETH-USD", "ETH-USDT",
    "SOL", "SOL-USD", "SOL-USDT", "ADA", "ADA-USD", "XRP", "XRP-USD",
    "DOT", "DOT-USD", "AVAX", "AVAX-USD", "MATIC", "MATIC-USD",
    "LINK", "LINK-USD", "UNI", "UNI-USD", "ATOM", "ATOM-USD",
    "NEAR", "NEAR-USD", "FTM", "FTM-USD", "ALGO", "ALGO-USD",
    "VET", "VET-USD", "HBAR", "HBAR-USD", "EGLD", "EGLD-USD",
    "THETA", "THETA-USD", "FIL", "FIL-USD", "ICP", "ICP-USD",
    "AAVE", "AAVE-USD", "UNI", "UNI-USD", "CRV", "CRV-USD",
    "MKR", "MKR-USD", "COMP", "COMP-USD", "SNX", "SNX-USD",
    "YFI", "YFI-USD", "SUSHI", "SUSHI-USD", "1INCH", "1INCH-USD",
    "DOGE", "DOGE-USD", "SHIB", "SHIB-USD",
}

# Event type patterns
EVENT_PATTERNS = {
    etype: [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in kws]
    for etype, kws in CRYPTO_EVENT_TYPES.items()
}

SYMBOL_PATTERN = re.compile(r"\b(" + "|".join(re.escape(s) for s in sorted(CRYPTO_SYMBOLS, key=len, reverse=True)) + r")\b")


def classify_crypto_event(text: str) -> list[str]:
    """Return list of crypto event types matched in text."""
    matched = []
    for etype, patterns in EVENT_PATTERNS.items():
        if any(p.search(text) for p in patterns):
            matched.append(etype)
    return matched


def extract_symbols(text: str) -> list[str]:
    """Extract crypto symbols from text."""
    return list(set(SYMBOL_PATTERN.findall(text.upper())))


def is_crypto_context(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in ("crypto", "blockchain", "defi", "web3", "token", "coin", "altcoin", "stablecoin", "nft", "dao", "smart contract", "layer 1", "layer 2", "l1", "l2", "rollup", "zk", "zero-knowledge", "consensus", "validator", "staking", "yield farming", "liquidity mining", "amm", "dex", "cex", "cex/dex"))


def extract_event(text: str, source: str, url: str, published_at: str | None) -> list[dict]:
    """Extract structured crypto events from text."""
    if not is_crypto_context(text):
        return []

    event_types = classify_crypto_event(text)
    if not event_types:
        return []

    symbols = extract_symbols(text)

    events = []
    for etype in event_types:
        events.append({
            "type": "crypto_event",
            "subtype": etype,
            "symbols": symbols,
            "source": source,
            "url": url,
            "published_at": published_at,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        })
    return events


def extract_events_from_item(item: dict) -> list[dict]:
    """Extract all crypto events from a corpus item."""
    title = str(item.get("title", "") or "")
    extract = str(item.get("clean_extract", "") or "")
    text = f"{title} {item.get('raw_extract_if_available', '')}".strip()

    if not is_crypto_context(text):
        return []

    events = []
    for source_field in ("title", "clean_extract", "raw_extract_if_available"):
        text = str(item.get(source_field, "") or "")
        if not text:
            continue
        events.extend(extract_event(text, item.get("publisher", "unknown"),
                                   item.get("canonical_url", ""),
                                   item.get("published_at_utc")))

    # Deduplicate by (subtype, symbols)
    seen = set()
    deduped = []
    for e in events:
        key = (e["subtype"], tuple(sorted(e["symbols"])))
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return deduped


if __name__ == "__main__":
    test = "SEC approves spot Bitcoin ETF after years of delays; BTC-USD surges 5%"
    print(classify_crypto_event(test))
    print(extract_symbols(test))
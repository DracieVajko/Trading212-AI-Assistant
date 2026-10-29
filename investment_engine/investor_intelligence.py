"""investor_intelligence.py — track investor recommendations (Cramer inverse, etc.)

Tracks public recommendations from investors (Jim Cramer, Warren Buffett, etc.)
and computes inverse/follow signals. Default mode: OFF (opt-in via custom_rules.json).

Modes:
- FOLLOW: simulate following recommendations
- INVERSE: simulate opposite (Cramer inverse)
- CONTRARIAN_CONFIRMATION: inverse only after independent technical/fundamental confirmation
- IGNORE: track only, no score impact
- PAPER_ONLY: hypothetical trades, no real money

Data sources:
- Cramer: CNBC Mad Money transcripts, Twitter/X, Reddit (r/wallstreetbets, r/investing)
- Buffett: Berkshire Hathaway 13F filings (SEC EDGAR)
- Congress: House/Senate financial disclosures
- Trump: Truth Social, policy announcements

All recommendations are stored with timestamps for backtesting.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Strategy modes
MODE_FOLLOW = "follow"
MODE_INVERSE = "inverse"
MODE_CONTRARIAN = "contrarian_confirmation"
MODE_IGNORE = "ignore"
MODE_PAPER_ONLY = "paper_only"

DEFAULT_MODE = MODE_INVERSE  # Cramer inverse by default when enabled

# Default config (user can override via custom_rules.json)
DEFAULT_CONFIG = {
    "enabled": False,  # Default OFF
    "mode": DEFAULT_MODE,
    "sources": ["cramer"],
    "lookback_days": 14,
    "weight": 0.5,
    "cap": 1.0,
    "min_confidence": 0.7,
    "track_performance": True,
    "paper_trading": True,  # Never use real money for investor signals
}


@dataclass
class InvestorEvent:
    """A tracked investor recommendation."""
    investor: str
    ticker: str
    stance: str  # "bullish", "bearish", "neutral"
    action: str  # "buy", "sell", "mention"
    published_at: str  # ISO timestamp
    source: str  # "cnbc", "twitter", "reddit", "13f", "congress"
    confidence: float = 0.5
    url: str = ""
    raw_text: str = ""
    verified: bool = False


@dataclass
class InvestorSignal:
    """Computed signal from investor events."""
    ticker: str
    investor: str
    mode: str  # follow/inverse/contrarian/ignore/paper_only
    adjustment: float  # score adjustment (-cap to +cap)
    confidence: float
    reason: str
    events: list[InvestorEvent] = field(default_factory=list)


def _load_config(rules: dict) -> dict:
    """Load investor intelligence config from custom_rules.json."""
    cfg = dict(DEFAULT_CONFIG)
    inv_cfg = rules.get("investor_intelligence", {})
    if isinstance(inv_cfg, dict):
        cfg.update(inv_cfg)
    return cfg


def _is_enabled(rules: dict) -> bool:
    """Check if investor intelligence is enabled."""
    cfg = _load_config(rules)
    return bool(cfg.get("enabled", False))


def _get_mode(rules: dict, investor: str = "cramer") -> str:
    """Get strategy mode for an investor."""
    cfg = _load_config(rules)
    modes = cfg.get("modes", {})
    if isinstance(modes, dict) and investor in modes:
        return str(modes[investor])
    return str(cfg.get("mode", DEFAULT_MODE))


def parse_cramer_recommendation(text: str) -> list[InvestorEvent]:
    """Parse a Cramer recommendation from text (CNBC transcript, tweet, etc.).

    Returns list of InvestorEvent. Only explicit buy/sell recommendations
    are extracted; mentions without clear stance are ignored.

    NOTE: This is a heuristic parser. Real implementation should use
    NLP/LLM for better accuracy. Always verify before acting.
    """
    events = []
    if not text:
        return events

    seen = set()

    # Patterns for explicit recommendations
    buy_patterns = [
        r"(?:buy|own|hold|buying|recommending|accumulate)\s+(\w{1,5})(?:\s+and\s+(\w{1,5}))?",
        r"(\w{1,5})\s+(?:is a buy|should be owned)",
        r"i'?m (?:buying|recommending|accumulating)\s+(\w{1,5})(?:\s+and\s+(\w{1,5}))?",
    ]
    sell_patterns = [
        r"(?:sell|avoid|stay away from|don'?t buy|selling)\s+(\w{1,5})(?:\s+and\s+(\w{1,5}))?",
        r"(\w{1,5})\s+(?:is a sell|should be sold|is a no)",
        r"i'?m (?:selling|avoiding)\s+(\w{1,5})(?:\s+and\s+(\w{1,5}))?",
    ]

    text_lower = text.lower()
    for pattern in buy_patterns:
        for match in re.finditer(pattern, text_lower):
            for g in match.groups():
                if g and len(g) <= 5 and g.isalpha():
                    ticker = g.upper()
                    if ticker not in seen:
                        seen.add(ticker)
                        events.append(InvestorEvent(
                            investor="cramer",
                            ticker=ticker,
                            stance="bullish",
                            action="buy",
                            published_at=datetime.now().isoformat(),
                            source="text_parse",
                            confidence=0.6,
                            raw_text=text[:200],
                        ))
    for pattern in sell_patterns:
        for match in re.finditer(pattern, text_lower):
            for g in match.groups():
                if g and len(g) <= 5 and g.isalpha():
                    ticker = g.upper()
                    if ticker not in seen:
                        seen.add(ticker)
                        events.append(InvestorEvent(
                            investor="cramer",
                            ticker=ticker,
                            stance="bearish",
                            action="sell",
                            published_at=datetime.now().isoformat(),
                            source="text_parse",
                            confidence=0.6,
                            raw_text=text[:200],
                        ))

    return events


def compute_investor_signals(
    events: list[InvestorEvent],
    rules: dict,
    held_tickers: set[str] | None = None,
) -> list[InvestorSignal]:
    """Compute signals from investor events based on configured mode.

    Returns list of InvestorSignal with score adjustments.
    """
    if not _is_enabled(rules):
        return []

    held = held_tickers or set()
    cfg = _load_config(rules)
    lookback = int(cfg.get("lookback_days", 14))
    weight = float(cfg.get("weight", 0.5))
    cap = float(cfg.get("cap", 1.0))
    min_conf = float(cfg.get("min_confidence", 0.7))

    signals = []
    for ev in events:
        if ev.confidence < min_conf:
            continue
        mode = _get_mode(rules, ev.investor)
        if mode == MODE_IGNORE:
            continue

        # Compute adjustment based on mode
        action_val = 1.0 if ev.action == "buy" else (-1.0 if ev.action == "sell" else 0.0)
        if mode == MODE_INVERSE:
            adjustment = -action_val * weight
        elif mode == MODE_FOLLOW:
            adjustment = action_val * weight
        elif mode == MODE_CONTRARIAN:
            # Only inverse if independent confirmation exists (placeholder)
            adjustment = -action_val * weight * 0.5  # half weight until confirmed
        elif mode == MODE_PAPER_ONLY:
            adjustment = 0.0  # no score impact, just tracking
        else:
            adjustment = 0.0

        adjustment = max(-cap, min(cap, adjustment))

        reason = f"{ev.investor} {ev.action} {ev.ticker} ({ev.stance}) → mode={mode} → adjustment={adjustment:+.2f}"
        if mode == MODE_INVERSE:
            reason += " [INVERSE: doing opposite]"

        signals.append(InvestorSignal(
            ticker=ev.ticker,
            investor=ev.investor,
            mode=mode,
            adjustment=adjustment,
            confidence=ev.confidence,
            reason=reason,
            events=[ev],
        ))

    return signals


def get_investor_summary(signals: list[InvestorSignal]) -> str:
    """Human-readable summary of investor signals."""
    if not signals:
        return "No investor signals (disabled or no events)."
    lines = ["Investor Intelligence Signals:"]
    for s in signals:
        lines.append(f"  - {s.ticker}: {s.mode} → adjustment {s.adjustment:+.2f} (conf={s.confidence:.2f}) — {s.reason}")
    return "\n".join(lines)


def track_performance(signals: list[InvestorSignal], prices: dict, bench=None) -> dict:
    """Track performance of investor signals over time.

    Returns dict with per-signal performance metrics.
    """
    # Placeholder: real implementation would compare signal direction vs actual price movement
    results = {}
    for s in signals:
        results[s.ticker] = {
            "investor": s.investor,
            "mode": s.mode,
            "adjustment": s.adjustment,
            "confidence": s.confidence,
            "tracked": True,
        }
    return results

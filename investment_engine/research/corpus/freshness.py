"""Phase 5 freshness: 48h decision rule, background labelling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DECISION_MAX_AGE_HOURS = 48.0

# Reference material with its own as-of semantics (earnings calendars,
# analyst consensus snapshots, standing regulatory events). Never presented
# as fresh news and never given a faked fresh date; classified separately
# so reports can show them with their own validity window.
REFERENCE_CATEGORIES = frozenset({
    "earnings_calendar",
    "analyst_consensus",
    "regulatory",
})


def age_hours(published_at_utc: Any, now: datetime | None = None) -> float | None:
    """Hours since publication. None when undated/unparseable."""
    from investment_engine.schemas.research_item import parse_utc

    dt = parse_utc(published_at_utc)
    if dt is None:
        return None
    ref = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return (ref - dt).total_seconds() / 3600.0


def classify(age_h: float | None, tier: int, category: str,
             max_age_hours: float = DECISION_MAX_AGE_HOURS) -> str:
    """DECISION | BACKGROUND | BACKGROUND-REFERENCE | EXCLUDED-UNDATED.

    BACKGROUND-REFERENCE is background with its own as-of validity (never
    decision-relevant, never re-dated as fresh).
    """
    from investment_engine.research.corpus.tiers import may_enter_decision

    if age_h is None:
        return "EXCLUDED-UNDATED"
    if str(category or "").strip().lower() in REFERENCE_CATEGORIES:
        return "BACKGROUND-REFERENCE"
    if not may_enter_decision(tier, category):
        return "BACKGROUND"
    if age_h < 0 or age_h > max_age_hours:
        return "BACKGROUND"
    return "DECISION"

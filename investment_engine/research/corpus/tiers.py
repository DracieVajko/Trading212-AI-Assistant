"""Phase 5 source tiers and decision gating."""

from __future__ import annotations

# T0 broker / official IR / exchange notices. T1 major wire + regulators.
# T2 established financial press + data pages. T3 social/forums/ideas.
TIER_OFFICIAL = 0
TIER_WIRE = 1
TIER_PRESS = 2
TIER_SOCIAL = 3

DECISION_TIERS = frozenset({0, 1, 2})

# Categories that are always LOW_CONFIDENCE sentiment-only (never actionable).
SOCIAL_CATEGORIES = frozenset({"reddit", "social", "stocktwits", "tradingview_ideas", "x"})


def tier_for_category(category: str, explicit_tier: int | None = None) -> int:
    """Social categories are ALWAYS T3 (explicit overrides cannot launder
    social content into the decision set). Otherwise explicit tier wins."""
    if str(category or "").strip().lower() in SOCIAL_CATEGORIES:
        return TIER_SOCIAL
    if explicit_tier is not None:
        try:
            return max(0, min(3, int(explicit_tier)))
        except (TypeError, ValueError):
            pass
    return TIER_PRESS


def may_enter_decision(tier: int, category: str) -> bool:
    """T0-T2 only; social categories never enter the decision set."""
    if str(category or "").strip().lower() in SOCIAL_CATEGORIES:
        return False
    return int(tier) in DECISION_TIERS


# Completeness multipliers: a headline is not a read article. An editorial
# prediction is not a confirmed fact at any tier — corroboration, not the
# masthead, is what raises confidence.
COMPLETENESS_FACTOR = {
    "FULL_TEXT": 1.0,
    "PARTIAL_TEXT": 0.85,
    "RSS_SUMMARY": 0.7,
    "HEADLINE_ONLY": 0.5,
    "UNKNOWN": 0.6,
}

_BASE_CREDIBILITY = {0: 95.0, 1: 80.0, 2: 60.0, 3: 25.0}


def credibility_for(item: dict) -> float:
    """Evidence-weighted credibility (0-100). Never raises.

    tier base × completeness factor × aggregator penalty + corroboration
    bonus (+5 per extra independent publisher, cap +10). A T1 headline
    from an aggregator link scores below a T2 full-text primary item —
    the masthead alone never decides.
    """
    try:
        tier = max(0, min(3, int(item.get("source_tier", 3))))
    except (TypeError, ValueError):
        tier = 3
    base = _BASE_CREDIBILITY.get(tier, 25.0)
    factor = COMPLETENESS_FACTOR.get(str(item.get("completeness", "UNKNOWN")).upper(), 0.6)
    if str(item.get("url_kind", "")) == "aggregator_url":
        factor *= 0.9
    try:
        extra = max(0, int(item.get("corroboration", 1) or 1) - 1)
    except (TypeError, ValueError):
        extra = 0
    bonus = min(10, extra * 5)
    return round(max(0.0, min(100.0, base * factor + bonus)), 1)


# Gate threshold used across the pipeline (news_engine filter default).
DECISION_GATE_SCORE = 60.0


def adjust_relevance(item: dict, max_age_hours: float = 48.0) -> tuple[float, list[str]]:
    """Evidence-adjusted relevance + transparent basis. Never raises.

    Starts from the fetcher score, then: HEADLINE_ONLY -10, aggregator
    link -5, corroboration +5/extra source (cap +10). Fresh (≤48h),
    tier≤2 items with a confirmed entity tag never fall below the decision
    gate — the floor is recorded in the basis, not hidden. Generic,
    undated, or entity-less items keep their honest lower value.
    """
    try:
        score = float(item.get("relevance_score", 0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    basis: list[str] = [f"fetcher={score:.0f}"]
    completeness = str(item.get("completeness", "UNKNOWN")).upper()
    if completeness == "HEADLINE_ONLY":
        score -= 10
        basis.append("headline_only=-10")
    if str(item.get("url_kind", "")) == "aggregator_url":
        score -= 5
        basis.append("aggregator=-5")
    try:
        extra = max(0, int(item.get("corroboration", 1) or 1) - 1)
    except (TypeError, ValueError):
        extra = 0
    if extra:
        bonus = min(10, extra * 5)
        score += bonus
        basis.append(f"corroborated+{bonus}")
    # Gate floor: fresh + tiered + entity-confirmed stays decision-eligible
    # by policy; the floor itself is part of the auditable basis.
    try:
        age = item.get("age_hours")
        tier = int(item.get("source_tier", 3))
    except (TypeError, ValueError):
        age, tier = None, 3
    has_entity = bool(item.get("ticker_tags"))
    if (isinstance(age, (int, float)) and 0.0 <= age <= max_age_hours
            and tier <= 2 and has_entity and score < DECISION_GATE_SCORE):
        basis.append(f"gate-floor={DECISION_GATE_SCORE:.0f}")
        score = DECISION_GATE_SCORE
    return round(max(0.0, min(100.0, score)), 1), basis

"""Research enrichment: T212 standalone holdings and PIE deep dive.

This module owns the per-position enrichment loop (technicals, news, earnings,
dividends, analyst consensus, energy snapshot, corpus) plus the standalone and
PIE AI sections. It was extracted from ``run_engine`` to keep the orchestrator
readable.

This module delegates to:
- ``holdings_enrichment`` for standalone T212 position enrichment
- ``pie_enrichment`` for PIE blocks and AI sections
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from investment_engine.config.settings import EngineSettings
from investment_engine.run_phases.holdings_enrichment import (
    HoldingsEnrichmentInputs as _HoldingsInputs,
    enrich_holdings as _enrich_holdings,
)
from investment_engine.run_phases.pie_enrichment import (
    PieEnrichmentInputs as _PieInputs,
    enrich_pies as _enrich_pies,
)

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentInputs:
    """All values the enrichment phase reads from the orchestrator."""

    assets: list[dict[str, Any]]
    tech_pies: list[dict[str, Any]]
    renewable_pies: list[dict[str, Any]]
    passive_pies: list[dict[str, Any]]
    all_active_assets: list[dict[str, Any]]
    t212_data: dict[str, Any]
    snapshot: Any
    settings: EngineSettings
    settings_dict: dict[str, Any]
    provider: Any
    run_id: str
    reports_dir: str
    language: str
    portfolio_context: dict[str, Any]
    canonical_map: dict[str, Any]
    canonical_display_note: str
    canonical_note: str
    regime_context: str
    decision_sections: list[str] = field(default_factory=list)
    verbose_sections: list[str] = field(default_factory=list)
    source_ledger: list[dict[str, Any]] = field(default_factory=list)
    news_by_symbol: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    playwright_earnings: int = 0


@dataclass
class EnrichmentResult:
    """Everything the later report phases consume from enrichment."""

    standalone: list[dict[str, Any]]
    pie_blocks: list[dict[str, Any]]
    extra_tech: dict[str, dict]
    extra_news: dict[str, list[dict]]
    extra_earn: dict[str, str]
    playwright_stats: dict
    tvnews_stats: dict
    corpus_info: dict
    corpus_run_id: str
    universe_info: dict
    yahoo_by_display: dict[str, str | None]
    known_clean: set[str]
    aliases: dict[str, Any]
    analyst_consensus_map: dict[str, str]
    dividends_12m: dict[str, dict]
    energy_snapshot: dict
    unified_technicals_seed: dict[str, Any]
    decision_sections: list[str]
    verbose_sections: list[str]
    source_ledger: list[dict[str, Any]]


def build_enrichment(inputs: EnrichmentInputs) -> EnrichmentResult:
    """Run the per-position enrichment and PIE/standalone AI sections."""

    # Step 1: Enrich standalone holdings
    holdings_result = _enrich_holdings(_HoldingsInputs(
        assets=inputs.assets,
        tech_pies=inputs.tech_pies,
        renewable_pies=inputs.renewable_pies,
        passive_pies=inputs.passive_pies,
        all_active_assets=inputs.all_active_assets,
        t212_data=inputs.t212_data,
        snapshot=inputs.snapshot,
        settings=inputs.settings,
        settings_dict=inputs.settings_dict,
        run_id=inputs.run_id,
        reports_dir=inputs.reports_dir,
        language=inputs.language,
        portfolio_context=inputs.portfolio_context,
        known_clean=set(),
        aliases={},
    ))

    # Step 2: Enrich PIE blocks (depends on standalone holdings results)
    pie_result = _enrich_pies(_PieInputs(
        assets=inputs.assets,
        tech_pies=inputs.tech_pies,
        renewable_pies=inputs.renewable_pies,
        passive_pies=inputs.passive_pies,
        all_active_assets=inputs.all_active_assets,
        t212_data=inputs.t212_data,
        standalone=holdings_result.standalone,
        settings=inputs.settings,
        settings_dict=inputs.settings_dict,
        provider=inputs.provider,
        run_id=inputs.run_id,
        reports_dir=inputs.reports_dir,
        language=inputs.language,
        portfolio_context=inputs.portfolio_context,
        canonical_map=inputs.canonical_map,
        canonical_display_note=inputs.canonical_display_note,
        canonical_note=inputs.canonical_note,
        regime_context=inputs.regime_context,
        decision_sections=inputs.decision_sections,
        verbose_sections=inputs.verbose_sections,
        source_ledger=inputs.source_ledger,
        news_by_symbol=holdings_result.news_by_symbol,
        yahoo_by_display=holdings_result.yahoo_by_display,
        known_clean=holdings_result.known_clean,
        aliases=holdings_result.aliases,
        playwright_earnings=inputs.playwright_earnings,
    ))

    return EnrichmentResult(
        standalone=holdings_result.standalone,
        pie_blocks=pie_result.pie_blocks,
        extra_tech=holdings_result.extra_tech,
        extra_news=holdings_result.extra_news,
        extra_earn=holdings_result.extra_earn,
        playwright_stats=pie_result.playwright_stats,
        tvnews_stats=pie_result.tvnews_stats,
        corpus_info=pie_result.corpus_info,
        corpus_run_id=pie_result.corpus_run_id,
        universe_info=pie_result.universe_info,
        yahoo_by_display=holdings_result.yahoo_by_display,
        known_clean=holdings_result.known_clean,
        aliases=holdings_result.aliases,
        analyst_consensus_map=holdings_result.analyst_consensus_map,
        dividends_12m=holdings_result.dividends_12m,
        energy_snapshot=holdings_result.energy_snapshot,
        unified_technicals_seed=holdings_result.unified_technicals_seed,
        decision_sections=pie_result.decision_sections,
        verbose_sections=pie_result.verbose_sections,
        source_ledger=pie_result.source_ledger,
    )

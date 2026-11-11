"""Run setup and asset-universe planning."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from investment_engine import liveness as _lv
from investment_engine.config.settings import EngineSettings
from investment_engine.research.pies import PieLoader
from investment_engine.run_state import FALLBACK_EVENTS as _FALLBACK_EVENTS
from investment_engine.run_state import STAGE_ATTRIBUTION as _STAGE_ATTRIBUTION

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RunSetup:
    """Per-run identity and reporting paths."""

    settings: EngineSettings
    run_id: str
    reports_dir: str
    language: str
    portfolio_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class UniversePlan:
    """Pie groups, active assets, and the known clean-ticker universe."""

    pies: list[dict[str, Any]]
    tech_pies: list[dict[str, Any]]
    renewable_pies: list[dict[str, Any]]
    passive_pies: list[dict[str, Any]]
    crypto_assets: list[dict[str, Any]]
    tech: list[dict[str, str]]
    renewable: list[dict[str, str]]
    other: list[dict[str, str]]
    crypto: list[dict[str, str]]
    all_active_assets: list[dict[str, Any]]
    known_clean: set[str]
    known_names_base: dict[str, str]


def prepare_run(
    settings: EngineSettings | None,
    portfolio_context: dict[str, Any] | None,
) -> RunSetup:
    """Reset per-run state, arm the watchdog, and resolve run identity."""
    from investment_engine.providers.generation import note_unreachable_local_providers
    from investment_engine.providers.telemetry import reset_local_ai_tracker
    from investment_engine.run_state import reset_run_budget

    settings = settings or EngineSettings.from_defaults()
    context = dict(portfolio_context or {})
    run_id = str(context.get("run_id") or uuid.uuid4().hex[:8])
    reports_dir = ROOT / "reports"
    reset_run_budget()  # monotonic budget
    _lv.reset_degraded()
    try:
        from investment_engine.providers.fallback import ChainedFallbackProvider

        ChainedFallbackProvider.reset_run_cooldowns()
    except Exception:
        pass

    watchdog_s = _lv.resolve_watchdog_seconds(_lv.RUN_BUDGET.seconds)
    _lv.arm_watchdog(
        watchdog_s,
        dump_path=Path(reports_dir) / "logs" / f"watchdog_stack_{run_id}.txt",
        sentinel_path=Path(reports_dir) / "logs" / f".watchdog_armed_{run_id}",
        label=f"run_engine:{run_id}",
    )

    for noisy in ("yfinance", "peewee", "urllib3.connectionpool", "urllib3", "numba"):
        try:
            logging.getLogger(noisy).setLevel(logging.WARNING)
        except Exception:
            pass

    _FALLBACK_EVENTS.clear()
    _STAGE_ATTRIBUTION.clear()
    reset_local_ai_tracker()
    try:
        from investment_engine.providers.fallback import reset_circuit_breaker

        reset_circuit_breaker()
    except Exception:
        pass
    try:
        from investment_engine.research.market_data import reset_market_data_registry

        # Branch runs share the same market data: the second branch must reuse
        # the bars the first one fetched instead of downloading them again.
        if not context.get("reuse_market_data"):
            reset_market_data_registry()
    except Exception:
        pass

    language = str(context.get("language") or "English")
    note_unreachable_local_providers(settings)
    return RunSetup(
        settings=settings,
        run_id=run_id,
        reports_dir=reports_dir,
        language=language,
        portfolio_context=context,
    )


def build_universe_plan(assets: list[dict[str, Any]]) -> UniversePlan:
    """Group assets into pie-driven active buckets and resolve known tickers."""
    from investment_engine.main import _symbol
    from investment_engine.portfolio.symbols import build_known_maps

    pies = PieLoader().load_all()
    tech_pies = [pie for pie in pies if "tech" in pie["name"].lower()]
    renewable_pies = [pie for pie in pies if "renew" in pie["name"].lower()]
    passive_pies = [pie for pie in pies if pie not in tech_pies and pie not in renewable_pies]
    crypto_assets = [
        asset for asset in assets if str(asset.get("group", "")).upper() == "CRYPTO"
    ]

    def entries_from_pies(group: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {"ticker": holding["slice"], "name": holding["name"]}
            for pie in group
            for holding in pie["holdings"]
        ]

    tech = entries_from_pies(tech_pies)
    renewable = entries_from_pies(renewable_pies)
    existing = {item["ticker"] for item in tech + renewable}
    other = [
        {"ticker": _symbol(asset), "name": str(asset.get("name") or _symbol(asset))}
        for asset in assets
        if str(asset.get("group", "")).upper() in {"TECH_PIE", "SHORT_TERM_TRADING"}
        and _symbol(asset) not in existing
    ]
    crypto = [
        {"ticker": _symbol(asset), "name": str(asset.get("name") or _symbol(asset))}
        for asset in crypto_assets
    ]

    try:
        early_slices = [
            (holding.get("slice"), holding.get("name"))
            for pie in (tech_pies + renewable_pies + passive_pies)
            for holding in (pie.get("holdings", []) if isinstance(pie, dict) else [])
        ]
        known_clean, known_names_base = build_known_maps(early_slices, assets)
    except Exception:
        known_clean, known_names_base = set(), {}

    return UniversePlan(
        pies=pies,
        tech_pies=tech_pies,
        renewable_pies=renewable_pies,
        passive_pies=passive_pies,
        crypto_assets=crypto_assets,
        tech=tech,
        renewable=renewable,
        other=other,
        crypto=crypto,
        all_active_assets=tech + renewable + other + crypto,
        known_clean=known_clean,
        known_names_base=known_names_base,
    )

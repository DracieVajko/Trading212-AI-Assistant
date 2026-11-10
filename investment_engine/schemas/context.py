"""Typed shapes for the hottest engine seams.

These are TypedDicts rather than dataclasses because the values cross JSON
boundaries and existing callers already pass plain dicts. They give static
checkers and reviewers a named contract without changing runtime behavior.
"""

from __future__ import annotations

from typing import Any, TypedDict


class PortfolioRow(TypedDict, total=False):
    display_symbol: str
    ticker: str
    weight: float
    pnl_pct: float
    signal: str
    market_value: float
    sector: str
    isin: str


class T212Snapshot(TypedDict, total=False):
    status: str
    account_summary: dict[str, Any]
    cash: dict[str, Any]
    positions: list[dict[str, Any]]
    all_positions: list[dict[str, Any]]
    reconciliation_v2: dict[str, Any]
    reconciliation_ok: bool
    account_id: str
    timestamp: str


class AIContextInputs(TypedDict, total=False):
    portfolio_rows: list[PortfolioRow]
    regime: str
    t212_data: T212Snapshot
    news: dict[str, list[dict[str, Any]]]
    earnings: dict[str, str]
    language: str


class AssetInput(TypedDict, total=False):
    broker_symbol: str
    yahoo_symbol: str
    name: str
    group: str
    enabled: bool
    ticker: str


class NewsFetchResultDict(TypedDict, total=False):
    news_by_symbol: dict[str, list[dict[str, Any]]]
    all_news_items: list[Any]
    trump_tracking: dict[str, Any]
    commodity_news: dict[str, Any]
    analyst_news: dict[str, Any]
    slovak_news: dict[str, Any]
    reddit_news: dict[str, Any]
    news_context_path: str | None


class RunResult(TypedDict, total=False):
    """Canonical ``run_engine`` result contract.

    Keys are the ones the CLI wrapper, brief builder, and manifest consume.
    ``total=False`` keeps the historical optional-key behavior while giving
    static checkers a named shape.
    """

    markdown: str
    brief_markdown: str
    snapshot_markdown: str
    deep_dive_markdown: str
    run_id: str
    brief_generated_at: str
    requested_mode: str
    effective_mode: str
    environment_id: str
    local_ai_attempts: int
    local_ai_requests_sent: int
    local_ai_attempts_blocked: int
    brief_metadata: dict[str, Any]
    snapshot_metadata: dict[str, Any]
    context_file: str
    tech_tickers: list[dict[str, str]]
    renewable_tickers: list[dict[str, str]]
    crypto: list[dict[str, str]]
    passive_pies: list[dict[str, Any]]
    recent_news: dict[str, list[dict[str, Any]]]
    trump_watch: dict[str, Any]
    earnings_dates: dict[str, Any]
    settings: dict[str, Any]
    report_mode: str
    market_regime: Any
    providers_per_stage: dict[str, dict]
    skill_outputs: dict[str, dict]
    skill_versions: dict[str, str]
    order_plans: dict[str, Any]
    investment_policy: dict[str, Any]
    universe: dict[str, Any]
    playwright: dict[str, Any]
    tvnews: dict[str, Any]
    research_corpus: dict[str, Any]
    research_universe: dict[str, Any]
    previous_run: dict[str, Any]
    source_status: list[dict[str, Any]]
    source_status_summary: dict[str, Any]
    research_note: str
    research_watchlist_markdown: str
    execution_mode_lines: list[str]
    api_execution_mode: str
    disabled_providers: list[str]
    ai_recommendations: dict[str, Any]
    t212_data: T212Snapshot
    reconciliation: dict[str, Any]
    account_performance: dict[str, Any]
    t212_statement_reconciliation: dict[str, Any]
    cash_flow_ledger_metadata: dict[str, Any]
    portfolio_rows: list[PortfolioRow]
    issuer_exposure: Any
    schedule_profile: Any
    monitoring_items: list[dict[str, Any]]
    regime_result: Any
    decision_news: list[dict[str, Any]]
    decision_news_selected: list[dict[str, Any]]
    news_filter_stats: dict[str, Any]
    catalyst_radar: list[dict[str, Any]]
    earnings_7d: dict[str, Any]
    earnings_provenance: dict[str, dict[str, str]]
    dividends_12m: dict[str, dict]
    analyst_consensus: dict[str, Any]
    energy_snapshot: dict[str, Any]
    unavailable_sources: list[str]
    run_budget: dict[str, Any]
    ideas: list[dict[str, Any]]
    portfolio_names: dict[str, str]
    failed_tickers: list[dict[str, Any]]
    _run_status_inputs: dict[str, Any]

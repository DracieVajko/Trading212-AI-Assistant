from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

from investment_engine.config.settings import EngineSettings
from investment_engine.schemas.context import AssetInput

# Liveness primitives


# Compact record of LLM fallback events for the current run. Rendered as a
# one-line provider note in the report (no stack traces, no secrets).

# Summary guardrails: the report is advisory and executes no orders. Without
# this, the model narrates trades that never happened (live: "RNDRUSDT sold",
# "tech trimmed") and turns watchlist names into owned positions.
SUMMARY_GUARDRAILS = (
    "HARD RULES: this run executed no trades. Never claim that any position was "
    "bought, sold, trimmed, liquidated, added to, or reduced unless an explicit "
    "executed-order list is supplied (none is). Describe only current holdings, "
    "signals, and risks. Never present watchlist or research-only tickers as "
    "owned positions. If a claim is not supported by the supplied decisions, "
    "omit it."
)

# Run budget: replaced by _lv.RUN_BUDGET (monotonic). Kept for backwards compat.
_RUN_DEADLINE_S: float = 900.0
_RUN_START_TIME: float = 0.0


# Helpers below were extracted into focused modules. They are re-exported here
# with their historical private names so existing imports and tests keep
# working; new code should import the public names from the owning module.
from investment_engine.reporting.formatters import (  # noqa: E402,F401
    apply_fail_guards as _apply_fail_guards,
    deterministic_summary as _deterministic_summary,
    ensure_consistent_summary as _ensure_consistent_summary,
    format_cash_deployment as _format_cash_deployment,
    format_earnings_radar as _format_earnings_radar,
    format_news as _format_news,
    format_trump_watch as _format_trump_watch,
    kpi_dashboard as _kpi_dashboard,
    methodology_block as _methodology_block,
)
from investment_engine.reporting.sections import (  # noqa: E402,F401
    build_monitoring_block as _build_monitoring_block,
    build_priority_actions_table as _build_priority_actions_table,
    derive_top_risks as _derive_top_risks,
    enforce_canonical_in_pie_section as _enforce_canonical_in_pie_section,
    hold_trigger_reason as _hold_trigger_reason,
    passive_pie_lines as _passive_pie_lines,
    provider_fallback_note as _provider_fallback_note,
    safe_money as _safe_money,
    safe_pct as _safe_pct,
    safe_w as _safe_w,
    strip_priority_actions_from_summary as _strip_priority_actions_from_summary,
    validate_new_ideas as _validate_new_ideas,
)
from investment_engine.providers.generation import (  # noqa: E402,F401
    annotate_skill_output as _annotate_skill_output,
    cfg_get as _cfg_get,
    deterministic_fallback as _deterministic_fallback,
    execution_mode_lines as _execution_mode_lines,
    generate_with_fallback as _generate_with_fallback,
    model_for_stage as _model_for_stage,
    note_deterministic_skill as _note_deterministic_skill,
    note_unreachable_local_providers as _note_unreachable_local_providers,
    record_fallback as _record_fallback,
    revive_locals_if_due as _revive_locals_if_due,
    try_lmstudio_stage as _try_lmstudio_stage,
)
from investment_engine.fetching import (  # noqa: E402,F401
    NewsFetchResult,
    build_regime_context as _build_regime_context,
    fetch_all_news_parallel as _fetch_all_news_parallel,
    fetch_finviz_safe as _fetch_finviz_safe,
    fetch_t212_data as _fetch_t212_data,
    is_us_symbol as _is_us_symbol,
    load_symbol_aliases as _load_symbol_aliases,
    symbol as _symbol,
    t212_yahoo_symbol as _t212_yahoo_symbol,
    yahoo_symbol as _yahoo_symbol,
)
from investment_engine.research.earnings_fetch import (  # noqa: E402,F401
    analyst_consensus_bundle as _analyst_consensus_bundle,
    fetch_earnings_fast as _fetch_earnings_fast,
    fetch_earnings_for_symbols as _fetch_earnings_for_symbols,
    fetch_news_for_extra_tickers as _fetch_news_for_extra_tickers,
    fetch_technicals_parallel as _fetch_technicals_parallel,
    fill_earnings_layer2 as _fill_earnings_layer2,
    merge_calendar_earnings as _merge_calendar_earnings,
    tech_summary_line as _tech_summary_line,
)
from investment_engine.providers.recommendations import (  # noqa: E402,F401
    build_ai_recommendations as _build_ai_recommendations,
)
from investment_engine.portfolio.performance import (  # noqa: E402,F401
    resolve_account_performance as _resolve_account_performance,
)
from investment_engine.reporting.portfolio_view import (  # noqa: E402,F401
    apply_fail_watchlist_sweep as _apply_fail_watchlist_sweep,
    build_portfolio_names as _build_portfolio_names,
    canonical_decisions as _canonical_decisions,
    portfolio_tickers_for_priority as _portfolio_tickers_for_priority,
    sanitized_settings as _sanitized_settings,
    sanitized_t212_data as _sanitized_t212_data,
)
from investment_engine.reporting.context_archive import (  # noqa: E402,F401
    save_ai_context as _save_ai_context,
)
from investment_engine.reporting.sections import headlines_block as _headlines_block  # noqa: E402,F401
from investment_engine.run_state import (  # noqa: E402,F401
    build_run_budget as _build_run_budget,
    reset_run_budget as _reset_run_budget,
    run_deadline_exceeded as _run_deadline_exceeded,
)




# Local AI attempt tracking: distinguishes blocked vs sent requests.
# local_ai_attempts: total attempts to call local AI providers
# local_ai_requests_sent: actual HTTP requests sent to local AI
# local_ai_attempts_blocked: attempts blocked before sending (e.g., API_ONLY mode)








































def run_engine(
    assets: List[AssetInput],
    portfolio_context: Dict[str, Any] | None = None,
    settings: EngineSettings | None = None,
) -> Dict[str, Any]:
    """Thin facade: the orchestrator lives in investment_engine.run_engine."""
    from investment_engine.run_engine import run_engine as _impl

    return _impl(assets, portfolio_context=portfolio_context, settings=settings)








# Stage sets: single source of truth lives in providers.presets; these
# private aliases keep the old import path working (tests pin identity).
from investment_engine.providers.presets import FINANCE_STAGES as _FINANCE_STAGES  # noqa: F401
from investment_engine.providers.presets import THINKING_STAGES as _THINKING_STAGES  # noqa: F401
from investment_engine.providers.presets import WRITER_STAGES as _WRITER_STAGES  # noqa: F401













































































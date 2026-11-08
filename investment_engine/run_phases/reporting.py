"""Report assembly phase: briefs, diagnostics, attribution, and result dict.

Extracted from ``run_engine``; this module owns the deterministic report
documents and the final run-result payload.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from investment_engine import liveness as _lv
from investment_engine.config.settings import EngineSettings
from investment_engine.portfolio import t212_view
from investment_engine.portfolio.performance import resolve_account_performance
from investment_engine.providers.generation import (
    execution_mode_lines as _execution_mode_lines,
)
from investment_engine.providers.telemetry import LOCAL_AI_TRACKER as _LOCAL_AI_TRACKER
from investment_engine.reporting.formatters import format_cash_deployment
from investment_engine.reporting.portfolio_view import (
    sanitized_settings,
    sanitized_t212_data,
)
from investment_engine.research.corpus import source_status as _srcstat
from investment_engine.research.earnings_fetch import analyst_consensus_bundle
from investment_engine.run_state import STAGE_ATTRIBUTION as _STAGE_ATTRIBUTION
from investment_engine.run_state import build_run_budget
from investment_engine.schemas.context import RunResult

logger = logging.getLogger(__name__)


@dataclass
class ReportInputs:
    """Everything the report phase reads from the orchestrator."""

    settings: EngineSettings
    settings_dict: dict[str, Any]
    run_id: str
    start_time: float
    portfolio_context: dict[str, Any]
    assets: list[dict[str, Any]]
    all_active_assets: list[dict[str, Any]]
    tech: list[dict[str, str]]
    renewable: list[dict[str, str]]
    other: list[dict[str, str]]
    crypto: list[dict[str, str]]
    passive_pies: list[dict[str, Any]]
    known_clean: set[str]
    aliases: dict[str, Any]
    t212_data: dict[str, Any]
    recon: dict[str, Any]
    regime_result: Any
    ai_recs: dict[str, Any]
    canonical_map: dict[str, Any]
    portfolio_rows: list[dict[str, Any]]
    portfolio_names: dict[str, str]
    unified_technicals: dict[str, Any]
    earnings: dict[str, Any]
    earnings_status: dict[str, tuple[str, str]]
    earnings_provenance: dict[str, dict[str, str]]
    news_by_symbol: dict[str, list[dict[str, Any]]]
    trump_tracking: dict[str, Any]
    commodity_news: dict[str, Any]
    analyst_news: dict[str, Any]
    source_ledger: list[dict[str, Any]]
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
    analyst_consensus_map: dict[str, str]
    dividends_12m: dict[str, dict]
    energy_snapshot: dict
    issuer_exposure: Any
    order_plans: dict[str, Any]
    policy_state: dict[str, Any]
    skill_outputs: dict[str, dict]
    skill_versions: dict[str, str]
    candidate_section: str
    summary_section: str
    context_file: Any


def build_report(inputs: ReportInputs) -> RunResult:
    """Render the decision brief, snapshot, deep dive, and result payload."""
    settings = inputs.settings
    settings_dict = inputs.settings_dict
    run_id = inputs.run_id
    start_time = inputs.start_time
    portfolio_context = inputs.portfolio_context
    assets = inputs.assets
    all_active_assets = inputs.all_active_assets
    tech = inputs.tech
    renewable = inputs.renewable
    other = inputs.other
    crypto = inputs.crypto
    passive_pies = inputs.passive_pies
    known_clean = inputs.known_clean
    aliases = inputs.aliases
    t212_data = inputs.t212_data
    recon = inputs.recon
    regime_result = inputs.regime_result
    ai_recs = inputs.ai_recs
    canonical_map = inputs.canonical_map
    portfolio_rows = inputs.portfolio_rows
    portfolio_names = inputs.portfolio_names
    unified_technicals = inputs.unified_technicals
    earnings = inputs.earnings
    earnings_status = inputs.earnings_status
    earnings_provenance = inputs.earnings_provenance
    news_by_symbol = inputs.news_by_symbol
    trump_tracking = inputs.trump_tracking
    commodity_news = inputs.commodity_news
    analyst_news = inputs.analyst_news
    source_ledger = inputs.source_ledger
    standalone = inputs.standalone
    pie_blocks = inputs.pie_blocks
    playwright_stats = inputs.playwright_stats
    tvnews_stats = inputs.tvnews_stats
    corpus_info = inputs.corpus_info
    _corpus_run_id = inputs.corpus_run_id
    universe_info = inputs.universe_info
    yahoo_by_display = inputs.yahoo_by_display
    analyst_consensus_map = inputs.analyst_consensus_map
    dividends_12m = inputs.dividends_12m
    energy_snapshot = inputs.energy_snapshot
    issuer_exposure = inputs.issuer_exposure
    order_plans = inputs.order_plans
    policy_state = inputs.policy_state
    skill_outputs = inputs.skill_outputs
    skill_versions = inputs.skill_versions
    candidate_section = inputs.candidate_section
    summary_section = inputs.summary_section
    context_file = inputs.context_file
    _recon = recon

    # --- Two-document reporting: decision brief (concise) + snapshot (full) ---
    from investment_engine.reporting.documents import (
        build_monitoring_items as _mon_items,
    )
    from investment_engine.reporting.documents import (
        extract_validated_ideas as _extract_ideas,
    )
    from investment_engine.reporting.documents import (
        render_brief as _render_brief,
    )
    from investment_engine.reporting.documents import (
        render_snapshot as _render_snapshot,
    )
    from investment_engine.research.market_data import (
        filter_earnings_window as _filter_7d,
    )
    from investment_engine.research.market_data import report_now_bta as _now_bta
    from investment_engine.research.news_engine import (
        filter_decision_news as _filter_news,
    )

    report_dt = _now_bta()
    try:
        report_date = report_dt.date()
    except Exception:
        from datetime import date as _d
        report_date = _d.today()

    # Explicit PIE-level warnings: pie aggregate (matched sample) down <= -5%.
    pie_warnings: dict[str, str] = {}
    try:
        for b in pie_blocks or []:
            matched = [s for s in (b.get("sample", []) or []) if s.get("matched")]
            if not matched:
                continue
            avg = sum(float(s.get("pnl_pct", 0) or 0) for s in matched) / len(matched)
            if avg <= -5.0:
                for s in matched:
                    try:
                        from investment_engine.portfolio.symbols import (
                            to_display_symbol as _tdw,
                        )
                        pie_warnings[_tdw(s.get("slice", ""), known_clean)] = (
                            f"PIE {b.get('name')} aggregate {avg:+.1f}%")
                    except Exception:
                        pass
    except Exception:
        pie_warnings = {}

    # Watchlist ideas first (validated ticker + evidence + URL + supported data).
    try:
        from investment_engine.portfolio.symbols import support_state as _ssw
        from investment_engine.portfolio.symbols import to_yahoo_symbol as _tyw
        def _idea_supported(ticker: str) -> bool:
            try:
                return _ssw(_tyw(ticker, ticker, aliases), "market_data") == "SUPPORTED"
            except Exception:
                return False
    except ImportError:
        def _idea_supported(ticker: str) -> bool:
            return True
    ideas = _extract_ideas(candidate_section, news_by_symbol, _idea_supported)

    row_displays = {str(r.get("display_symbol") or r.get("ticker") or "").strip().upper()
                    for r in (portfolio_rows or []) if isinstance(r, dict)}
    pie_sample_displays: set[str] = set()
    try:
        for b in pie_blocks or []:
            for s in (b.get("sample", []) or []):
                d = s.get("display")
                if d:
                    pie_sample_displays.add(str(d).strip().upper())
    except Exception:
        pass
    idea_tickers = {str(i.get("ticker", "") or "").strip().upper() for i in ideas}
    earnings_allowed = set(row_displays) | set(pie_sample_displays) | set(idea_tickers)
    earnings_events: list[dict] = []
    for disp, val in (earnings_status or {}).items():
        d = val[0][:10] if isinstance(val, (tuple, list)) and val and isinstance(val[0], str) else None
        if not d:
            continue
        key = str(disp).strip().upper()
        if key in earnings_allowed:
            earnings_events.append({"display": key, "company": portfolio_names.get(key, key),
                                    "date": d, "source_type": None})
    earnings_7d = _filter_7d(earnings_events, report_dt)
    earnings_7d_displays = {e["display"] for e in earnings_7d.get("in_window", [])}

    monitoring_items = _mon_items(
        portfolio_rows, earnings_status=earnings_status, technicals=unified_technicals,
        pie_warnings=pie_warnings, recon_status=(_recon.get("status") if isinstance(_recon, dict) else "UNKNOWN"),
        report_date=report_date, canonical_map=canonical_map,
    )
    monitoring_by_display = {it["display"]: it["presentation"] for it in monitoring_items}
    for r in portfolio_rows or []:
        if isinstance(r, dict):
            d = str(r.get("display_symbol") or r.get("ticker") or "").strip().upper()
            monitoring_by_display.setdefault(d, "HOLD")

    try:
        news_threshold = int(((settings_dict.get("market_regime", {}) or {}).get("news", {}) or {}).get(
            "min_relevance_score", 30))
    except (TypeError, ValueError):
        news_threshold = 30
    decision_news = _filter_news(
        news_by_symbol, owned=row_displays, constituents=pie_sample_displays,
        watchlist=idea_tickers, earnings=earnings_7d_displays, names=portfolio_names,
        relevance_min=news_threshold, now=report_dt,
        include_macro_unlinked=True,
        min_tier_for_unlinked=1,
        stats=(_news_filter_stats := {}),
    )
    try:
        logger.info(
            "Decision-news filter: input=%d no_title_url=%d below_relevance=%d "
            "too_old=%d unlinked=%d kept=%d",
            _news_filter_stats.get("input", 0), _news_filter_stats.get("no_title_url", 0),
            _news_filter_stats.get("below_relevance", 0), _news_filter_stats.get("too_old", 0),
            _news_filter_stats.get("unlinked", 0), _news_filter_stats.get("kept", 0))
    except Exception:
        pass
    # Catalyst radar (V1, informational): explicit future dates in linked
    # news titles per ticker. Never breaks the run; no signal changes.
    catalyst_radar: list = []
    try:
        from investment_engine.research.news_engine import (
            extract_catalysts as _extract_catalysts,
        )
        catalyst_radar = _extract_catalysts(decision_news, now=report_dt) or []
        if catalyst_radar:
            logger.info(
                "Catalyst radar: %d dated events (%s)", len(catalyst_radar),
                ", ".join(f"{c['ticker']} {c['date']}" for c in catalyst_radar[:8]))
    except Exception as exc:
        logger.debug("Catalyst radar skipped: %s", type(exc).__name__)
    # Relevance diagnostics (threshold review data): score distribution of
    # valid candidates + top near-misses below the bar. No threshold change
    # here — the numbers decide in a later run.
    try:
        _rel_scores: list[tuple[int, str]] = []
        for _sym_entries in (news_by_symbol or {}).values():
            for _rec in _sym_entries or []:
                if isinstance(_rec, dict) and _rec.get("title") and _rec.get("url"):
                    try:
                        _rel_scores.append((int(_rec.get("relevance_score", 0) or 0),
                                            str(_rec.get("title", ""))[:90]))
                    except (TypeError, ValueError):
                        pass
        if _rel_scores:
            _rel_scores.sort(key=lambda t: t[0])
            _vals = [s for s, _ in _rel_scores]
            _near = [f"{s}:{t}" for s, t in _rel_scores if s < news_threshold][-5:]
            logger.info("News relevance: n=%d min=%d med=%d max=%d threshold=%s near-miss=%s",
                        len(_vals), _vals[0], _vals[len(_vals) // 2], _vals[-1],
                        news_threshold, _near or [])
    except Exception:
        pass

    # Research coverage + execution-mode context for both briefs.
    _corpus_decision_n = int((corpus_info.get("counts", {}) or {}).get("decision", 0) or 0)
    if _corpus_decision_n < 3:
        research_note = (
            f"Research coverage insufficient: {_corpus_decision_n} "
            f"validated decision-quality items in the last 48 hours.")
    else:
        research_note = ""
    _api_only_run = bool(getattr(settings, "api_only", False))
    try:
        from investment_engine.config.settings import resolve_execution_mode as _mode2
        _exec_mode = _mode2(settings)
    except Exception:
        _exec_mode = "public" if _api_only_run else "auto"
    _api_only_run = (_exec_mode == "public")
    execution_mode_lines = _execution_mode_lines(settings)
    try:
        from investment_engine.providers.factory import ProviderFactory as _PF2
        disabled_providers = list(_PF2.API_ONLY_DISABLED) if _api_only_run else []
    except Exception:
        disabled_providers = ["LM Studio", "llama.cpp", "Ollama"] if _api_only_run else []

    # Count actual TRIM/SELL plans so the cash line never claims funding the
    # policy engine did not generate (0 plans is the common HOLD state).
    _sell_plan_count = 0
    try:
        _sell_plan_count = sum(
            1 for _plan in (order_plans.get("plans") or [])
            if isinstance(_plan, dict)
            and str(_plan.get("direction", "")).upper() in ("TRIM", "SELL")
        )
    except Exception:
        _sell_plan_count = 0

    if str(_recon.get("status") if isinstance(_recon, dict) else "").upper() == "FAIL":
        cash_line = (f"€{_recon.get('reported_cash', 0):,.2f} reported cash — "
                     f"deployment withheld until account reconciliation passes.")
    else:
        cash_line = format_cash_deployment(
            regime_result, t212_data, ai_recs, portfolio_rows,
            recon_status=(_recon.get("status") if isinstance(_recon, dict) else None),
            sell_plan_count=_sell_plan_count)

    # Account performance: broker equity vs verified net cash flows. Shown
    # even when position reconciliation FAILs; FAIL only blocks new
    # BUY/DCA/deployment instructions (enforced upstream).
    try:
        account_performance, cashflow_metadata = resolve_account_performance(
            t212_data, portfolio_context)
    except Exception as exc:
        logger.debug("Account performance unavailable: %s", type(exc).__name__)
        account_performance, cashflow_metadata = {"performance_status": "Unavailable"}, {}

    # Independent Trading 212 statement reconciliation (optional CSV).
    # API/broker truth stays authoritative; the statement explains the bridge.
    t212_statement_reconciliation: dict = {
        "status": "UNAVAILABLE",
        "reasons": ["No Trading 212 CSV statement was provided for this run."],
    }
    try:
        _stmt_path = str((portfolio_context or {}).get("t212_csv_path", "") or "")
        if _stmt_path and Path(_stmt_path).is_file():
            if str(account_performance.get("performance_status", "")) != "Available":
                t212_statement_reconciliation = {
                    "status": "UNAVAILABLE",
                    "reasons": ["Account performance is unavailable; statement reconciliation skipped."],
                }
            else:
                from investment_engine.accounting.t212_statement import (
                    parse_t212_statement as _parse_stmt,
                )
                from investment_engine.accounting.t212_statement import (
                    reconcile_t212_statement as _reconcile_stmt,
                )
                _stmt = _parse_stmt(_stmt_path)
                _unrealized = sum(
                    float(r.get("unrealized_pnl", 0) or 0)
                    for r in (portfolio_rows or [])
                )
                t212_statement_reconciliation = _reconcile_stmt(
                    _stmt,
                    api_total_deposits_eur=account_performance.get("total_deposits_eur"),
                    api_total_withdrawals_eur=account_performance.get("total_withdrawals_eur"),
                    api_net_deposits_eur=account_performance.get("net_deposits_eur"),
                    api_net_pnl_eur=account_performance.get("net_pnl_after_costs_eur"),
                    api_fees_eur=account_performance.get("fees_eur"),
                    api_interest_eur=account_performance.get("interest_eur"),
                    unrealized_pnl_eur=_unrealized,
                ).to_dict()
        elif _stmt_path:
            t212_statement_reconciliation = {
                "status": "UNAVAILABLE",
                "reasons": [f"Trading 212 CSV not found: {_stmt_path}"],
            }
    except Exception as exc:
        logger.warning("T212 statement reconciliation skipped: %s", exc)
        t212_statement_reconciliation = {
            "status": "UNAVAILABLE",
            "reasons": [f"{type(exc).__name__}: {exc}"],
        }

    brief_md = _render_brief(
        generated_at=report_dt.strftime("%Y-%m-%d %H:%M %Z"),
        regime_result=regime_result, recon=_recon if isinstance(_recon, dict) else {},
        rows=portfolio_rows, monitoring_items=monitoring_items, earnings_7d=earnings_7d,
        decision_news=decision_news, ideas=ideas, cash_line=cash_line,
        performance=account_performance,
        catalyst_radar=catalyst_radar,
        research_note=research_note,
        execution_mode_lines=execution_mode_lines,
        order_plans=order_plans if isinstance(order_plans, dict) else None,
        summary=summary_section,
    )
    snapshot_md = _render_snapshot(
        generated_at=report_dt.strftime("%Y-%m-%d %H:%M %Z"),
        recon=_recon if isinstance(_recon, dict) else {},
        cash=t212_view.cash(t212_data),
        rows=portfolio_rows, monitoring_by_display=monitoring_by_display,
        earnings_status=earnings_status, t212_data=t212_data,
        performance=account_performance, ledger_metadata=cashflow_metadata,
    )

    # Render the statement reconciliation near the top of the decision brief
    # and at the end of the snapshot (English only).
    try:
        from investment_engine.accounting.t212_statement import (
            render_reconciliation_markdown as _render_stmt_md,
        )
        _stmt_md = _render_stmt_md(t212_statement_reconciliation)
        if _stmt_md:
            if "## Summary" in brief_md:
                brief_md = brief_md.replace("## Summary", _stmt_md + "\n\n## Summary", 1)
            else:
                brief_md = brief_md.rstrip() + "\n\n" + _stmt_md + "\n"
            snapshot_md = snapshot_md.rstrip() + "\n\n" + _stmt_md + "\n"
    except Exception as exc:
        logger.debug("T212 statement section skipped: %s", type(exc).__name__)

    elapsed = time.time() - start_time
    print(f"Report generated in {elapsed:.1f}s")

    # Sanitized reconciliation diagnostic object for the JSON output
    # (numerics + status only; no raw payloads, no secrets).
    try:
        _diag_src = _recon if isinstance(_recon, dict) else {}
    except NameError:
        _diag_src = {}
    reconciliation_diagnostic = {
        key: _diag_src.get(key)
        for key in ("total_equity", "positions_value", "implied_cash",
                    "reported_cash", "cash_delta", "threshold", "status")
    }

    # Deep-dive companion brief (15 fixed sections, deterministic, no LLM).
    # Never breaks the run; falls back to a header-only document.
    try:
        from investment_engine.reporting.documents import (
            build_deep_dive as _build_deep_dive,
        )
        deep_dive_md = _build_deep_dive(
            generated_at=report_dt.strftime("%Y-%m-%d %H:%M %Z"),
            run_id=str((portfolio_context or {}).get("run_id", "") or ""),
            regime_result=regime_result,
            recon=_recon if isinstance(_recon, dict) else {},
            rows=portfolio_rows,
            monitoring_items=monitoring_items,
            t212_data=t212_data,
            news_by_symbol=news_by_symbol,
            decision_news=decision_news,
            earnings_7d=earnings_7d,
            ideas=ideas,
            trump_tracking=trump_tracking,
            commodity_news=commodity_news,
            analyst_news=analyst_news,
            order_plans=order_plans if isinstance(order_plans, dict) else None,
            dividends_12m=dividends_12m if "dividends_12m" in dir() else {},
            stage_attribution={k: dict(v) for k, v in _STAGE_ATTRIBUTION.items()},
            result_modes={"api_execution_mode": {"public": "API_ONLY", "locals": "LOCALS"}.get(
                _exec_mode if "_exec_mode" in dir() else "auto", "STANDARD")},
        )
    except Exception as exc:
        logger.debug("Deep-dive brief skipped: %s", type(exc).__name__)
        deep_dive_md = "# Portfolio Deep Dive\n\nNo coverage this run.\n"

    # Failed-ticker ledger: UNRESOLVED mappings + market-data fetch misses.
    # Never breaks the run; empty list when everything resolved.
    try:
        from investment_engine.reporting.failed_tickers import (
            collect_failed_tickers as _collect_failed,
        )
        from investment_engine.research.market_data import (
            _FETCH_FAILED as _fetch_failed_set,
        )
        failed_tickers = _collect_failed(
            yahoo_by_display if "yahoo_by_display" in dir() else {},
            standalone=standalone if "standalone" in dir() else [],
            fetch_failed=set(_fetch_failed_set),
        )
    except Exception:
        failed_tickers = []

    # Research coverage universe (Phase 2): single scope structure for the run.
    # Holdings + watchlist + themes + benchmarks + discovery candidates.
    # Holdings must reflect the FULL broker portfolio (PIE constituents +
    # standalone + auto-discovered), not just the configured asset list.
    try:
        from investment_engine.research.universe import (
            build_research_universe as _build_universe,
        )
        _mr_symbol = ""
        try:
            _mr_symbol = str(getattr(getattr(settings, "market_regime", None), "symbol", "") or "")
        except Exception:
            pass
        _holdings_source = all_active_assets if "all_active_assets" in dir() else assets
        _research_universe = _build_universe(
            _holdings_source,
            getattr(settings, "watchlist", None),
            getattr(settings, "preferred_themes", None),
            [_mr_symbol or "EXI2.DE"],
            [str(i.get("ticker", "")) for i in (ideas if isinstance(ideas, list) else []) if isinstance(i, dict)],
        )
    except Exception:
        _research_universe = {"holdings": [], "watchlist": [], "themes": [],
                              "benchmarks": [], "discovery": []}

    # Phase 9: run budget + previous-run linkage (never break the run).
    _run_duration_s = round(__import__("time").time() - start_time, 1) if "start_time" in dir() else 0.0
    try:
        _run_budget_s = float(_lv.RUN_BUDGET.seconds or 900.0)
    except Exception:
        _run_budget_s = 900.0
    if _run_duration_s > _run_budget_s:
        logger.warning("Run budget exceeded: %.1fs > %.0fs budget", _run_duration_s, _run_budget_s)
    previous_run = None
    try:
        from investment_engine.reporting.run_history import (
            load_previous_run as _load_prev,
        )
        _arch_dir = str((settings_dict or {}).get("archive_folder", str(ROOT / "reports" / "archive")) or str(ROOT / "reports" / "archive"))
        previous_run = _load_prev(_arch_dir, str((portfolio_context or {}).get("run_id", "") or ""))
    except Exception as exc:
        logger.debug("Previous-run linkage skipped: %s", type(exc).__name__)

    return {
        "markdown": brief_md,
        "brief_markdown": brief_md,
        "snapshot_markdown": snapshot_md,
        "deep_dive_markdown": deep_dive_md,
        "run_id": str((portfolio_context or {}).get("run_id", "") or ""),
        "brief_generated_at": report_dt.isoformat(),
        # --- AI mode provenance ---
        "requested_mode": str((portfolio_context or {}).get("requested_mode", "unknown")),
        "effective_mode": _exec_mode if "_exec_mode" in dir() else "unknown",
        "environment_id": str((portfolio_context or {}).get("environment_id", "unknown")),
        "local_ai_attempts": _LOCAL_AI_TRACKER["attempts"],
        "local_ai_requests_sent": _LOCAL_AI_TRACKER["requests_sent"],
        "local_ai_attempts_blocked": _LOCAL_AI_TRACKER["blocked"],
        "brief_metadata": {
            "generated_at": report_dt.isoformat(),
            "timezone": "Europe/Bratislava",
            "recon_status": reconciliation_diagnostic.get("status"),
            "stance": next((l for l in brief_md.splitlines() if l.startswith("- Portfolio stance:")), ""),
            "monitoring_items": len(monitoring_items),
            "earnings_7d": len(earnings_7d.get("in_window", [])),
            "news_items": len(decision_news),
            "watchlist": len(ideas),
        },
        "snapshot_metadata": {
            "generated_at": report_dt.isoformat(),
            "timezone": "Europe/Bratislava",
            "recon_status": reconciliation_diagnostic.get("status"),
            "positions": len(portfolio_rows or []),
        },
        "context_file": str(context_file),
        "tech_tickers": tech + other,
        "renewable_tickers": renewable,
        "crypto": crypto,
        "passive_pies": [{"name": pie["name"], "tickers": [holding["slice"] for holding in pie["holdings"]]} for pie in passive_pies],
        "recent_news": news_by_symbol,
        "trump_watch": {},
        "earnings_dates": earnings,
        "settings": sanitized_settings(settings),
        "report_mode": "decision_brief_and_snapshot",
        "market_regime": regime_result.to_dict() if regime_result else None,
        "providers_per_stage": {k: dict(v) for k, v in _STAGE_ATTRIBUTION.items()},
        "skill_outputs": skill_outputs,
        "skill_versions": skill_versions,
        "order_plans": order_plans,
        "investment_policy": {"status": policy_state.get("status", "NOT SET"),
                              "version": policy_state.get("version", ""),
                              "problems": policy_state.get("problems", []),
                              "profile": policy_state.get("profile", {})},
        "universe": {
            "enabled": True,
            "counts": dict(universe_info or {}),
        },
        "playwright": dict(playwright_stats or {}),
        "tvnews": dict(tvnews_stats or {}),
        "research_corpus": {
            "run_id": _corpus_run_id,
            "counts": (corpus_info or {}).get("counts", {}),
            "path_md": (corpus_info or {}).get("path_md"),
            "path_json": (corpus_info or {}).get("path_json"),
            "path_rejected": (corpus_info or {}).get("path_rejected"),
        },
        "research_universe": _research_universe,
        "previous_run": previous_run,
        "source_status": list(source_ledger) if "source_ledger" in dir() else [],
        "source_status_summary": _srcstat.summarize(source_ledger) if "source_ledger" in dir() else {},
        "research_note": research_note,
        "execution_mode_lines": execution_mode_lines,
        "api_execution_mode": {"public": "API_ONLY", "locals": "LOCALS"}.get(_exec_mode, "STANDARD"),
        "disabled_providers": disabled_providers,
        "ai_recommendations": ai_recs,
        "t212_data": sanitized_t212_data(t212_data),
        "reconciliation": reconciliation_diagnostic,
        "account_performance": account_performance,
        "t212_statement_reconciliation": t212_statement_reconciliation,
        "cash_flow_ledger_metadata": cashflow_metadata,
        # Human-brief contract: keys consumed by generate_human_brief()
        # via portfolio_ai_assistant.py wrapper (all computed above).
        "portfolio_rows": portfolio_rows or [],
        "issuer_exposure": issuer_exposure or [],
        "schedule_profile": {
            "timezone": "Europe/Bratislava",
            "full_run": "09:00",
            "evening_run": "21:00",
            "us_open_event_driven": True,
        },
        "monitoring_items": monitoring_items or [],
        "regime_result": regime_result,
        "decision_news": decision_news or [],
        # WP3: filter provenance — how many raw items were rejected and why.
        "decision_news_selected": len(decision_news or []),
        "news_filter_stats": dict(_news_filter_stats) if "_news_filter_stats" in dir() else {},
        "catalyst_radar": catalyst_radar or [],
        "earnings_7d": earnings_7d or {},
        "earnings_provenance": dict(earnings_provenance) if "earnings_provenance" in dir() else {},
        "dividends_12m": dividends_12m or {},
        "analyst_consensus": analyst_consensus_bundle(
            analyst_consensus_map if "analyst_consensus_map" in dir() else {}),
        "energy_snapshot": dict(energy_snapshot) if "energy_snapshot" in dir() else {},
        # Social platforms without a permitted access path stay explicitly
        # unavailable — never fabricated coverage.
        "unavailable_sources": [
            "X (no permitted access)",
            "StockTwits (no permitted access)",
            "Facebook/Instagram (no permitted access)",
            "private forums and groups (no permitted access)",
        ],
        "previous_run": previous_run if "previous_run" in dir() else None,
        "run_budget": build_run_budget(
            start_time if "start_time" in dir() else None,
            report_dt,
            _run_duration_s if "_run_duration_s" in dir() else 0.0,
            _run_budget_s if "_run_budget_s" in dir() else 900.0,
        ),
        "ideas": ideas or [],
        "portfolio_names": portfolio_names or {},
        "failed_tickers": failed_tickers,
        # Run status inputs for wrapper finalization
        "_run_status_inputs": {
            "degraded_stages": dict(_lv.degraded_stages()),
            "broker_ok": t212_view.status(t212_data) == "ok",
            "deadline_exceeded": _lv.RUN_BUDGET.exceeded(),
            "run_id": run_id,
            "budget_remaining_s": _lv.RUN_BUDGET.remaining_seconds(),
        },
    }

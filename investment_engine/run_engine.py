"""Portfolio run orchestrator (moved out of main.py).

This module owns run_engine. Helper functions remain in main.py and are
imported here; main.py re-exports run_engine as a thin facade so existing
imports keep working.
"""

from __future__ import annotations

import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from investment_engine import liveness as _lv
from investment_engine.config.settings import EngineSettings
from investment_engine.portfolio import t212_view
from investment_engine.providers.factory import ProviderFactory
from investment_engine.reporting.regime_report import RegimeReportGenerator
from investment_engine.research.market_regime import EXI2RegimeAnalyzer
from investment_engine.run_state import STAGE_ATTRIBUTION as _STAGE_ATTRIBUTION
from investment_engine.schemas.context import AssetInput, RunResult

logger = logging.getLogger(__name__)

from investment_engine.fetching import build_regime_context
from investment_engine.main import SUMMARY_GUARDRAILS
from investment_engine.providers.generation import (
    annotate_skill_output,
    generate_with_fallback,
    note_deterministic_skill,
)
from investment_engine.providers.recommendations import build_ai_recommendations
from investment_engine.reporting.formatters import (
    apply_fail_guards,
    ensure_consistent_summary,
    format_earnings_radar,
)
from investment_engine.reporting.portfolio_view import (
    apply_fail_watchlist_sweep,
    build_portfolio_names,
    portfolio_tickers_for_priority,
)
from investment_engine.reporting.sections import (
    build_priority_actions_table,
    headlines_block,
    strip_priority_actions_from_summary,
)


def apply_user_cash_floor(regime_result, cash_floor_pct):
    """Override the regime cash target with an explicit user cash floor.

    ``None`` keeps the regime recommendation. ``0.0`` disables the cash target
    (user explicitly chose no mandatory cash reserve). Invalid values are
    ignored so a malformed custom rule never blocks the run.
    """
    if regime_result is None or cash_floor_pct is None:
        return regime_result
    try:
        floor = float(cash_floor_pct)
    except (TypeError, ValueError):
        logger.warning("Invalid cash_floor_pct %r; keeping regime cash target", cash_floor_pct)
        return regime_result
    implications = getattr(regime_result, "implications", None)
    if not isinstance(implications, dict):
        return regime_result
    previous = implications.get("cash_target_pct")
    implications["cash_target_pct"] = floor
    logger.info("Cash target overridden by custom_rules: %s%% -> %s%% (explicit user floor)",
                previous, floor)
    return regime_result


def apply_user_cash_floor_to_policy(policy_state: dict, cash_floor_pct):
    """Apply the explicit user cash floor to the loaded investment policy.

    The policy file's ``cash.mandatory_floor_pct`` controls the order-plan
    reserve. Without this override, custom_rules' ``cash_floor_pct: 0`` is
    ignored and every BUY is blocked by the file's reserve.
    """
    if cash_floor_pct is None or not isinstance(policy_state, dict):
        return policy_state
    if str(policy_state.get("status", "")).upper() != "OK":
        return policy_state
    try:
        floor = float(cash_floor_pct)
    except (TypeError, ValueError):
        logger.warning("Invalid cash_floor_pct %r; keeping policy cash floor", cash_floor_pct)
        return policy_state
    policy = policy_state.get("policy")
    if not isinstance(policy, dict):
        return policy_state
    cash_cfg = policy.get("cash")
    if not isinstance(cash_cfg, dict):
        cash_cfg = {}
        policy["cash"] = cash_cfg
    previous = cash_cfg.get("mandatory_floor_pct")
    cash_cfg["mandatory_floor_pct"] = floor
    logger.info("Policy cash floor overridden by custom_rules: %s%% -> %s%%",
                previous, floor)
    return policy_state


def run_engine(assets: list[AssetInput], portfolio_context: dict[str, Any] | None = None, settings: EngineSettings | None = None) -> RunResult:
    """Create a compact, live-data report with short model calls per active category."""
    from investment_engine.run_phases.setup import build_universe_plan, prepare_run

    run = prepare_run(settings, portfolio_context)
    settings = run.settings
    run_id = run.run_id
    reports_dir = run.reports_dir
    language = run.language
    portfolio_context = run.portfolio_context

    universe = build_universe_plan(assets)
    tech_pies = universe.tech_pies
    renewable_pies = universe.renewable_pies
    passive_pies = universe.passive_pies
    tech = universe.tech
    renewable = universe.renewable
    other = universe.other
    crypto = universe.crypto
    all_active_assets = universe.all_active_assets
    known_clean = universe.known_clean
    known_names_base = universe.known_names_base

    # --- FETCH DATA IN PARALLEL ---
    start_time = time.time()

    # 1. Trading212 (with timeout protection) + canonical reconciliation
    from investment_engine.run_phases.broker import fetch_broker_phase

    broker = fetch_broker_phase(
        settings=settings,
        run_id=run_id,
        reports_dir=reports_dir,
        portfolio_context=portfolio_context,
        assets=assets,
        all_active_assets=all_active_assets,
        known_clean=known_clean,
    )
    settings_dict = broker.settings_dict
    t212_data = broker.t212_data
    _snap = broker.snapshot
    _recon_result = broker.recon_result
    _dpos = broker.positions
    _recon = broker.recon

    # 2. News (parallel, top 10 holdings) + source ledger
    from investment_engine.run_phases.news import fetch_news_phase

    news = fetch_news_phase(
        settings_dict=settings_dict,
        all_active_assets=all_active_assets,
        portfolio_context=portfolio_context,
    )
    news_by_symbol = news.news_by_symbol
    trump_tracking = news.trump_tracking
    commodity_news = news.commodity_news
    analyst_news = news.analyst_news
    news_context_path = news.news_context_path
    source_ledger = news.source_ledger

    # 3. Earnings (parallel fast path, then calendar fallback)
    from investment_engine.run_phases.earnings import fetch_earnings_phase

    earnings_phase = fetch_earnings_phase(
        settings=settings,
        assets=assets,
        all_active_assets=all_active_assets,
    )
    earnings = earnings_phase.earnings
    _dated_before_l2 = earnings_phase.dated_before_l2
    _calendar_sourced = earnings_phase.calendar_sourced
    playwright_earnings = earnings_phase.playwright_earnings
    # NOTE: dividends block lives after the mapping layer is populated
    # (yahoo_by_display/standalone); an earlier placement raised
    # UnboundLocalError (run 066ac8be) and skipped silently.

    # 4. Market Regime
    regime_result = None
    regime_context = ""
    if settings.market_regime.enabled:
        try:
            regime_analyzer = EXI2RegimeAnalyzer(
                symbol=settings.market_regime.symbol,
                cache_ttl_seconds=settings.market_regime.cache_ttl_seconds,
            )
            regime_result = regime_analyzer.analyze()
            regime_result = apply_user_cash_floor(
                regime_result, getattr(settings, "cash_floor_pct", None)
            )
            regime_context = build_regime_context(regime_result)
        except Exception as e:
            regime_context = f"Regime analysis failed: {e}"

    # 5. AI Recommendations
    ai_recs = {}
    t212_ok = t212_view.status(t212_data) == "ok"
    # Allow AI recommendations even with reconciliation failure, just suppress account-level P&L
    if regime_result and t212_ok:
        provider = ProviderFactory.create(settings)
        ai_recs = build_ai_recommendations(regime_result, t212_data, all_active_assets, provider, settings_dict, language)

        # Notify about BUY/SELL signals from AI recommendations
        try:
            from investment_engine.notifications import notify_urgent
            ai_recs_data = ai_recs.get("ai_recs", {}) if isinstance(ai_recs, dict) else {}
            if isinstance(ai_recs_data, dict):
                trades = ai_recs_data.get("trades", [])
                portfolio_actions = ai_recs_data.get("portfolio_actions", [])
                for action in trades + portfolio_actions:
                    if isinstance(action, dict) and action.get("action") in ("BUY", "SELL"):
                        symbol = action.get("asset", "Unknown")
                        reason = action.get("reason", "No reason provided")
                        notify_urgent(
                            f"{action} {symbol}",
                            f"{action} {symbol}: {reason}"
                        )
        except Exception as exc:
            logger.debug("Notification failed: %s", type(exc).__name__)

    # 6. Regime + context report rendering happens at the end (needs all AI
    # sections, technicals, news and earnings ready). Placeholders for now.
    context_file: Path | None = None

    # 7. LLM Decisions for active positions
    provider = ProviderFactory.create(settings)
    decision_sections: list[str] = []  # curated, rendered in the human report
    verbose_sections: list[str] = []  # full per-ticker analysis → AI context file only
    # ONE canonical signal mapping, built once and shared by every section
    # (T212 Portfolio, Priority Actions, AI Recommendations, PIE evaluation,
    # KPI text). Keyed by DISPLAY symbol; internal IDs alias to the same entry.
    try:
        from investment_engine.portfolio.symbols import to_display_symbol as _td_canon
        from investment_engine.reporting.regime_report import (
            build_canonical_signals as _build_canon,
        )
        from investment_engine.reporting.regime_report import (
            ensure_canonical_defaults as _ensure_defaults,
        )
        canonical_map: dict = _build_canon(ai_recs, known_clean,
                                             settings_dict.get("hold_thesis", {}))
        # Pre-fill HOLD defaults for every authoritative holding so the PIE
        # prompt and every downstream section share one complete mapping.
        _auth = t212_view.account_summary(t212_data).get("all_positions") or (t212_data or {}).get("all_positions") or []
        _ensure_defaults(canonical_map, [_td_canon(str((p or {}).get("symbol", "")), known_clean) for p in _auth if isinstance(p, dict)])
    except Exception:
        canonical_map = {}
    canonical = {k: (v.get("signal") if isinstance(v, dict) else v) for k, v in (canonical_map or {}).items()}
    # Deduplicate display keys for the prompt note.
    _seen_disp: dict = {}
    for _v in (canonical_map or {}).values():
        if isinstance(_v, dict) and _v.get("display") and _v["display"] not in _seen_disp:
            _seen_disp[_v["display"]] = _v.get("signal")
    canonical_display_note = (
        ", ".join(f"{_d}={_s}" for _d, _s in sorted(_seen_disp.items())) or "none yet"
    )
    canonical_note = (
        f"\nCANONICAL DECISIONS (final, from structured recommendations – do NOT contradict, do NOT repeat rationale, one line each): {canonical}"
        if canonical else ""
    )

    # Prepare news for LLM

    # Per-scope LLM decision sections (crypto, tech, renewables)
    from investment_engine.run_phases.decisions import (
        DecisionInputs,
        build_decision_sections,
    )

    decisions = build_decision_sections(
        DecisionInputs(
            crypto=crypto,
            tech=tech,
            other=other,
            renewable=renewable,
            news_by_symbol=news_by_symbol,
            earnings=earnings,
            language=language,
            regime_context=regime_context,
            provider=provider,
            settings=settings,
            decision_sections=decision_sections,
            verbose_sections=verbose_sections,
        )
    )
    decision_sections = decisions.decision_sections
    verbose_sections = decisions.verbose_sections

    # 7b/7c. Enrichment: standalone holdings, PIE deep dive, dividends,
    # analyst consensus, energy snapshot, and the research corpus.
    from investment_engine.run_phases.enrichment import (
        EnrichmentInputs,
        build_enrichment,
    )

    enrichment = build_enrichment(
        EnrichmentInputs(
            assets=assets,
            tech_pies=tech_pies,
            renewable_pies=renewable_pies,
            passive_pies=passive_pies,
            all_active_assets=all_active_assets,
            t212_data=t212_data,
            snapshot=_snap,
            settings=settings,
            settings_dict=settings_dict,
            provider=provider,
            run_id=run_id,
            reports_dir=reports_dir,
            language=language,
            portfolio_context=portfolio_context,
            canonical_map=canonical_map,
            canonical_display_note=canonical_display_note,
            canonical_note=canonical_note,
            regime_context=regime_context,
            decision_sections=decision_sections,
            verbose_sections=verbose_sections,
            source_ledger=source_ledger,
            news_by_symbol=news_by_symbol,
            playwright_earnings=playwright_earnings,
        )
    )
    standalone = enrichment.standalone
    pie_blocks = enrichment.pie_blocks
    extra_tech = enrichment.extra_tech
    extra_news = enrichment.extra_news
    extra_earn = enrichment.extra_earn
    playwright_stats = enrichment.playwright_stats
    tvnews_stats = enrichment.tvnews_stats
    corpus_info = enrichment.corpus_info
    _corpus_run_id = enrichment.corpus_run_id
    universe_info = enrichment.universe_info
    yahoo_by_display = enrichment.yahoo_by_display
    known_clean = enrichment.known_clean
    aliases = enrichment.aliases
    analyst_consensus_map = enrichment.analyst_consensus_map
    dividends_12m = enrichment.dividends_12m
    energy_snapshot = enrichment.energy_snapshot
    unified_technicals_seed = enrichment.unified_technicals_seed
    decision_sections = enrichment.decision_sections
    verbose_sections = enrichment.verbose_sections
    source_ledger = enrichment.source_ledger

    # Candidate section. The discovery prompt MUST carry headlines: without
    # them the model can only return the "None supported" fallback (seen live
    # 2026-09-28: 86 prompt tokens, content_len=59). extra_news is keyed by
    # display symbol; cap the block so the prompt stays bounded.
    try:
        _disco_block = headlines_block(dict(list((extra_news or {}).items())[:40]))
    except Exception:
        _disco_block = "None"
    discovery_prompt = f"""Write a Markdown section called '## Potential New Ideas' in {language}.
Using only these recent headlines, name at most three ticker candidates as WATCH, never BUY. Explain in one short line why each needs further verification. If no ticker is clearly identifiable and supported, write 'None supported by current evidence.'
RECENT HEADLINES:
{_disco_block}"""
    candidate_section = generate_with_fallback(provider, discovery_prompt, settings, tokens=1024, stage="discovery")

    # Summary (LLM) + Priority Actions (deterministic, unified).
    # Priority Actions are NEVER taken verbatim from the LLM: they are built
    # from the final unified T212 Portfolio rows so every ticker exists in
    # the portfolio table and every signal matches the normalized signal.
    # The LLM only writes the short ## Summary bullets.
    allowed_for_priority = portfolio_tickers_for_priority(t212_data, known_clean)
    summary_prompt = f"""Write ONLY the '## Summary' Markdown section in {language}, based strictly on the supplied decisions.
{SUMMARY_GUARDRAILS}
At most 5 concise bullets: portfolio state, EXI2 regime, top risks and opportunities.
Do NOT write a Priority Actions table (it is generated deterministically).
Only mention these owned tickers when naming actions: {', '.join(sorted(allowed_for_priority)) or 'none'}.
Respect the canonical decisions below – same ticker keeps the same action everywhere.
Do not invent price, news or analyst facts. This is research, not financial advice.
CANONICAL: {canonical if canonical else 'none yet'}.

DECISIONS:
{chr(10).join(decision_sections + verbose_sections + [candidate_section])}"""
    summary_llm = generate_with_fallback(provider, summary_prompt, settings, tokens=1200, stage="summary")
    summary_section = strip_priority_actions_from_summary(summary_llm)

    # Unified enrichment maps for portfolio table / KPIs / radar.
    # Names: display symbol -> company name (pie slices + config assets +
    # broker names + overrides). known_clean feeds display stripping.
    portfolio_names = build_portfolio_names(all_active_assets, pie_blocks, t212_data, known_names_base)
    # ISIN identity map for unified rows (same identity as broker_first):
    # KNOWN_ISINS first, then per-position ISIN fields when the broker supplies them.
    try:
        from investment_engine.portfolio.broker_first import KNOWN_ISINS as _KNOWN_ISINS
        _isin_map: dict[str, str] = dict(_KNOWN_ISINS)
    except Exception:
        _isin_map = {}
    try:
        _td_positions = ((t212_data or {}).get("all_positions") or []) + ((t212_data or {}).get("positions") or [])
        for _p in _td_positions:
            if isinstance(_p, dict) and _p.get("isin") and _p.get("symbol"):
                _isin_map.setdefault(str(_p["symbol"]).strip().upper(), str(_p["isin"]).strip().upper())
    except Exception:
        pass
    try:
        from investment_engine.reporting.regime_report import (
            build_unified_portfolio_rows as _build_rows,
        )
        portfolio_rows = _build_rows(
            t212_data, ai_recs, unified_technicals_seed, portfolio_names,
            known_clean, canonical_map, yahoo_by_display,
            isin_map=_isin_map,
        )
    except Exception:
        portfolio_rows = []
    # Phase 5: issuer-level exposure aggregation (same ISIN -> one issuer).
    try:
        from investment_engine.portfolio.exposure import (
            aggregate_issuer_exposure as _agg_issuer,
        )
        issuer_exposure = _agg_issuer(portfolio_rows)
    except Exception:
        issuer_exposure = []
    # Narrative must match the canonical rows: reject unowned actions/trades.
    summary_section = ensure_consistent_summary(
        summary_section, portfolio_rows, regime_result, t212_data,
    )
    unified_technicals = dict(extra_tech or {})

    # Record signals for later backtesting (best-effort, never blocks the run).
    try:
        from investment_engine.signals import record_portfolio_signals as _record_signals
        _record_signals(run_id, portfolio_rows)
    except Exception as _sig_exc:
        logger.debug("Signal recording skipped: %s", type(_sig_exc).__name__)

    # Permanent AI memory: record actionable signals with their rationale.
    try:
        from investment_engine.history import record_decision as _record_decision
        for _row in portfolio_rows:
            _sig = str(_row.get("signal", "")).upper()
            if _sig in ("BUY", "SELL"):
                _record_decision(
                    _row.get("display_symbol") or _row.get("ticker") or "?",
                    _sig,
                    str(_row.get("notes") or _row.get("_trigger") or "")[:500],
                    confidence=float(_row.get("confidence", 0) or 0),
                    source="portfolio_ai",
                    run_id=run_id,
                    mode=str((run.portfolio_context or {}).get("mode") or "live"),
                )
    except Exception as _hist_exc:
        logger.debug("History recording skipped: %s", type(_hist_exc).__name__)

    # Earnings radar keyed by DISPLAY symbol with inline certainty tags.
    # Config-asset earnings remapped to display; T212 enrichment earnings
    # mapped via the Yahoo layer; unsupported instruments stay 'unavailable'.
    import re as _re

    from investment_engine.research.market_data import classify_earnings_status

    def _add_radar(disp: str, d, status: str | None = None, source: str | None = None) -> None:
        if isinstance(d, str) and _re.match(r"^\d{4}-\d{2}-\d{2}", d):
            st = status or classify_earnings_status(str(disp), d[:10])
            prev = earnings_status.get(str(disp))
            # A confirmed date always wins over an estimated one.
            if prev is None or (prev[1] == "estimated" and st == "confirmed"):
                earnings_status[str(disp)] = (d[:10], st)
                from investment_engine.research.market_data import (
                    earnings_source_for as _src_for,
                )
                _cal = _calendar_sourced if "_calendar_sourced" in dir() else set()
                earnings_provenance[str(disp)] = {
                    "source": source or _src_for(str(disp), _cal),
                    "last_verified": datetime.now(timezone.utc).date().isoformat(),
                }

    earnings_status: dict[str, tuple[str, str]] = {}
    earnings_provenance: dict[str, dict[str, str]] = {}
    unavailable_earnings: list[str] = []
    try:
        from investment_engine.portfolio.symbols import to_display_symbol as _td
        for disp, d in (earnings or {}).items():
            _d = _td(str(disp), known_clean)
            _src = ("playwright-calendar"
                    if _d in (_calendar_sourced if "_calendar_sourced" in dir() else set())
                    else "yahoo")
            _add_radar(_d, d, source=_src)
        for p in standalone:
            disp = p.get("display") or _td(p.get("t212", ""), known_clean)
            val = extra_earn.get(disp, extra_earn.get(p.get("yahoo", ""), ""))
            if isinstance(val, str) and _re.match(r"^\d{4}-\d{2}-\d{2}", val):
                _add_radar(disp, val, source="yfinance")
            elif val in ("unavailable", "no_data", ""):
                if disp not in unavailable_earnings:
                    unavailable_earnings.append(disp)
        for b in pie_blocks:
            for s in b.get("sample", []) or []:
                disp = s.get("display") or _td(s.get("slice", ""), known_clean)
                val = extra_earn.get(disp, extra_earn.get(s.get("slice", ""), ""))
                if isinstance(val, str) and _re.match(r"^\d{4}-\d{2}-\d{2}", val):
                    _add_radar(disp, val, source="yfinance")
                elif val in ("unavailable", "no_data", ""):
                    if disp not in unavailable_earnings:
                        unavailable_earnings.append(disp)
    except Exception:
        pass
    format_earnings_radar(earnings_status, portfolio_names, unavailable_earnings)
    # Phase 6 skills run after the canonical snapshot (built before news fetch).
    skill_outputs: dict[str, dict] = {}
    skill_versions: dict[str, str] = {}
    # Phase 6 skills (first four): structured, evidence-gated outputs stored in
    # the result + manifest. Deterministic fallbacks keep offline runs green;
    # legacy prose sections above are unchanged (prompt cutover is P1).
    try:
        from investment_engine.skills import registry as _skills
        _corpus_items = (corpus_info or {}).get("items", []) or []
        _corpus_decision = (corpus_info or {}).get("decision_items", []) or []
        _cash_view = t212_view.cash(t212_data)

        # Phase 2: annotate each skill output with execution_type and fallback_reason.
        # Skills already set these fields themselves (with execution_reason);
        # only fill gaps so validated skill provenance is never overwritten.
        skill_outputs["risk"] = annotate_skill_output(
            _skills.run_skill(
                "portfolio_risk_manager",
                {"portfolio_rows": portfolio_rows,
                 "reconciliation": _recon if isinstance(_recon, dict) else {"status": "UNKNOWN"},
                 "regime": getattr(regime_result, "regime", "UNKNOWN") if regime_result else "UNKNOWN",
                 "cash": _cash_view},
                provider, settings, language),
            "portfolio_risk_manager")
        skill_outputs["news_events"] = annotate_skill_output(
            _skills.run_skill(
                "news_event_analyst",
                {"decision_items": _corpus_decision, "portfolio_rows": portfolio_rows},
                provider, settings, language),
            "news_event_analyst")
        try:
            from investment_engine.providers import attribution as _attr_sk
            _sk_record = _attr_sk.new_stage_record("news_events")
            _news_out = skill_outputs.get("news_events", {}) or {}
            _news_inv = (_news_out.get("data", {}) or {}).get("llm_invocation", {}) or {}
            if bool((_news_out.get("data", {}) or {}).get("enriched")):
                _STAGE_ATTRIBUTION["news_events"] = _attr_sk.apply_chain_hint(_sk_record, provider)
            elif bool(_news_inv.get("invoked")) and bool(_news_inv.get("call_succeeded")):
                # LLM call succeeded but output failed validation: record the
                # actual provider/model AND the validation failure (never
                # mislabelled as deterministic_by_design).
                _STAGE_ATTRIBUTION["news_events"] = _attr_sk.apply_chain_hint(_sk_record, provider)
                _STAGE_ATTRIBUTION["news_events"]["output_validation"] = str(_news_inv.get("validation", "failed"))
                _STAGE_ATTRIBUTION["news_events"]["fallback_reason"] = str(_news_out.get("fallback_reason", ""))
                _STAGE_ATTRIBUTION["news_events"]["execution_reason"] = "FALLBACK_INVALID_OUTPUT"
            elif bool(_news_inv.get("invoked")):
                # Provider call itself failed: record the attempt honestly.
                _STAGE_ATTRIBUTION["news_events"] = _attr_sk.note_deterministic(_sk_record, "skills")
                _STAGE_ATTRIBUTION["news_events"]["execution_reason"] = "FALLBACK_PROVIDER_FAILURE"
                _STAGE_ATTRIBUTION["news_events"]["fallback_reason"] = str(_news_out.get("fallback_reason", ""))
            else:
                _STAGE_ATTRIBUTION["news_events"] = _attr_sk.note_deterministic(_sk_record, "deterministic_by_design")
                _STAGE_ATTRIBUTION["news_events"]["execution_reason"] = "DETERMINISTIC_BY_DESIGN"
        except Exception:
            pass
        skill_outputs["equity_notes"] = annotate_skill_output(
            _skills.run_skill(
                "equity_research_analyst",
                {"portfolio_rows": portfolio_rows, "technicals": unified_technicals,
                 "earnings_status": earnings_status, "corpus_items": _corpus_items},
                provider, settings, language),
            "equity_research_analyst")
        # --- TradingAgents-style analyst team (technical + sentiment) ---
        skill_outputs["technical"] = annotate_skill_output(
            _skills.run_skill(
                "technical_analyst",
                {"portfolio_rows": portfolio_rows, "technicals": unified_technicals},
                provider, settings, language),
            "technical_analyst")
        skill_outputs["sentiment"] = annotate_skill_output(
            _skills.run_skill(
                "sentiment_analyst",
                {"decision_items": _corpus_decision, "social_items": _corpus_items},
                provider, settings, language),
            "sentiment_analyst")
        # --- Bull vs bear researcher debate over the analyst outputs ---
        skill_outputs["researchers"] = annotate_skill_output(
            _skills.run_skill(
                "researcher_debate",
                {"analyst_outputs": {
                    "technical_analyst": skill_outputs["technical"],
                    "sentiment_analyst": skill_outputs["sentiment"],
                    "news_event_analyst": skill_outputs["news_events"],
                    "equity_research_analyst": skill_outputs["equity_notes"],
                }},
                provider, settings, language),
            "researcher_debate")
        # --- Trader agent: concrete advisory proposal from the debate ---
        _risk_budget = 0.0
        try:
            _eq_now = float(t212_view.account_summary(t212_data).get("total_equity", 0) or 0)
            _risk_budget = _eq_now * 2.0 / 100.0  # 2% per trade default
        except Exception:
            _risk_budget = 0.0
        skill_outputs["trader"] = annotate_skill_output(
            _skills.run_skill(
                "trader_agent",
                {"debates": (skill_outputs["researchers"].get("data", {}) or {}).get("debates", []),
                 "technicals": unified_technicals,
                 "risk_budget": _risk_budget},
                provider, settings, language),
            "trader_agent")
        # --- Sector-style research watchlist with anti-chasing stance ---
        _sector_map: dict[str, str] = {}
        try:
            from investment_engine.portfolio.symbols import to_display_symbol as _td_sector
            for _asset in assets or []:
                _disp = _td_sector(str((_asset or {}).get("broker_symbol", "")), known_clean)
                _grp = str((_asset or {}).get("group", "") or "")
                if _disp and _grp:
                    _sector_map[_disp] = _grp
        except Exception:
            _sector_map = {}
        skill_outputs["watchlist"] = annotate_skill_output(
            _skills.run_skill(
                "watchlist_stance",
                {"watchlist": list(settings_dict.get("watchlist", []) or []),
                 "portfolio_rows": portfolio_rows,
                 "technicals": unified_technicals,
                 "news_events": (skill_outputs["news_events"].get("data", {}) or {}).get("events", []) or [],
                 "earnings_status": earnings_status,
                 "sectors": _sector_map,
                 "event_calendar": []},
                provider, settings, language),
            "watchlist_stance")
        skill_outputs["committee"] = annotate_skill_output(
            _skills.run_skill(
                "investment_committee",
                {"risk_output": skill_outputs["risk"], "news_output": skill_outputs["news_events"],
                 "equity_output": skill_outputs["equity_notes"], "canonical_map": canonical_map,
                 "portfolio_rows": portfolio_rows,
                 "researcher_output": skill_outputs["researchers"],
                 "trader_output": skill_outputs["trader"],
                 "watchlist_output": skill_outputs["watchlist"],
                 "reconciliation": _recon if isinstance(_recon, dict) else {"status": "UNKNOWN"}},
                provider, settings, language),
            "investment_committee")
        skill_versions = dict(_skills.SKILL_VERSIONS)
        # Record deterministic skill executions with human-readable reasons
        note_deterministic_skill("risk", "deterministic_by_design")
        note_deterministic_skill("equity_notes", "deterministic_by_design")
        note_deterministic_skill("technical", "deterministic_by_design")
        note_deterministic_skill("sentiment", "deterministic_by_design")
        note_deterministic_skill("researchers", "deterministic_by_design")
        note_deterministic_skill("trader", "deterministic_by_design")
        note_deterministic_skill("watchlist", "deterministic_by_design")
        note_deterministic_skill("committee", "deterministic_by_design")
        logger.info("Skills complete: %s",
                    {k: v.get("status", "?") for k, v in skill_outputs.items()})
    except Exception as exc:
        # Log sanitized traceback for debugging (no secrets)
        import traceback as _tb
        _tb_str = _tb.format_exc()
        # Sanitize: remove absolute paths, keep only function/line info
        import re as _re
        _tb_clean = _re.sub(r'File "[^"]*"', 'File "..."', _tb_str)
        logger.debug("Skills skipped: %s\n%s", type(exc).__name__, _tb_clean)
        skill_outputs = {}
    # Phase 7 advisory order plans (informational only, never executed).
    order_plans: dict = {"plans": [], "blocked": [], "policy_version": "",
                         "advisory_guard": "", "generated_at": ""}
    policy_state: dict = {"status": "NOT SET", "policy": {}, "version": "", "problems": []}
    try:
        from investment_engine.portfolio.symbols import to_display_symbol as _td_sleeve
        from investment_engine.risk import order_plan as _op
        from investment_engine.risk import policy as _pol
        from investment_engine.risk.order_plan import sleeve_for_group as _sleeve_of
        policy_state = _pol.load_policy()
        policy_state = apply_user_cash_floor_to_policy(
            policy_state, getattr(settings, "cash_floor_pct", None)
        )
        if policy_state.get("status") == "OK":
            _sleeves: dict[str, str] = {}
            for _a in assets or []:
                try:
                    _d = _td_sleeve(str((_a or {}).get("broker_symbol", "")), known_clean)
                    _sleeves[_d] = _sleeve_of((_a or {}).get("group"))
                except Exception:
                    continue
            _committee = (skill_outputs.get("committee", {}) or {}).get("data", {}) or {}
            _news_ev = (skill_outputs.get("news_events", {}) or {}).get("data", {}) or {}
            _cash = t212_view.cash(t212_data)
            _dsum2 = t212_view.account_summary(t212_data)
            order_plans = _op.build_plans(
                committee_decisions=_committee.get("decisions", []) or [],
                upstream_ok=bool(skill_outputs.get("committee")),
                portfolio_rows=portfolio_rows,
                recon_status=(_recon.get("status") if isinstance(_recon, dict) else "UNKNOWN"),
                free_cash=float(_cash.get("free", 0) or 0),
                total_equity=float(_dsum2.get("total_equity", 0) or 0),
                earnings_status=earnings_status,
                report_day=datetime.now(timezone.utc).date().isoformat(),
                news_events=_news_ev.get("events", []) or [],
                regime=getattr(regime_result, "regime", "UNKNOWN") if regime_result else "UNKNOWN",
                risk_posture=((skill_outputs.get("risk", {}) or {}).get("data", {}) or {}).get("posture", ""),
                policy=policy_state.get("policy", {}) or {},
                sleeves=_sleeves,
                hold_thesis=settings_dict.get("hold_thesis", {}))
            logger.info("Order plans: %d advisory, %d blocked (policy %s, profile %s)",
                        len(order_plans.get("plans", [])), len(order_plans.get("blocked", [])),
                        policy_state.get("version", ""),
                        (policy_state.get("profile") or {}).get("name", "custom"))
        else:
            logger.info("Order plans disabled: investment policy %s", policy_state.get("status"))
    except Exception as exc:
        logger.debug("Order plans skipped: %s", type(exc).__name__)

    # Checkpoint: analysis (skills + advisory)
    _skill_statuses = {k: v.get("status", "?") for k, v in (skill_outputs or {}).items()}
    _lv.write_checkpoint(reports_dir, run_id, "analysis", {
        "skill_statuses": _skill_statuses,
        "plans": len((order_plans or {}).get("plans", [])),
        "providers_per_stage": {k: dict(v) for k, v in _STAGE_ATTRIBUTION.items()},
    })
    # Trade safety: reconcile-gated BUY demotion applied once.
    try:
        from investment_engine.reporting.regime_report import (
            apply_trade_safety as _safety,
        )
        # Sanitized observability record.
        logger.info(
            "Reconciliation diagnostic | endpoints=/equity/account/cash,/equity/portfolio"
            " | total=%.2f positions=%.2f implied=%.2f reported=%.2f delta=%+.2f threshold=%.2f status=%s",
            _recon.get("total_equity", 0), _recon.get("positions_value", 0),
            _recon.get("implied_cash", 0), _recon.get("reported_cash", 0),
            _recon.get("cash_delta", 0), _recon.get("threshold", 0), _recon.get("status"),
        )
        if _recon_result is not None:
            ai_recs = apply_fail_guards(ai_recs, _recon["status"])
            _safety(canonical_map, portfolio_rows, unified_technicals, _recon["status"], earnings_status)
    except Exception as exc:
        logger.debug("Trade safety pass skipped: %s", exc)
    priority_table = build_priority_actions_table(
        portfolio_rows, earnings_status, unified_technicals, canonical_map=canonical_map
    )
    # Broker-first reconciliation diagnostic (CSV + Markdown).
    # Uses the same canonical snapshot built above; never recalculates.
    try:
        from investment_engine.portfolio.broker_first import (
            build_diagnostic_rows as _diag_rows,
        )
        from investment_engine.portfolio.broker_first import (
            write_diagnostic_csv as _write_dcsv,
        )
        from investment_engine.portfolio.broker_first import (
            write_diagnostic_markdown as _write_dmd,
        )
        if _snap is not None and _recon_result is not None:
            _drows, _dsummary = _diag_rows(_snap)
            _dsummary["reconciliation_status"] = _recon_result.reconciliation_status
            _dsummary["reconciliation_delta_eur"] = _recon_result.reconciliation_delta_eur
            _dsummary["expected_open_positions_value_eur"] = _recon_result.expected_open_positions_value_eur
            _dsummary["sum_deduplicated_broker_position_values_eur"] = \
                _recon_result.sum_deduplicated_broker_position_values_eur
            _dsummary["sum_raw_broker_position_values_eur"] = \
                _recon_result.sum_raw_broker_position_values_eur
            _dout = ROOT / "reports"
            _dout.mkdir(parents=True, exist_ok=True)
            _write_dcsv(_drows, _dout / "reconciliation_diagnostic.csv")
            _write_dmd(_drows, _dsummary, _dout / "reconciliation_diagnostic.md")
            logger.info("Reconciliation diagnostic written: %s rows=%d status=%s",
                        _dout, len(_drows), _dsummary.get("reconciliation_status"))
    except Exception as exc:
        logger.debug("Diagnostic report skipped: %s: %s", type(exc).__name__, exc)
    if summary_section and "## Summary" not in summary_section:
        summary_section = "## Summary\n" + summary_section.strip()
    summary_section = (summary_section or "## Summary").rstrip() + "\n\n" + priority_table
    # All report writers use the single canonical _recon status.
    _recon_status = _recon.get("status") if isinstance(_recon, dict) else "UNKNOWN"
    if str(_recon_status or "").upper() == "FAIL":
        summary_section, decision_sections = apply_fail_watchlist_sweep(
            summary_section, decision_sections, portfolio_rows, earnings_status, unified_technicals)

    # 6. Regime report parts (dashboard order: portfolio → AI recs → EXI2).
    # The unified T212 Portfolio table receives the same rows enrichment
    # (technicals + names + canonical signals) as the deterministic actions.
    if settings.market_regime.enabled and regime_result:
        report_gen = RegimeReportGenerator(
            include_charts=settings.market_regime.reporting.get("include_charts", False),
            canonical_recon=(_recon if isinstance(_recon, dict) else None),
        )
        report_gen.generate_parts(
            regime_result, t212_data, ai_recs, None, unified_technicals,
            portfolio_names, known_clean, canonical_map, yahoo_by_display,
        )

    # AI context file – full archive for machines: verbose per-ticker analysis,
    # all technicals and all headlines (human report stays curated).
    from investment_engine.run_phases.ai_context import (
        AIContextInputs,
        save_ai_context_phase,
    )

    ai_context = save_ai_context_phase(
        AIContextInputs(
            settings=settings,
            regime_result=regime_result,
            t212_data=t212_data,
            ai_recs=ai_recs,
            portfolio_rows=portfolio_rows,
            unified_technicals=unified_technicals,
            yahoo_by_display=yahoo_by_display,
            extra_tech=extra_tech,
            extra_news=extra_news,
            news_by_symbol=news_by_symbol,
            news_context_path=news_context_path,
            candidate_section=candidate_section,
            portfolio_context=portfolio_context,
            snapshot=_snap,
            recon_result=_recon_result,
        )
    )
    context_file = ai_context.context_file
    run_id = ai_context.run_id

    # --- Two-document reporting: decision brief (concise) + snapshot (full) ---
    from investment_engine.run_phases.reporting import ReportInputs, build_report

    _result = build_report(
        ReportInputs(
            settings=settings,
            settings_dict=settings_dict,
            run_id=run_id,
            start_time=start_time,
            portfolio_context=portfolio_context,
            assets=assets,
            all_active_assets=all_active_assets,
            tech=tech,
            renewable=renewable,
            other=other,
            crypto=crypto,
            passive_pies=passive_pies,
            known_clean=known_clean,
            aliases=aliases,
            t212_data=t212_data,
            recon=_recon,
            regime_result=regime_result,
            ai_recs=ai_recs,
            canonical_map=canonical_map,
            portfolio_rows=portfolio_rows,
            portfolio_names=portfolio_names,
            unified_technicals=unified_technicals,
            earnings=earnings,
            earnings_status=earnings_status,
            earnings_provenance=earnings_provenance,
            news_by_symbol=news_by_symbol,
            trump_tracking=trump_tracking,
            commodity_news=commodity_news,
            analyst_news=analyst_news,
            source_ledger=source_ledger,
            standalone=standalone,
            pie_blocks=pie_blocks,
            extra_tech=extra_tech,
            extra_news=extra_news,
            extra_earn=extra_earn,
            playwright_stats=playwright_stats,
            tvnews_stats=tvnews_stats,
            corpus_info=corpus_info,
            corpus_run_id=_corpus_run_id,
            universe_info=universe_info,
            yahoo_by_display=yahoo_by_display,
            analyst_consensus_map=analyst_consensus_map,
            dividends_12m=dividends_12m,
            energy_snapshot=energy_snapshot,
            issuer_exposure=issuer_exposure,
            order_plans=order_plans,
            policy_state=policy_state,
            skill_outputs=skill_outputs,
            skill_versions=skill_versions,
            candidate_section=candidate_section,
            summary_section=summary_section,
            context_file=context_file,
        )
    )
    # Generalised research watchlist section (sector | catalyst | confirmation | risk | stance).
    try:
        if skill_outputs.get("watchlist"):
            from investment_engine.skills import registry as _skills_render
            _wl_mod = _skills_render.get_skill("watchlist_stance")
            _result["research_watchlist_markdown"] = _wl_mod.render(skill_outputs["watchlist"])
    except Exception as _wl_exc:
        logger.debug("Watchlist render skipped: %s", type(_wl_exc).__name__)
    try:
        from investment_engine.reporting.excel_export import export_holdings_excel
        export_holdings_excel(
            t212_data,
            pie_blocks,
            portfolio_names,
            Path(ROOT / "reports" / "current" / "holdings.xlsx"),
        )
    except Exception as _xl_exc:
        logger.debug("Excel export skipped: %s", type(_xl_exc).__name__)
    return _result

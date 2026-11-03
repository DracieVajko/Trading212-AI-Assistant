"""AI context archive phase.

Writes the machine-readable context file (verbose analysis, technicals, and
headlines) and resolves the AI-context run id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investment_engine.config.settings import EngineSettings
from investment_engine.reporting.context_archive import save_ai_context
from investment_engine.research.earnings_fetch import tech_summary_line
from investment_engine.run_state import STAGE_ATTRIBUTION as _STAGE_ATTRIBUTION

logger = logging.getLogger(__name__)


@dataclass
class AIContextInputs:
    """Values the AI-context phase reads from the orchestrator."""

    settings: EngineSettings
    regime_result: Any
    t212_data: dict[str, Any]
    ai_recs: dict[str, Any]
    portfolio_rows: list[dict[str, Any]]
    unified_technicals: dict[str, Any]
    yahoo_by_display: dict[str, str | None]
    extra_tech: dict[str, dict]
    extra_news: dict[str, list[dict]]
    news_by_symbol: dict[str, list[dict[str, Any]]]
    news_context_path: str | None
    candidate_section: str
    portfolio_context: dict[str, Any]
    snapshot: Any
    recon_result: Any


@dataclass
class AIContextPhase:
    """AI-context output consumed by the report phase."""

    context_file: Any
    run_id: str


def save_ai_context_phase(inputs: AIContextInputs) -> AIContextPhase:
    """Build and save the machine context file."""
    settings = inputs.settings
    regime_result = inputs.regime_result
    t212_data = inputs.t212_data
    ai_recs = inputs.ai_recs
    portfolio_rows = inputs.portfolio_rows
    unified_technicals = inputs.unified_technicals
    yahoo_by_display = inputs.yahoo_by_display
    extra_tech = inputs.extra_tech
    extra_news = inputs.extra_news
    news_by_symbol = inputs.news_by_symbol
    news_context_path = inputs.news_context_path
    candidate_section = inputs.candidate_section
    portfolio_context = inputs.portfolio_context
    _snap = inputs.snapshot
    _recon_result = inputs.recon_result

    # AI context file – full archive for machines: verbose per-ticker analysis,
    # all technicals and all headlines (human report stays curated).
    output_dir = Path("reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        "\n".join(
            tech_summary_line(sym, ind) for sym, ind in sorted(extra_tech.items())
        )
        [e for entries in list(news_by_symbol.values()) + list(extra_news.values()) for e in entries]
        try:
            from investment_engine.reporting.regime_report import unresolved_market_data as _unresolved_md
            _unresolved_syms = _unresolved_md(portfolio_rows)
        except Exception:
            _unresolved_syms = []
        _unresolved_note = (
            "\n\n## Market-data coverage\n"
            + ("Market-data mapping unavailable; broker valuation retained for: "
               + ", ".join(_unresolved_syms) + "." if _unresolved_syms
               else "All holdings have verified market-data mappings.")
        )
        # Build reconciliation result for AI context
        # Uses the same canonical _recon_result; no independent calculation.
        try:
            reconciliation = _recon_result
        except Exception:
            reconciliation = None

        # Build account snapshot for AI context
        # Reuses the canonical _snap built earlier; never rebuilds.
        try:
            account_snapshot = _snap if _snap is not None else None
        except Exception:
            account_snapshot = None

        # Build FX info
        try:
            from trading212.portfolio import get_live_fx_rates as _live_fx2
            fx_info = _live_fx2()
        except Exception:
            fx_info = {}

        # Build catalog meta
        try:
            import json as _json
            from pathlib import Path as _Path
            _cat_path = _Path("data/cache/t212_instruments.json")
            if _cat_path.exists():
                _cat_data = _json.loads(_cat_path.read_text(encoding="utf-8"))
                _fetched_at = str(_cat_data.get("fetched_at", "") or "")
                _age_days = None
                if _fetched_at:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        _fetched_dt = _dt.fromisoformat(_fetched_at.replace("Z", "+00:00"))
                        if _fetched_dt.tzinfo is None:
                            _fetched_dt = _fetched_dt.replace(tzinfo=_tz.utc)
                        _age_days = round((_dt.now(_tz.utc) - _fetched_dt).total_seconds() / 86400.0, 2)
                    except Exception:
                        _age_days = None
                catalog_meta = {
                    "fetched_at": _fetched_at,
                    # None (not 0.0) when unknown — the builder renders None as
                    # "unavailable" and a real 0.0 as fresh (0.0 is falsy!).
                    "age_days": _age_days,
                    "count": _cat_data.get("count", 0),
                }
            else:
                catalog_meta = {}
        except Exception:
            catalog_meta = {}

        # Build external research (signals from AI recs that are not broker positions)
        external_research = {}
        watchlist = []
        if ai_recs:
            # Extract watchlist ideas from candidate section
            try:
                from investment_engine.reporting.documents import extract_validated_ideas as _extract_ideas
                from investment_engine.portfolio.symbols import support_state as _ssw
                from investment_engine.portfolio.symbols import to_yahoo_symbol as _tyw
                def _idea_supported(ticker: str) -> bool:
                    try:
                        return _ssw(_tyw(ticker, ticker, {}), "market_data") == "SUPPORTED"
                    except Exception:
                        return False
                _ideas = _extract_ideas(candidate_section, news_by_symbol, _idea_supported)
                for idea in _ideas:
                    watchlist.append({
                        "ticker": idea.get("ticker", ""),
                        "signal": "WATCH",
                        "horizon": "research",
                        "catalyst": idea.get("reason", ""),
                        "key_level": "",
                    })
            except Exception:
                pass

        # uuid here used to fork ai_context onto a different run_id (7e520fb5
        # vs wrapper 524fffa0). "UNKNOWN" only when the caller passed none —
        # the wrapper consistency check flags that case in the manifest.
        run_id = str((portfolio_context or {}).get("run_id", "") or "") or "UNKNOWN"

        # Collect model info for attribution (configured intent + actual winners).
        model_info = {
            "decision_model": settings.decision_model,
            "summary_model": settings.writer_model,
            "discovery_model": getattr(settings, "thinking_model", settings.decision_model),
            "decision_detail_model": getattr(settings, "finance_model", settings.decision_model),
            "ai_aggressiveness": getattr(settings, "ai_aggressiveness", "balanced"),
            "providers_per_stage": {k: dict(v) for k, v in _STAGE_ATTRIBUTION.items()},
        }
        stage_attribution = {k: dict(v) for k, v in _STAGE_ATTRIBUTION.items()}

        context_file = save_ai_context(
            regime_result=regime_result,
            t212_data=t212_data,
            portfolio_rows=portfolio_rows,
            technicals=unified_technicals,
            yahoo_map=yahoo_by_display,
            external_research=external_research,
            watchlist=watchlist,
            reconciliation=reconciliation,
            account_snapshot=account_snapshot,
            fx_info=fx_info,
            catalog_meta=catalog_meta,
            output_dir=output_dir,
            run_id=run_id,
            model_info=model_info,
            news_context_path=news_context_path,
            stage_attribution=stage_attribution,
        )
    except Exception as exc:
        logger.warning("AI context save failed: %s", exc)
        # Fallback minimal context — MUST reuse the same run_id so the
        # fallback file never forks onto a random id (see run 524fffa0:
        # content carried 7e520fb5 while every other artifact said 524fffa0).
        context_file = save_ai_context(
            regime_result=regime_result,
            t212_data=t212_data,
            portfolio_rows=portfolio_rows,
            technicals=unified_technicals,
            yahoo_map=yahoo_by_display,
            external_research={},
            watchlist=[],
            reconciliation=None,
            account_snapshot=None,
            fx_info={},
            catalog_meta={},
            output_dir=output_dir,
            run_id=run_id if "run_id" in dir() else "UNKNOWN",
            model_info=model_info,
            news_context_path=news_context_path,
            stage_attribution=stage_attribution if "stage_attribution" in dir() else None,
        )
    return AIContextPhase(context_file=context_file, run_id=run_id)

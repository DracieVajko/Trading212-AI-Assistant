"""Machine context archive writer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from investment_engine.portfolio.broker_first import AccountSnapshot, ReconciliationResult
from investment_engine.reporting.regime_report import AIContextReportBuilder
from investment_engine.research.market_regime import RegimeResult

def _save_ai_context(
    regime_result: RegimeResult,
    t212_data: dict | None,
    portfolio_rows: list[dict] | None,
    technicals: dict | None,
    yahoo_map: dict | None,
    external_research: dict | None,
    watchlist: list[dict] | None,
    reconciliation: ReconciliationResult | None,
    account_snapshot: AccountSnapshot | None,
    fx_info: dict | None,
    catalog_meta: dict | None,
    output_dir: Path,
    run_id: str = "",
    model_info: dict | None = None,
    news_context_path: str | None = None,
    stage_attribution: dict | None = None,
) -> Path:
    """Save machine-safe AI context report using broker-first model."""
    builder = AIContextReportBuilder()
    context = builder.build_report(
        regime_result=regime_result,
        t212_data=t212_data,
        portfolio_rows=portfolio_rows,
        technicals=technicals,
        yahoo_map=yahoo_map,
        external_research=external_research,
        watchlist=watchlist,
        reconciliation=reconciliation,
        account_snapshot=account_snapshot,
        fx_info=fx_info,
        catalog_meta=catalog_meta,
        run_id=run_id,
        model_info=model_info,
        news_context_path=news_context_path,
        stage_attribution=stage_attribution,
    )
    # Single AI-context path (deduped): the ai_context/ layer owns this file.
    # save_ai_context_layer() persists the sibling portfolio_analysis JSON and
    # skips re-copying this identical .md (see report_structure).
    layer_dir = Path(output_dir) / "ai_context"
    layer_dir.mkdir(parents=True, exist_ok=True)
    stamp = (run_id or "").strip() or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    context_file = layer_dir / f"ai_context_{stamp}.md"
    context_file.write_text(context, encoding="utf-8")
    return context_file

save_ai_context = _save_ai_context

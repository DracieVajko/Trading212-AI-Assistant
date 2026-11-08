"""PIE enrichment: PIE blocks construction and PIE deep-dive AI sections.

Extracted from investment_engine/run_phases/enrichment.py to keep modules focused.
"""

from __future__ import annotations

import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from dataclasses import dataclass, field
from typing import Any

from investment_engine import liveness as _lv
from investment_engine.config.settings import EngineSettings
from investment_engine.portfolio.symbols import (
    build_known_maps,
    to_display_symbol,
    to_yahoo_symbol,
)
from investment_engine.providers.generation import generate_with_fallback
from investment_engine.reporting.sections import (
    enforce_canonical_in_pie_section,
    headlines_block,
)
from investment_engine.research.corpus import source_status as _srcstat
from investment_engine.research.corpus.builder import (
    build_corpus_files as _build_corpus,
)
from investment_engine.research.corpus.builder import (
    render_rejected_markdown as _render_rej,
)
from investment_engine.research.earnings_fetch import (
    fetch_earnings_for_symbols,
    fetch_news_for_extra_tickers,
    fetch_technicals_parallel,
    tech_summary_line,
)

logger = logging.getLogger(__name__)


@dataclass
class PieEnrichmentInputs:
    """Inputs for PIE enrichment."""

    assets: list[dict[str, Any]]
    tech_pies: list[dict[str, Any]]
    renewable_pies: list[dict[str, Any]]
    passive_pies: list[dict[str, Any]]
    all_active_assets: list[dict[str, Any]]
    t212_data: dict[str, Any]
    standalone: list[dict[str, Any]]
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
    yahoo_by_display: dict[str, str | None] = field(default_factory=dict)
    known_clean: set[str] = field(default_factory=set)
    aliases: dict[str, Any] = field(default_factory=dict)
    playwright_earnings: int = 0


@dataclass
class PieEnrichmentResult:
    """Result of PIE enrichment."""

    pie_blocks: list[dict[str, Any]]
    playwright_stats: dict
    tvnews_stats: dict
    corpus_info: dict
    corpus_run_id: str
    universe_info: dict
    decision_sections: list[str]
    verbose_sections: list[str]
    source_ledger: list[dict[str, Any]]


def enrich_pies(inputs: PieEnrichmentInputs) -> PieEnrichmentResult:
    """Build PIE blocks and generate PIE deep-dive AI sections."""

    assets = inputs.assets
    tech_pies = inputs.tech_pies
    renewable_pies = inputs.renewable_pies
    passive_pies = inputs.passive_pies
    all_active_assets = inputs.all_active_assets
    t212_data = inputs.t212_data
    standalone = inputs.standalone
    settings = inputs.settings
    settings_dict = inputs.settings_dict
    provider = inputs.provider
    run_id = inputs.run_id
    reports_dir = inputs.reports_dir
    language = inputs.language
    portfolio_context = inputs.portfolio_context
    canonical_map = inputs.canonical_map
    canonical_display_note = inputs.canonical_display_note
    canonical_note = inputs.canonical_note
    regime_context = inputs.regime_context
    decision_sections = inputs.decision_sections
    verbose_sections = inputs.verbose_sections
    source_ledger = inputs.source_ledger
    news_by_symbol = inputs.news_by_symbol
    yahoo_by_display = inputs.yahoo_by_display
    known_clean = inputs.known_clean
    aliases = inputs.aliases
    playwright_earnings = inputs.playwright_earnings

    # --- PIE blocks: match T212 positions to pie slices by DISPLAY symbol ---
    _summ = (t212_data or {}).get("account_summary", {}) or {}
    t212_positions_all = list(_summ.get("all_positions") or [])
    if not t212_positions_all:
        t212_positions_all = list((t212_data or {}).get("all_positions") or [])
    if not t212_positions_all:
        t212_positions_all = list((t212_data or {}).get("positions", []) or [])

    pos_by_display: dict[str, dict] = {}
    for pos in t212_positions_all:
        if isinstance(pos, dict) and pos.get("symbol"):
            pos_by_display[to_display_symbol(str(pos.get("symbol")), known_clean)] = pos

    pie_blocks = []
    for pie in (tech_pies + renewable_pies + passive_pies):
        holdings = pie.get("holdings", []) if isinstance(pie, dict) else []
        enriched = []
        for h in holdings:
            sl = str(h.get("slice", "")).strip().upper()
            if not sl:
                continue
            match = pos_by_display.get(to_display_symbol(sl, known_clean))
            enriched.append({
                "slice": sl,
                "name": h.get("name", sl),
                "value_eur": (match or {}).get("value_eur", 0) or 0,
                "pnl_pct": (match or {}).get("pnl_pct", 0) or 0,
                "matched": match is not None,
            })
        matched = [e for e in enriched if e["matched"]]
        total_v = sum(e["value_eur"] for e in enriched)
        sample = sorted(matched, key=lambda e: e["value_eur"], reverse=True)[:4]
        if len(sample) < 4:
            seen = {e["slice"] for e in sample}
            for e in enriched:
                if e["slice"] not in seen:
                    sample.append(e)
                if len(sample) >= 4:
                    break
        pie_blocks.append({
            "name": pie.get("name", "PIE") if isinstance(pie, dict) else "PIE",
            "count": len(enriched),
            "matched_count": len(matched),
            "value_eur": total_v,
            "holdings": enriched,
            "sample": sample,
        })

    # --- Technicals + news + earnings for PIE samples ---
    for b in pie_blocks:
        for s in b["sample"]:
            disp = to_display_symbol(s["slice"], known_clean)
            s["display"] = disp
            if disp not in yahoo_by_display:
                yahoo_by_display[disp] = to_yahoo_symbol(s["slice"], disp, aliases)

    yahoo_pairs = [(disp, y) for disp, y in yahoo_by_display.items() if y]
    extra_tech = fetch_technicals_parallel(yahoo_pairs)
    extra_news = fetch_news_for_extra_tickers(
        settings_dict,
        [(s["display"], yahoo_by_display.get(s["display"]) or s["display"], s["name"])
         for b in pie_blocks for s in b["sample"] if yahoo_by_display.get(s["display"])],
    )
    extra_earn = fetch_earnings_for_symbols(yahoo_by_display)

    # --- Playwright sweep (TradingView technicals) ---
    playwright_stats: dict = {"technicals": 0, "facts": 0, "attempted": 0,
                              "earnings": playwright_earnings}
    try:
        from investment_engine.research.corpus import adapters_tradingview as _tv
        _tv.reset()
        if getattr(settings, "use_playwright_fallback", True):
            _t212_by_display: dict[str, str] = {}
            for _sp in standalone:
                if isinstance(_sp, dict) and _sp.get("display") and _sp.get("t212"):
                    _t212_by_display[str(_sp["display"]).strip().upper()] = str(
                        _sp["t212"])
            _sweep_cands: list[tuple] = []
            for _disp, _yh in (yahoo_by_display or {}).items():
                if not _yh or str(_yh).upper().endswith("-USD"):
                    continue
                if _disp in (extra_tech or {}):
                    continue
                _sweep_cands.append((_disp, _yh, _t212_by_display.get(_disp)))
                if len(_sweep_cands) >= 8:
                    break
            if _sweep_cands:
                _sweep = _tv.run_sweep(_sweep_cands, assets, max_symbols=8,
                                       timeout_ms=30000)
                for _d, _t in (_sweep.get("technicals") or {}).items():
                    extra_tech.setdefault(_d, _t)
                for _item in (_sweep.get("items") or []):
                    _tags = _item.get("ticker_tags") or []
                    if _tags:
                        news_by_symbol.setdefault(_tags[0], []).append(_item)
                playwright_stats = {
                    "technicals": len(_sweep.get("technicals", {}) or {}),
                    "facts": len(_sweep.get("items", []) or []),
                    "attempted": (_sweep.get("stats", {}) or {}).get("attempted", 0),
                    "earnings": playwright_earnings,
                }
                logger.info("Playwright sweep: %(attempted)d pages, "
                            "%(technicals)d technicals, %(facts)d facts",
                            playwright_stats)
                try:
                    _got = playwright_stats["technicals"] + playwright_stats["facts"]
                    _srcstat.record(source_ledger, adapter="tradingview.sweep",
                                    domain="technicals_facts",
                                    status="SUCCESS_WITH_ITEMS" if _got
                                    else "SUCCESS_EMPTY",
                                    raw_count=playwright_stats["attempted"],
                                    normalized_count=_got, selected_count=_got)
                except Exception:
                    pass
            else:
                try:
                    _srcstat.record(source_ledger, adapter="tradingview.sweep",
                                    domain="technicals_facts",
                                    status="NOT_ATTEMPTED")
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("Playwright sweep skipped: %s", type(exc).__name__)
        try:
            _srcstat.record(source_ledger, adapter="tradingview.sweep",
                            domain="technicals_facts",
                            status="FAILED", error=type(exc).__name__)
        except Exception:
            pass

    # --- TV symbol news ---
    tvnews_stats: dict = {"items": 0, "symbols": 0, "attempted": 0}
    try:
        from investment_engine.research.corpus import adapters_tvnews as _tvn
        _tvn.reset()
        _val_by_display: dict[str, float] = {}
        for _sp in standalone:
            if isinstance(_sp, dict) and _sp.get("display"):
                _val_by_display[str(_sp["display"]).strip().upper()] = float(
                    _sp.get("value_eur", 0) or 0)
        _news_pool: list[tuple] = []
        for _disp, _yh in (yahoo_by_display or {}).items():
            if not _yh or str(_yh).upper().endswith("-USD"):
                continue
            _news_pool.append((_val_by_display.get(str(_disp).strip().upper(), 0.0),
                               _disp, _yh))
        _news_pool.sort(key=lambda t: t[0], reverse=True)
        _news_cands = [(_d, _y) for _, _d, _y in _news_pool[:8]]
        if _news_cands:
            _tvn_res = _tvn.fetch_symbol_news(_news_cands, assets,
                                              limit_per_symbol=10)
            for _item in (_tvn_res.get("items") or []):
                _tags = _item.get("ticker_tags") or []
                if _tags:
                    news_by_symbol.setdefault(_tags[0], []).append(_item)
            _tvn_stats = _tvn_res.get("stats", {}) or {}
            tvnews_stats = {
                "items": int(_tvn_stats.get("items", 0)),
                "symbols": int(_tvn_stats.get("symbols", 0)),
                "attempted": int(_tvn_stats.get("attempted", 0)),
            }
            logger.info("TV symbol news: %(attempted)d symbols attempted, "
                        "%(symbols)d with news, %(items)d items", tvnews_stats)
            try:
                _srcstat.record(source_ledger, adapter="tradingview.symbol_news",
                                domain="symbol_news",
                                status="SUCCESS_WITH_ITEMS"
                                if tvnews_stats["items"] else "SUCCESS_EMPTY",
                                raw_count=tvnews_stats["attempted"],
                                normalized_count=tvnews_stats["items"],
                                selected_count=tvnews_stats["items"])
            except Exception:
                pass
    except Exception as exc:
        logger.debug("TV symbol news skipped: %s", type(exc).__name__)
        try:
            _srcstat.record(source_ledger, adapter="tradingview.symbol_news",
                            domain="symbol_news",
                            status="FAILED", error=type(exc).__name__)
        except Exception:
            pass

    # --- Research corpus ---
    _corpus_run_id = str((portfolio_context or {}).get("run_id", "") or "")
    corpus_info: dict = {"counts": {"total": 0, "decision": 0, "background": 0,
                                    "undated": 0, "rejected": 0, "failed_buckets": 0,
                                    "schema_invalid": 0},
                         "path_md": None, "path_json": None, "path_rejected": None,
                         "items": [], "decision_items": [], "rejected_items": []}
    universe_info: dict = {"resolved": 0, "skipped_working": 0, "missed": 0}
    try:
        _names_map = {}
        _universe_syms = set()
        try:
            _all_names = [
                (h.get("slice"), h.get("name"))
                for pie in (tech_pies + renewable_pies + passive_pies)
                for h in (pie.get("holdings", []) if isinstance(pie, dict) else [])
            ] + [(str(a.get("broker_symbol") or ""), str(a.get("name") or ""))
                 for a in assets or []]
            _, _names_map = build_known_maps(_all_names, assets)
            _universe_syms = {str(s).strip().upper() for s in
                              ((all_active_assets if "all_active_assets"
                                in dir() else assets) or [])
                              for s in [str(e.get("ticker") or "")]}
            _universe_syms.discard("")
        except Exception:
            _names_map, _universe_syms = {}, set()
        corpus_info = _build_corpus(
            news_by_symbol,
            run_id=_corpus_run_id,
            output_dir=settings_dict.get("output_folder", "reports"),
            names_map=_names_map,
            universe_symbols=_universe_syms or None,
        )
        logger.info("Research corpus: %(total)d items (%(decision)d decision, "
                    "%(background)d background, %(undated)d undated, "
                    "%(rejected)d rejected)",
                    {k: corpus_info.get("counts", {}).get(k, 0)
                     for k in ("total", "decision", "background", "undated",
                               "rejected")})
        try:
            _debug_dir = ROOT / "reports" / "debug" / _corpus_run_id
            _debug_dir.mkdir(parents=True, exist_ok=True)
            _rej_path = _debug_dir / "undated_or_rejected_research.md"
            _rej_path.write_text(
                _render_rej(corpus_info.get("rejected_items", []) or [],
                            _corpus_run_id), encoding="utf-8")
            corpus_info["path_rejected"] = str(_rej_path)
        except Exception as exc2:
            logger.debug("Rejected-research ledger skipped: %s",
                         type(exc2).__name__)
    except Exception as exc:
        logger.debug("Research corpus skipped: %s", type(exc).__name__)

    # Checkpoint: research corpus
    _lv.write_checkpoint(reports_dir, run_id, "research", {
        "corpus_counts": (corpus_info.get("counts", {})
                          if isinstance(corpus_info, dict) else {}),
        "corpus_run_id": _corpus_run_id,
    })

    # --- PIE AI sections ---
    if any(b["sample"] for b in pie_blocks):
        pie_parts = []
        for b in pie_blocks:
            det = []
            for s in b["sample"]:
                disp = to_display_symbol(s["slice"], known_clean)
                s["display"] = disp
                det.append(f"  - {disp} ({s['name']}) | value="
                           f"{s['value_eur']:,.2f} | P&L={s['pnl_pct']:+.1f}% | "
                           f"{tech_summary_line(disp, extra_tech.get(disp))} | "
                           f"earnings={extra_earn.get(disp, 'unavailable')}")
            pie_parts.append(
                f"PIE {b['name']}: {b['count']} holdings, "
                f"{b['matched_count']} matched in broker, "
                f"matched value={b['value_eur']:,.2f}\n"
                + "\n".join(det))
        pie_prompt = f"""Write only the 'PIEs - evaluation' section of a concise portfolio report in {language}. This is research, not financial advice.
For EACH pie below output:
1. Verdict line: PIE NAME - HOLD / ACCUMULATE / TRIM - one-line reason (aggregate P&L + sampled technicals + sector view).
2. Sector view (1-2 sentences): how is the sector of its holdings doing, based on the technicals and headlines supplied.
3. One bullet per sampled stock, using EXACTLY this format with the DISPLAY ticker and the CANONICAL signal shown (do NOT change the signal; keep the technical observation after the em dash):
TICKER - SIGNAL - one-line technical observation - support/resistance.
CANONICAL DISPLAY TICKERS AND SIGNALS (final - use verbatim): {canonical_display_note}.
Do not invent prices, results, dates, news, or analyst opinions. Sampled stocks are a detail sample; the verdict is for the whole PIE.{canonical_note}

MARKET REGIME CONTEXT:
{regime_context}

PIES:
{chr(10).join(pie_parts)}

RECENT HEADLINES (48h, sampled constituents):
{headlines_block({k: v for k, v in extra_news.items()
                  if any(k == (s.get('display') or s['slice'])
                         for b in pie_blocks for s in b['sample'])})}"""
        pie_section = generate_with_fallback(
            provider, pie_prompt, settings, tokens=3072, stage="decision")
        pie_section = enforce_canonical_in_pie_section(
            pie_section, canonical_map, known_clean)
        decision_sections.append(f"## PIEs - evaluation\n{pie_section}")

    return PieEnrichmentResult(
        pie_blocks=pie_blocks,
        playwright_stats=playwright_stats,
        tvnews_stats=tvnews_stats,
        corpus_info=corpus_info,
        corpus_run_id=_corpus_run_id,
        universe_info=universe_info,
        decision_sections=decision_sections,
        verbose_sections=verbose_sections,
        source_ledger=source_ledger,
    )

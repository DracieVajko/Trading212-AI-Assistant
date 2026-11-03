"""Research enrichment: T212 standalone holdings and PIE deep dive.

This module owns the per-position enrichment loop (technicals, news, earnings,
dividends, analyst consensus, energy snapshot, corpus) plus the standalone and
PIE AI sections. It was extracted from ``run_engine`` to keep the orchestrator
readable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from investment_engine import liveness as _lv
from investment_engine.config.settings import EngineSettings
from investment_engine.research.market_data import analyst_consensus
from investment_engine.research.corpus import source_status as _srcstat
from investment_engine.fetching import load_symbol_aliases
from investment_engine.providers.generation import generate_with_fallback
from investment_engine.reporting.sections import (
    enforce_canonical_in_pie_section,
    headlines_block,
)
from investment_engine.research.earnings_fetch import (
    fetch_earnings_for_symbols,
    fetch_news_for_extra_tickers,
    fetch_technicals_parallel,
    tech_summary_line,
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
    assets = inputs.assets
    tech_pies = inputs.tech_pies
    renewable_pies = inputs.renewable_pies
    passive_pies = inputs.passive_pies
    all_active_assets = inputs.all_active_assets
    t212_data = inputs.t212_data
    _snap = inputs.snapshot
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
    playwright_earnings = inputs.playwright_earnings

    # Fail-safe defaults in case the enrichment body aborts early.
    aliases: dict[str, Any] = {}
    analyst_consensus_map: dict[str, str] = {}
    dividends_12m: dict[str, dict] = {}
    energy_snapshot: dict = {"benchmarks": {}, "stats": {"attempted": 0, "ok": 0}}
    unified_technicals_seed: dict[str, Any] = {}

    # 7b. T212 standalone holdings (outside PIEs) – per-stock data like legacy build:
    # price/RSI/SMA/support/resistance + 48h news + P&L, with AI BUY/SELL/HOLD per ticker.
    # 7c. PIE deep-dive – aggregate per PIE + detailed sample of constituents + sector view.
    # Both go through _generate_with_fallback, i.e. the full chained provider
    # (local → OpenRouter free → Gemini → Mistral → OpenCodeZen).
    standalone: list[dict] = []
    pie_blocks: list[dict] = []
    extra_tech: dict[str, dict] = {}
    extra_news: dict[str, list[dict]] = {}
    extra_earn: dict[str, str] = {}
    playwright_stats: dict = {"technicals": 0, "facts": 0, "attempted": 0, "earnings": 0}
    tvnews_stats: dict = {"items": 0, "symbols": 0, "attempted": 0}
    corpus_info: dict = {"counts": {"total": 0, "decision": 0, "background": 0,
                                    "undated": 0, "rejected": 0, "failed_buckets": 0,
                                    "schema_invalid": 0},
                         "path_md": None, "path_json": None, "path_rejected": None,
                         "items": [], "decision_items": [], "rejected_items": []}
    _corpus_run_id: str = ""
    universe_info: dict = {"resolved": 0, "skipped_working": 0, "missed": 0}
    # display -> yahoo for every enrichment symbol (single mapping layer).
    yahoo_by_display: dict[str, str | None] = {}
    # Known clean tickers + names from pie CSVs and config assets.
    known_clean: set = set()
    try:
        from investment_engine.portfolio.symbols import (
            build_known_maps as _build_known_maps,
            to_display_symbol as _to_display,
            to_yahoo_symbol as _to_yahoo,
        )
        aliases = load_symbol_aliases(portfolio_context)
        _summ = (t212_data or {}).get("account_summary", {}) or {}
        # Authoritative broker snapshot; `positions` is fallback only and is
        # never merged into `all_positions`.
        t212_positions_all = list(_summ.get("all_positions") or [])
        if not t212_positions_all:
            t212_positions_all = list((t212_data or {}).get("all_positions") or [])
        if not t212_positions_all:
            t212_positions_all = list((t212_data or {}).get("positions", []) or [])

        # Known universe for display stripping + name resolution.
        _pie_slices = [
            (h.get("slice"), h.get("name"))
            for pie in (tech_pies + renewable_pies + passive_pies)
            for h in (pie.get("holdings", []) if isinstance(pie, dict) else [])
        ]
        known_clean, _known_names = _build_known_maps(_pie_slices, assets)
        for _k, _v in (aliases or {}).items():
            known_clean.add(str(_k).strip().upper())

        standalone = []
        for pos in t212_positions_all:
            if not isinstance(pos, dict) or pos.get("is_pie_constituent"):
                continue
            qty = pos.get("quantity") or 0
            if qty <= 0:
                continue
            t_sym = str(pos.get("symbol", ""))
            disp = _to_display(t_sym, known_clean)
            yahoo = _to_yahoo(t_sym, disp, aliases)
            yahoo_by_display[disp] = yahoo
            standalone.append({
                "t212": t_sym,
                "display": disp,
                "yahoo": yahoo,
                "qty": qty,
                "value_eur": pos.get("value_eur", 0) or 0,
                "pnl_eur": pos.get("pnl_eur", 0) or 0,
                "pnl_pct": pos.get("pnl_pct", 0) or 0,
            })
        standalone = sorted(standalone, key=lambda p: p["value_eur"], reverse=True)[:20]

        # Complete display -> Yahoo map for every authoritative position
        # (no network here; verification happens before each request).
        for pos in t212_positions_all:
            if isinstance(pos, dict) and pos.get("symbol"):
                try:
                    _d = _to_display(str(pos["symbol"]), known_clean)
                    yahoo_by_display.setdefault(_d, _to_yahoo(str(pos["symbol"]), _d, aliases))
                except Exception:
                    pass

        # PIE aggregates: match T212 positions to pie slices by DISPLAY symbol
        # (single mapping layer, so C7A0d_EQ matches the C7A0 pie slice).
        pos_by_display: dict[str, dict] = {}
        for pos in t212_positions_all:
            if isinstance(pos, dict) and pos.get("symbol"):
                pos_by_display[_to_display(str(pos.get("symbol")), known_clean)] = pos
        pie_blocks = []
        for pie in (tech_pies + renewable_pies + passive_pies):
            holdings = pie.get("holdings", []) if isinstance(pie, dict) else []
            enriched = []
            for h in holdings:
                sl = str(h.get("slice", "")).strip().upper()
                if not sl:
                    continue
                match = pos_by_display.get(_to_display(sl, known_clean))
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
                "sample": sample,
            })

        # Technicals + news + earnings for standalone + sampled pie slices.
        # Everything is keyed by DISPLAY symbol; Yahoo tickers come only from
        # the explicit mapping layer (never company names).
        for b in pie_blocks:
            for s in b["sample"]:
                disp = _to_display(s["slice"], known_clean)
                s["display"] = disp
                if disp not in yahoo_by_display:
                    yahoo_by_display[disp] = _to_yahoo(s["slice"], disp, aliases)
        # Universe enrichment (default on): ISIN-keyed cross-listing discovery
        # fills ONLY missing/unresolvable entries; working mappings (tables,
        # config aliases) are never overridden. Degrades to a no-op on any
        # failure (UNIVERSE_ENABLED=0 disables entirely).
        try:
            from investment_engine.research import universe as _uni
            from investment_engine.portfolio.symbols import support_state as _ss
            if _uni.enabled() and _snap is not None:
                _snap_rows = [{
                    "display_symbol": str(getattr(getattr(p, "instrument", None), "display_symbol", "") or ""),
                    "isin": str(getattr(getattr(p, "instrument", None), "isin", "") or ""),
                    "currency": str(getattr(getattr(p, "instrument", None), "currency", "") or ""),
                } for p in (_snap.positions or [])]
                universe_info = _uni.enrich_yahoo_map(
                    yahoo_by_display, _snap_rows,
                    is_working=lambda y: bool(y) and _ss(str(y), "market_data") == "SUPPORTED")
                logger.info("Universe enrichment: %(resolved)d resolved, "
                            "%(skipped_working)d kept, %(missed)d still missing",
                            {k: universe_info.get(k, 0) for k in ("resolved", "skipped_working", "missed")})
        except Exception as exc:
            logger.debug("Universe enrichment skipped: %s", type(exc).__name__)
        # Yahoo lookup pairs, skipping unsupported instruments cleanly.
        yahoo_pairs = [(disp, y) for disp, y in yahoo_by_display.items() if y]
        extra_tech = fetch_technicals_parallel(yahoo_pairs)
        extra_news = fetch_news_for_extra_tickers(
            settings_dict,
            [(p["display"], p["yahoo"] or p["display"], p["display"]) for p in standalone if p.get("yahoo")]
            + [(s["display"], yahoo_by_display.get(s["display"]) or s["display"], s["name"]) for b in pie_blocks for s in b["sample"] if yahoo_by_display.get(s["display"])],
        )
        extra_earn = fetch_earnings_for_symbols(yahoo_by_display)
        # Technicals keyed by display symbol for row enrichment.
        unified_technicals_seed = dict(extra_tech or {})

        # Playwright sweep (automatic): every display with a Yahoo mapping but
        # no technicals gets one TradingView page (gauge technicals + key facts
        # + analyst rating). Caps, serial loads, kill-switch; crypto and
        # underivable venues are skipped, never guessed. Results merge into
        # technicals (distinct TV_ keys) and news buckets (corpus built below).
        playwright_stats: dict = {"technicals": 0, "facts": 0, "attempted": 0,
                                  "earnings": playwright_earnings}
        try:
            from investment_engine.research.corpus import adapters_tradingview as _tv
            _tv.reset()
            if not getattr(settings, "use_playwright_fallback", True):
                try:
                    _srcstat.record(source_ledger, adapter="tradingview.sweep", domain="technicals_facts",
                                    status="DISABLED", error="use_playwright_fallback off")
                except Exception:
                    pass
            if getattr(settings, "use_playwright_fallback", True):
                _t212_by_display: dict[str, str] = {}
                for _sp in standalone or []:
                    if isinstance(_sp, dict) and _sp.get("display") and _sp.get("t212"):
                        _t212_by_display[str(_sp["display"]).strip().upper()] = str(_sp["t212"])
                _sweep_cands: list[tuple] = []
                for _disp, _yh in (yahoo_by_display or {}).items():
                    if not _yh or str(_yh).upper().endswith("-USD"):
                        continue
                    if _disp in (unified_technicals_seed or {}):
                        continue
                    _sweep_cands.append((_disp, _yh, _t212_by_display.get(_disp)))
                    if len(_sweep_cands) >= 8:
                        break
                if _sweep_cands:
                    _sweep = _tv.run_sweep(_sweep_cands, assets, max_symbols=8, timeout_ms=30000)
                    for _d, _t in (_sweep.get("technicals") or {}).items():
                        unified_technicals_seed.setdefault(_d, _t)
                        extra_tech.setdefault(_d, _t)
                    for _item in (_sweep.get("items") or []):
                        _tags = _item.get("ticker_tags") or []
                        if _tags:
                            news_by_symbol.setdefault(_tags[0], []).append(_item)
                    playwright_stats = {"technicals": len(_sweep.get("technicals", {}) or {}),
                                        "facts": len(_sweep.get("items", []) or []),
                                        "attempted": (_sweep.get("stats", {}) or {}).get("attempted", 0),
                                        "earnings": playwright_earnings}
                    logger.info("Playwright sweep: %(attempted)d pages, %(technicals)d technicals, "
                                "%(facts)d facts", playwright_stats)
                    try:
                        _got = playwright_stats["technicals"] + playwright_stats["facts"]
                        _srcstat.record(source_ledger, adapter="tradingview.sweep", domain="technicals_facts",
                                        status="SUCCESS_WITH_ITEMS" if _got else "SUCCESS_EMPTY",
                                        raw_count=playwright_stats["attempted"],
                                        normalized_count=_got, selected_count=_got)
                    except Exception:
                        pass
                else:
                    try:
                        _srcstat.record(source_ledger, adapter="tradingview.sweep", domain="technicals_facts",
                                        status="NOT_ATTEMPTED")
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Playwright sweep skipped: %s", type(exc).__name__)
            try:
                _srcstat.record(source_ledger, adapter="tradingview.sweep", domain="technicals_facts",
                                status="FAILED", error=type(exc).__name__)
            except Exception:
                pass

        # TradingView per-symbol news (plain HTTPS JSON, no browser): top-8
        # resolvable displays BY BROKER VALUE get dated per-symbol headlines
        # merged into news_by_symbol, so they enter the corpus (and decision
        # sets) below with real timestamps. Caps, serial 1 req/s, kill-switch;
        # crypto and underivable venues are skipped, never guessed.
        try:
            from investment_engine.research.corpus import adapters_tvnews as _tvn
            _tvn.reset()
            _t212_map = _t212_by_display if "_t212_by_display" in dir() else {}
            _val_by_display: dict[str, float] = {}
            try:
                for _sp in (standalone if "standalone" in dir() else []) or []:
                    if isinstance(_sp, dict) and _sp.get("display"):
                        _val_by_display[str(_sp["display"]).strip().upper()] = float(
                            _sp.get("value_eur", 0) or 0)
                for _rp in (t212_positions_all if "t212_positions_all" in dir() else []) or []:
                    if not isinstance(_rp, dict) or not _rp.get("symbol"):
                        continue
                    try:
                        from investment_engine.portfolio.symbols import to_display_symbol as _td_tv
                        _dd = str(_td_tv(str(_rp["symbol"]), known_clean
                                         if "known_clean" in dir() else set())).strip().upper()
                        _val_by_display.setdefault(_dd, float(_rp.get("value_eur", 0) or 0))
                    except Exception:
                        continue
            except Exception:
                pass
            _news_pool: list[tuple] = []
            for _disp, _yh in (yahoo_by_display or {}).items():
                if not _yh or str(_yh).upper().endswith("-USD"):
                    continue
                _news_pool.append((_val_by_display.get(str(_disp).strip().upper(), 0.0),
                                   _disp, _yh, _t212_map.get(_disp)))
            _news_pool.sort(key=lambda t: t[0], reverse=True)
            _news_cands = [(_d, _y, _t) for _, _d, _y, _t in _news_pool[:8]]
            if _news_cands:
                _tvn_res = _tvn.fetch_symbol_news(_news_cands, assets, limit_per_symbol=10)
                for _item in (_tvn_res.get("items") or []):
                    _tags = _item.get("ticker_tags") or []
                    if _tags:
                        news_by_symbol.setdefault(_tags[0], []).append(_item)
                _tvn_stats = _tvn_res.get("stats", {}) or {}
                tvnews_stats = {"items": int(_tvn_stats.get("items", 0)),
                                "symbols": int(_tvn_stats.get("symbols", 0)),
                                "attempted": int(_tvn_stats.get("attempted", 0))}
                logger.info("TV symbol news: %(attempted)d symbols attempted, "
                            "%(symbols)d with news, %(items)d items", tvnews_stats)
                try:
                    _srcstat.record(source_ledger, adapter="tradingview.symbol_news", domain="symbol_news",
                                    status="SUCCESS_WITH_ITEMS" if tvnews_stats["items"] else "SUCCESS_EMPTY",
                                    raw_count=tvnews_stats["attempted"],
                                    normalized_count=tvnews_stats["items"],
                                    selected_count=tvnews_stats["items"])
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("TV symbol news skipped: %s", type(exc).__name__)
            try:
                _srcstat.record(source_ledger, adapter="tradingview.symbol_news", domain="symbol_news",
                                status="FAILED", error=type(exc).__name__)
            except Exception:
                pass

        # 3c. Dividends (trailing-12M, yfinance): top SUPPORTED non-crypto
        # holdings by broker value, capped, failure-isolated, parallel.
        # Broker truth untouched — informational yield/ex-date layer.
        dividends_12m: dict[str, dict] = {}
        try:
            from investment_engine.portfolio.symbols import support_state as _ss_div
            from investment_engine.research.market_data import fetch_dividend_summary as _div_one
            from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _ac
            _div_cands: list[tuple] = []
            _div_seen: set[str] = set()
            for _sp in (standalone if "standalone" in dir() else []) or []:
                if not isinstance(_sp, dict):
                    continue
                _dd, _yy = _sp.get("display"), _sp.get("yahoo")
                if _dd and _yy and not str(_yy).upper().endswith("-USD") \
                        and _ss_div(_yy, "market_data") == "SUPPORTED":
                    _div_cands.append((_dd, _yy))
                    _div_seen.add(str(_dd).strip().upper())
                    if len(_div_cands) >= 15:
                        break
            # Standalone covers only non-pie positions (3 of 96) — top up with
            # pie members by broker value so the biggest payers are covered.
            if len(_div_cands) < 15:
                try:
                    _pie_pool: list[tuple] = []
                    for _rp in (t212_positions_all if "t212_positions_all" in dir() else []) or []:
                        if not isinstance(_rp, dict) or not _rp.get("symbol"):
                            continue
                        try:
                            from investment_engine.portfolio.symbols import to_display_symbol as _td_div
                            from investment_engine.portfolio.symbols import to_yahoo_symbol as _ty_div
                            _dd = str(_td_div(str(_rp["symbol"]), known_clean
                                              if "known_clean" in dir() else set())).strip().upper()
                            if not _dd or _dd in _div_seen:
                                continue
                            _yy = _ty_div(str(_rp["symbol"]), _dd, aliases
                                          if "aliases" in dir() else {})
                            if _yy and not str(_yy).upper().endswith("-USD") \
                                    and _ss_div(_yy, "market_data") == "SUPPORTED":
                                _pie_pool.append((float(_rp.get("value_eur", 0) or 0), _dd, _yy))
                        except Exception:
                            continue
                    _pie_pool.sort(key=lambda t: t[0], reverse=True)
                    for _, _dd, _yy in _pie_pool:
                        _div_cands.append((_dd, _yy))
                        _div_seen.add(_dd)
                        if len(_div_cands) >= 15:
                            break
                except Exception:
                    pass

            def _div_fetch(pair):
                _d, _y = pair
                try:
                    return _d, _div_one(_y)
                except Exception:
                    return _d, None

            with _TPE(max_workers=5) as _ex:
                _futs = {_ex.submit(_div_fetch, p): p[0] for p in _div_cands}
                for _f in _ac(_futs):
                    try:
                        _d, _rec = _f.result(timeout=45)
                        if _rec:
                            dividends_12m[_d] = _rec
                    except Exception:
                        pass
            logger.info("Dividends: %d holdings with TTM payouts (of %d checked)",
                        len(dividends_12m), len(_div_cands))
        except Exception as exc:
            logger.debug("Dividends skipped: %s", type(exc).__name__)

        # 3d. Analyst consensus snapshots (yfinance recommendations_summary).
        # Top SUPPORTED non-crypto holdings by broker value, capped at 8,
        # failure-isolated. Stored as {display: "period: buy=.., hold=.., sell=.."}
        # with as_of date and parsed analyst count; missing fields stay explicit.
        analyst_consensus_map: dict[str, str] = {}
        try:
            from investment_engine.portfolio.symbols import support_state as _ss_cons
            _cons_cands: list[tuple] = []
            for _sp in (standalone if "standalone" in dir() else []) or []:
                if not isinstance(_sp, dict):
                    continue
                _dd, _yy = _sp.get("display"), _sp.get("yahoo")
                if (_dd and _yy and not str(_yy).upper().endswith("-USD")
                        and _ss_cons(_yy, "market_data") == "SUPPORTED"):
                    _cons_cands.append((_sp.get("value_eur", 0) or 0, _dd, _yy))
            _cons_cands.sort(key=lambda t: t[0], reverse=True)
            for _, _dd, _yy in _cons_cands[:8]:
                try:
                    # Distinct name: _snap holds the broker AccountSnapshot
                    # (built above) and must never be overwritten by a str.
                    _cons_snap = analyst_consensus(_yy)
                    if _cons_snap:
                        analyst_consensus_map[_dd] = _cons_snap
                except Exception:
                    continue
            logger.info("Analyst consensus: %d snapshots (of %d checked)",
                        len(analyst_consensus_map), min(len(_cons_cands), 8))
        except Exception as exc:
            logger.debug("Analyst consensus skipped: %s", type(exc).__name__)

        # 3e. Energy/commodity price snapshot (benchmark-identified futures).
        # Separate from commodity *news*: an ETF price is never a commodity
        # price. Failure-isolated; per-benchmark errors stay explicit.
        energy_snapshot: dict = {"benchmarks": {}, "stats": {"attempted": 0, "ok": 0}}
        try:
            from investment_engine.research import energy_snapshot as _en
            energy_snapshot = _en.fetch_snapshot()
            logger.info("Energy snapshot: %d/%d benchmarks ok",
                        energy_snapshot.get("stats", {}).get("ok", 0),
                        energy_snapshot.get("stats", {}).get("attempted", 0))
        except Exception as exc:
            logger.debug("Energy snapshot skipped: %s", type(exc).__name__)

        # 2b. Research corpus (moved after the sweep so sweep items are included).
        # Normalize + dedupe + classify everything fetched above into ResearchItems;
        # persist full corpus + decision subset to ai_context/. Additive only.
        # (corpus_info/_corpus_run_id pre-initialized at function level.)
        _corpus_run_id = str((portfolio_context or {}).get("run_id", "") or "")
        try:
            from investment_engine.research.corpus.builder import build_corpus_files as _build_corpus
            from investment_engine.research.corpus.builder import render_rejected_markdown as _render_rej
            # WP2: conservative company-name confirmation needs the known-names
            # map and the full research-universe symbol set.
            _names_map = {}
            _universe_syms = set()
            try:
                from investment_engine.portfolio.symbols import build_known_maps as _bkm
                _all_names = [
                    (h.get("slice"), h.get("name"))
                    for pie in (tech_pies + renewable_pies + passive_pies)
                    for h in (pie.get("holdings", []) if isinstance(pie, dict) else [])
                ] + [(str(a.get("broker_symbol") or ""), str(a.get("name") or "")) for a in assets or []]
                _, _names_map = _bkm(_all_names, assets)
                _universe_syms = {str(s).strip().upper() for s in
                                  ((all_active_assets if "all_active_assets" in dir() else assets) or [])
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
                        "%(background)d background, %(undated)d undated, %(rejected)d rejected)",
                        {k: corpus_info.get("counts", {}).get(k, 0)
                         for k in ("total", "decision", "background", "undated", "rejected")})
            try:
                from pathlib import Path as _Path
                _debug_dir = _Path("reports") / "debug" / _corpus_run_id
                _debug_dir.mkdir(parents=True, exist_ok=True)
                _rej_path = _debug_dir / "undated_or_rejected_research.md"
                _rej_path.write_text(
                    _render_rej(corpus_info.get("rejected_items", []) or [], _corpus_run_id),
                    encoding="utf-8")
                corpus_info["path_rejected"] = str(_rej_path)
            except Exception as exc2:
                logger.debug("Rejected-research ledger skipped: %s", type(exc2).__name__)
        except Exception as exc:
            logger.debug("Research corpus skipped: %s", type(exc).__name__)

        # Checkpoint: research corpus
        _lv.write_checkpoint(reports_dir, run_id, "research", {
            "corpus_counts": (corpus_info.get("counts", {}) if isinstance(corpus_info, dict) else {}),
            "corpus_run_id": _corpus_run_id,
        })

    # NOTE (refactor): the per-position holdings live ONLY in the unified
        # "T212 Portfolio" table (regime_report._t212_portfolio). The legacy
        # standalone LLM section "T212 Holdings — individual (outside PIEs)"
        # was a duplicate verbose breakdown and is intentionally NOT rendered.
        # Standalone data collected above is reused to enrich that single table.
        # (No decision_sections entry for individual holdings by design.)

        if any(b["sample"] for b in pie_blocks):
            pie_parts = []
            for b in pie_blocks:
                det = []
                for s in b["sample"]:
                    disp = s.get("display") or _to_display(s["slice"], known_clean)
                    det.append(f"  - {disp} ({s['name']}) | value=€{s['value_eur']:,.2f} | P&L={s['pnl_pct']:+.1f}% | {tech_summary_line(disp, extra_tech.get(disp))} | earnings={extra_earn.get(disp, 'unavailable')}")
                pie_parts.append(
                    f"PIE {b['name']}: {b['count']} holdings, {b['matched_count']} matched in broker, matched value=€{b['value_eur']:,.2f}\n"
                    + "\n".join(det)
                )
            pie_prompt = f"""Write only the 'PIEs — evaluation' section of a concise portfolio report in {language}. This is research, not financial advice.
For EACH pie below output:
1. Verdict line: PIE NAME — HOLD / ACCUMULATE / TRIM — one-line reason (aggregate P&L + sampled technicals + sector view).
2. Sector view (1-2 sentences): how is the sector of its holdings doing, based on the technicals and headlines supplied.
3. One bullet per sampled stock, using EXACTLY this format with the DISPLAY ticker and the CANONICAL signal shown (do NOT change the signal; keep the technical observation after the em dash):
TICKER — SIGNAL — one-line technical observation — support/resistance.
CANONICAL DISPLAY TICKERS AND SIGNALS (final — use verbatim): {canonical_display_note}.
Do not invent prices, results, dates, news, or analyst opinions. Sampled stocks are a detail sample; the verdict is for the whole PIE.{canonical_note}

MARKET REGIME CONTEXT:
{regime_context}

PIES:
{chr(10).join(pie_parts)}

RECENT HEADLINES (48h, sampled constituents):
{headlines_block({k: v for k, v in extra_news.items() if any(k == (s.get('display') or s['slice']) for b in pie_blocks for s in b['sample'])})}"""
            pie_section = generate_with_fallback(provider, pie_prompt, settings, tokens=3072, stage="decision")
            pie_section = enforce_canonical_in_pie_section(pie_section, canonical_map, known_clean)
            decision_sections.append(f"## PIEs — evaluation\n{pie_section}")
    except Exception as exc:
        logger.warning("T212/PIE deep-dive sections failed: %s", exc)

    return EnrichmentResult(
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
        known_clean=known_clean,
        aliases=aliases,
        analyst_consensus_map=analyst_consensus_map,
        dividends_12m=dividends_12m,
        energy_snapshot=energy_snapshot,
        unified_technicals_seed=unified_technicals_seed,
        decision_sections=decision_sections,
        verbose_sections=verbose_sections,
        source_ledger=source_ledger,
    )

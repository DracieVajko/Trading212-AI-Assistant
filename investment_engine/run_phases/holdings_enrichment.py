"""Holdings enrichment: standalone T212 positions with technicals, news, earnings,
dividends, analyst consensus, energy snapshot, and universe enrichment.

Extracted from investment_engine/run_phases/enrichment.py to keep modules focused.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from investment_engine.config.settings import EngineSettings
from investment_engine.portfolio.symbols import (
    build_known_maps,
    to_display_symbol,
    to_yahoo_symbol,
)
from investment_engine.research.earnings_fetch import (
    fetch_earnings_for_symbols,
    fetch_news_for_extra_tickers,
    fetch_technicals_parallel,
)
from investment_engine.research.market_data import analyst_consensus

logger = logging.getLogger(__name__)


@dataclass
class HoldingsEnrichmentInputs:
    """Inputs for standalone holdings enrichment."""

    assets: list[dict[str, Any]]
    tech_pies: list[dict[str, Any]]
    renewable_pies: list[dict[str, Any]]
    passive_pies: list[dict[str, Any]]
    all_active_assets: list[dict[str, Any]]
    t212_data: dict[str, Any]
    snapshot: Any
    settings: EngineSettings
    settings_dict: dict[str, Any]
    run_id: str
    reports_dir: str
    language: str
    portfolio_context: dict[str, Any]
    known_clean: set[str]
    aliases: dict[str, Any]


@dataclass
class HoldingsEnrichmentResult:
    """Result of standalone holdings enrichment."""

    standalone: list[dict[str, Any]]
    extra_tech: dict[str, dict]
    extra_news: dict[str, list[dict]]
    extra_earn: dict[str, str]
    dividends_12m: dict[str, dict]
    analyst_consensus_map: dict[str, str]
    energy_snapshot: dict
    unified_technicals_seed: dict[str, Any]
    yahoo_by_display: dict[str, str | None]
    known_clean: set[str]
    aliases: dict[str, Any]
    news_by_symbol: dict[str, list[dict[str, Any]]]


def enrich_holdings(inputs: HoldingsEnrichmentInputs) -> HoldingsEnrichmentResult:
    """Enrich standalone T212 positions with technicals, news, earnings,
    dividends, analyst consensus, energy snapshot, and universe enrichment."""

    assets = inputs.assets
    tech_pies = inputs.tech_pies
    renewable_pies = inputs.renewable_pies
    passive_pies = inputs.passive_pies
    t212_data = inputs.t212_data
    _snap = inputs.snapshot
    settings_dict = inputs.settings_dict
    known_clean = set()
    aliases = {}

    # Fail-safe defaults.
    analyst_consensus_map: dict[str, str] = {}
    dividends_12m: dict[str, dict] = {}
    energy_snapshot: dict = {"benchmarks": {}, "stats": {"attempted": 0, "ok": 0}}
    unified_technicals_seed: dict[str, Any] = {}

    # --- Build standalone holdings from T212 positions (outside PIEs) ---
    standalone: list[dict] = []
    _summ = (t212_data or {}).get("account_summary", {}) or {}
    t212_positions_all = list(_summ.get("all_positions") or [])
    if not t212_positions_all:
        t212_positions_all = list((t212_data or {}).get("all_positions") or [])
    if not t212_positions_all:
        t212_positions_all = list((t212_data or {}).get("positions", []) or [])

    _pie_slices = [
        (h.get("slice"), h.get("name"))
        for pie in (tech_pies + renewable_pies + passive_pies)
        for h in (pie.get("holdings", []) if isinstance(pie, dict) else [])
    ]
    known_clean, _known_names = build_known_maps(_pie_slices, assets)
    for _k in (aliases or {}):
        known_clean.add(str(_k).strip().upper())

    for pos in t212_positions_all:
        if not isinstance(pos, dict) or pos.get("is_pie_constituent"):
            continue
        qty = pos.get("quantity") or 0
        if qty <= 0:
            continue
        t_sym = str(pos.get("symbol", ""))
        disp = to_display_symbol(t_sym, known_clean)
        yahoo = to_yahoo_symbol(t_sym, disp, aliases)
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

    # Complete display -> Yahoo map for every authoritative position.
    yahoo_by_display: dict[str, str | None] = {}
    for pos in t212_positions_all:
        if isinstance(pos, dict) and pos.get("symbol"):
            try:
                _d = to_display_symbol(str(pos["symbol"]), known_clean)
                yahoo_by_display.setdefault(
                    _d, to_yahoo_symbol(str(pos["symbol"]), _d, aliases))
            except Exception:
                pass

    # --- Technicals + news + earnings for standalone holdings ---
    yahoo_pairs = [(disp, y) for disp, y in yahoo_by_display.items() if y]
    extra_tech = fetch_technicals_parallel(yahoo_pairs)
    extra_news = fetch_news_for_extra_tickers(
        settings_dict,
        [(p["display"], p["yahoo"] or p["display"], p["display"])
         for p in standalone if p.get("yahoo")],
    )
    extra_earn = fetch_earnings_for_symbols(yahoo_by_display)
    unified_technicals_seed = dict(extra_tech or {})

    # --- Dividends (trailing-12M) ---
    try:
        from concurrent.futures import ThreadPoolExecutor as _TPE
        from concurrent.futures import as_completed as _ac

        from investment_engine.portfolio.symbols import support_state as _ss_div
        from investment_engine.research.market_data import (
            fetch_dividend_summary as _div_one,
        )

        _div_cands: list[tuple] = []
        _div_seen: set[str] = set()
        for _sp in standalone:
            if not isinstance(_sp, dict):
                continue
            _dd, _yy = _sp.get("display"), _sp.get("yahoo")
            if _dd and _yy and not str(_yy).upper().endswith("-USD") \
                    and _ss_div(_yy, "market_data") == "SUPPORTED":
                _div_cands.append((_dd, _yy))
                _div_seen.add(str(_dd).strip().upper())
                if len(_div_cands) >= 15:
                    break

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

    # --- Analyst consensus snapshots ---
    try:
        _cons_cands: list[tuple] = []
        for _sp in standalone:
            if not isinstance(_sp, dict):
                continue
            _dd, _yy = _sp.get("display"), _sp.get("yahoo")
            if (_dd and _yy and not str(_yy).upper().endswith("-USD")
                    and analyst_consensus is not None):
                from investment_engine.portfolio.symbols import (
                    support_state as _ss_cons,
                )
                if _ss_cons(_yy, "market_data") == "SUPPORTED":
                    _cons_cands.append((_sp.get("value_eur", 0) or 0, _dd, _yy))
        _cons_cands.sort(key=lambda t: t[0], reverse=True)
        for _, _dd, _yy in _cons_cands[:8]:
            try:
                _cons_snap = analyst_consensus(_yy)
                if _cons_snap:
                    analyst_consensus_map[_dd] = _cons_snap
            except Exception:
                continue
        logger.info("Analyst consensus: %d snapshots (of %d checked)",
                    len(analyst_consensus_map), min(len(_cons_cands), 8))
    except Exception as exc:
        logger.debug("Analyst consensus skipped: %s", type(exc).__name__)

    # --- Energy/commodity price snapshot ---
    try:
        from investment_engine.research import energy_snapshot as _en
        energy_snapshot = _en.fetch_snapshot()
        logger.info("Energy snapshot: %d/%d benchmarks ok",
                    energy_snapshot.get("stats", {}).get("ok", 0),
                    energy_snapshot.get("stats", {}).get("attempted", 0))
    except Exception as exc:
        logger.debug("Energy snapshot skipped: %s", type(exc).__name__)

    # --- Universe enrichment ---
    universe_info: dict = {"resolved": 0, "skipped_working": 0, "missed": 0}
    try:
        from investment_engine.portfolio.symbols import support_state as _ss
        from investment_engine.research import universe as _uni
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
                        {k: universe_info.get(k, 0)
                         for k in ("resolved", "skipped_working", "missed")})
    except Exception as exc:
        logger.debug("Universe enrichment skipped: %s", type(exc).__name__)

    # Build news_by_symbol from standalone and extra sources
    news_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for p in standalone:
        if p.get("display") and p.get("yahoo"):
            news_by_symbol.setdefault(p["display"], []).append({
                "title": f"Standalone holding: {p['display']}",
                "source": "standalone",
                "url": "",
                "published": "",
            })

    return HoldingsEnrichmentResult(
        standalone=standalone,
        extra_tech=extra_tech,
        extra_news=extra_news,
        extra_earn=extra_earn,
        dividends_12m=dividends_12m,
        analyst_consensus_map=analyst_consensus_map,
        energy_snapshot=energy_snapshot,
        unified_technicals_seed=unified_technicals_seed,
        yahoo_by_display=yahoo_by_display,
        known_clean=known_clean,
        aliases=aliases,
        news_by_symbol=news_by_symbol,
    )

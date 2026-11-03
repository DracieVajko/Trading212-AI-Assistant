"""Earnings, technicals, and analyst-consensus fetchers.

Extracted from ``fetching.py`` to keep each module focused.
"""

from __future__ import annotations

import logging
from concurrent.futures import TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List

from investment_engine.fetching import _symbol
from investment_engine.research.market_data import recent_earnings_date
from investment_engine.research.news_engine import StrictNewsFetcher

logger = logging.getLogger(__name__)

def _fetch_earnings_fast(assets: List[Dict[str, Any]], timeout_per_symbol: float = 3.0) -> dict[str, str]:
    """Fast earnings fetch with timeout per symbol, keyed by DISPLAY ticker.

    Yahoo lookups go through the explicit mapping layer only; company names
    and internal broker IDs never reach yfinance and never become keys.
    """
    from concurrent.futures import ThreadPoolExecutor
    try:
        from investment_engine.portfolio.symbols import (
            is_earnings_supported,
            to_display_symbol as _td_e,
            to_yahoo_symbol as _ty_e,
        )
    except Exception:
        _td_e = lambda s, *_: str(s or "").strip().upper().split("_")[0]
        _ty_e = lambda i, d, a: d
        is_earnings_supported = lambda y: bool(y)

    def fetch_one(asset):
        # ETFs/ETCs publish no earnings: skip before any network call so the
        # run never spams "No earnings dates found" for 20+ fund tickers.
        try:
            from investment_engine.research.market_data import is_etf_like as _is_etf
            if _is_etf(asset):
                return _disp_of(asset), "no_data"
        except Exception:
            pass
        explicit_yahoo = (asset or {}).get("yahoo_symbol")
        ref = explicit_yahoo or (asset or {}).get("ticker") or _symbol(asset)
        try:
            disp = _td_e(ref)
        except Exception:
            disp = str(ref or "UNKNOWN").strip().upper()
        try:
            yahoo = explicit_yahoo or _ty_e(ref, disp, None)
            if not yahoo or not is_earnings_supported(yahoo):
                return disp, "unavailable"
            date = recent_earnings_date(yahoo)
            return disp, date if date else "no_data"
        except Exception as e:
            return disp, f"error: {str(e)[:50]}"

    def _disp_of(asset) -> str:
        ref = (asset or {}).get("yahoo_symbol") or (asset or {}).get("ticker") or _symbol(asset)
        try:
            return _td_e(ref)
        except Exception:
            return str(ref or "UNKNOWN").strip().upper()

    earnings: dict[str, str] = {}
    # Limit to 15 assets; keys are DISPLAY tickers.
    priority_assets = assets[:15]

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_one, asset): asset for asset in priority_assets}
        for future in as_completed(futures):
            try:
                sym, date = future.result(timeout=timeout_per_symbol)
                earnings[sym] = date
            except FuturesTimeoutError:
                asset = futures[future]
                earnings[_disp_of(asset)] = "timeout"
            except Exception as e:
                asset = futures[future]
                earnings[_disp_of(asset)] = f"error: {str(e)[:50]}"

    return earnings


def _merge_calendar_earnings(earnings: dict, events, need: list,
                             to_display) -> int:
    """Merge Playwright calendar events into failed Yahoo earnings slots.

    Pure helper (testable): only fills displays in `need` with a dated event.
    Returns the number of filled slots.
    """
    filled = 0
    try:
        need_set = set(need or [])
        for _ev in (events or [])[:80]:
            try:
                _d = to_display(str(getattr(_ev, "symbol", "")))
            except Exception:
                continue
            if _d in need_set and getattr(_ev, "date", ""):
                earnings[_d] = str(_ev.date)[:10]
                filled += 1
    except Exception:
        pass
    return filled


def _fill_earnings_layer2(earnings: dict, need: list, *, fetch_calendar,
                          fetch_yahoo_date, to_display, to_yahoo,
                          sleep=None) -> int:
    """Layer-2 earnings fill: Playwright calendar with retry, yfinance fallback.

    Tries the calendar up to 3x (2s/4s backoff), merges dated events into
    `need` slots; on total failure falls back to per-symbol Yahoo earnings
    dates. Returns filled slots. Never raises.
    """
    from types import SimpleNamespace as _NS
    _sleep = sleep if callable(sleep) else (lambda s: __import__("time").sleep(s))
    try:
        _events = None
        for _attempt in range(3):
            try:
                _events = fetch_calendar()
                break
            except Exception as exc:
                if _attempt < 2:
                    logger.warning("Earnings layer 2 attempt %d/3 failed: %s. Retrying...",
                                   _attempt + 1, exc)
                    try:
                        _sleep(2.0 * (2 ** _attempt))
                    except Exception:
                        pass
                else:
                    logger.warning("Earnings layer 2 calendar failed after 3 attempts: %s", exc)
        if _events:
            return _merge_calendar_earnings(earnings, _events, need, to_display)
    except Exception as exc:
        logger.debug("Earnings layer 2 calendar skipped: %s", exc)
    try:
        _fb = []
        for _disp in need or []:
            try:
                _y = to_yahoo(_disp) if callable(to_yahoo) else None
                if not _y:
                    continue
                _d = fetch_yahoo_date(_y)
                if _d:
                    _fb.append(_NS(symbol=_disp, date=str(_d)[:10]))
            except Exception:
                continue
        if _fb:
            return _merge_calendar_earnings(earnings, _fb, need, to_display)
    except Exception as exc:
        logger.debug("Earnings layer 2 yfinance fallback skipped: %s", exc)
    return 0


def _analyst_consensus_bundle(by_symbol: dict) -> dict:
    """Bundle analyst snapshots with as_of date and parsed analyst count.

    result["analyst_consensus"] contract consumed by report_structure.
    Counts parsed from "period: buy=B, hold=H, sell=S" strings; when a
    string is unparseable the count stays "unknown" (never invented).
    """
    import re as _re_ac
    total, parsed_any = 0, False
    for snap in (by_symbol or {}).values():
        try:
            nums = [int(n) for n in _re_ac.findall(r"(?:buy|hold|sell)=(\d+)", str(snap), flags=_re_ac.IGNORECASE)]
            if nums:
                total += sum(nums)
                parsed_any = True
        except (TypeError, ValueError):
            continue
    return {
        "summary": ("; ".join(f"{k}: {v}" for k, v in list((by_symbol or {}).items())[:5])
                    or "No consensus snapshots this run."),
        "by_symbol": dict(by_symbol or {}),
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "analyst_count": total if parsed_any else "unknown",
    }


def _tech_summary_line(display: str, ind: dict | None) -> str:
    """One-line technical summary for LLM prompts (legacy-style per-asset block)."""
    if not ind:
        return f"{display}: no technical data"
    def _f(key, fmt="{:.2f}"):
        v = ind.get(key)
        try:
            return fmt.format(float(v)) if v is not None else "N/A"
        except (TypeError, ValueError):
            return "N/A"
    line = (
        f"{display}: Price={_f('price')} | RSI={_f('RSI_14', '{:.1f}')} | "
        f"SMA20={_f('SMA_20')} | SMA50={_f('SMA_50')} | MACD={_f('MACD', '{:.4f}')} | "
        f"Support={_f('Support')} | Resistance={_f('Resistance')}"
    )
    # TradingView sweep readings (distinct keys; shown only, never merged
    # into Yahoo numerics or broker values).
    tv_bits = []
    if isinstance(ind.get("TV_TECHNICALS_RATING"), str) and ind["TV_TECHNICALS_RATING"]:
        tv_bits.append(f"TV gauge: {ind['TV_TECHNICALS_RATING']}")
    if isinstance(ind.get("TV_ANALYST_RATING"), str) and ind["TV_ANALYST_RATING"]:
        tv_bits.append(f"TV analyst: {ind['TV_ANALYST_RATING']}")
    if tv_bits:
        line += " | " + " | ".join(tv_bits)
    return line


def _fetch_technicals_parallel(symbols: list) -> dict[str, dict]:
    """Fetch technical indicators, keyed by DISPLAY symbol.

    Accepts [(display, yahoo)] pairs (preferred) or plain Yahoo strings
    (backward compatible; keyed as given). Yahoo lookups only — never
    company names.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from investment_engine.research.market_data import fetch_technical_indicators
    pairs: list[tuple[str, str]] = []
    for item in dict.fromkeys(map(lambda x: x if isinstance(x, tuple) else (x, x), symbols or [])):
        disp, yahoo = item
        if yahoo and yahoo != "UNKNOWN":
            pairs.append((disp, yahoo))
    if not pairs:
        return {}
    out: dict[str, dict] = {}
    def _one(pair):
        disp, yahoo = pair
        try:
            from investment_engine.portfolio.symbols import support_state as _ss
            if _ss(yahoo, "market_data") != "SUPPORTED":
                return disp, None
            return disp, fetch_technical_indicators(yahoo, period="3mo", interval="1d")
        except Exception:
            return disp, None
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_one, p): p[0] for p in pairs}
        for f in as_completed(futs):
            try:
                disp, ind = f.result(timeout=60)
                if ind:
                    out[disp] = ind
            except Exception:
                pass
    return out


def _fetch_news_for_extra_tickers(settings_dict: dict, items: list[tuple]) -> dict[str, list[dict]]:
    """Fetch 48h news for extra tickers. items = [(key, yahoo_symbol, name)], limit 2 each."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out: dict[str, list[dict]] = {}
    items = [(k, s, n) for k, s, n in items if s and s != "UNKNOWN"]
    if not items:
        return out
    fetcher = StrictNewsFetcher(
        max_age_hours=settings_dict.get("market_regime", {}).get("news", {}).get("max_age_hours", 48),
        min_relevance=settings_dict.get("market_regime", {}).get("news", {}).get("min_relevance_score", 60),
    )
    def _one(item):
        key, sym, name = item
        try:
            return key, [i.__dict__ for i in fetcher.fetch_for_symbol(sym, name, limit=2)]
        except Exception:
            return key, []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_one, it): it[0] for it in items}
        for f in as_completed(futs):
            try:
                key, entries = f.result(timeout=60)
                if entries:
                    out[key] = entries
            except Exception:
                pass
    return out


def _fetch_earnings_for_symbols(yahoo_by_display: dict[str, str | None]) -> dict[str, str]:
    """Earnings dates keyed by DISPLAY symbol.

    Input maps display -> Yahoo ticker (or None when unsupported). Unsupported
    instruments resolve to 'unavailable' without any yfinance call; failures
    resolve to 'no_data'. Never queries company names.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from investment_engine.research.market_data import recent_earnings_date
    items = list((yahoo_by_display or {}).items())
    if not items:
        return {}
    out: dict[str, str] = {}
    for disp, yahoo in items:
        if not yahoo:
            out[disp] = "unavailable"
    todo = []
    try:
        from investment_engine.portfolio.symbols import support_state as _ss2
        for disp, yahoo in items:
            if not yahoo or disp in out:
                continue
            if _ss2(yahoo, "earnings") != "SUPPORTED":
                out[disp] = "unavailable"
            else:
                todo.append((disp, yahoo))
    except ImportError:
        todo = [(disp, yahoo) for disp, yahoo in items if yahoo and disp not in out]
    if not todo:
        return out
    def _one(pair):
        disp, yahoo = pair
        try:
            d = recent_earnings_date(yahoo)
            return disp, d if d else "no_data"
        except Exception:
            return disp, "no_data"
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_one, p): p[0] for p in todo}
        for f in as_completed(futs):
            try:
                disp, date = f.result(timeout=20)
                out[disp] = date
            except Exception:
                pass
    return out

# Public aliases for cross-module use (private names remain the
# implementation detail and stay available for in-module calls).
fetch_earnings_fast = _fetch_earnings_fast
merge_calendar_earnings = _merge_calendar_earnings
fill_earnings_layer2 = _fill_earnings_layer2
analyst_consensus_bundle = _analyst_consensus_bundle
tech_summary_line = _tech_summary_line
fetch_technicals_parallel = _fetch_technicals_parallel
fetch_news_for_extra_tickers = _fetch_news_for_extra_tickers
fetch_earnings_for_symbols = _fetch_earnings_for_symbols

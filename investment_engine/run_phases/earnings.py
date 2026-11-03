"""Earnings fast path plus the Playwright calendar fallback layer."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from investment_engine.config.settings import EngineSettings
from investment_engine.research.market_data import recent_earnings_date

logger = logging.getLogger(__name__)


@dataclass
class EarningsPhase:
    """Earnings map plus provenance for the slow calendar layer."""

    earnings: dict[str, Any] = field(default_factory=dict)
    dated_before_l2: set[str] = field(default_factory=set)
    calendar_sourced: set[str] = field(default_factory=set)
    playwright_earnings: int = 0


def fetch_earnings_phase(
    *,
    settings: EngineSettings,
    assets: list[dict[str, Any]],
    all_active_assets: list[dict[str, Any]],
) -> EarningsPhase:
    """Fetch Yahoo earnings first, then fill gaps from the calendar layer."""
    from investment_engine.research.earnings_fetch import (
    fetch_earnings_fast,
    fill_earnings_layer2,
)

    earnings = fetch_earnings_fast(all_active_assets)
    dated_before_l2 = {
        str(display)
        for display, value in (earnings or {}).items()
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value)
    }
    calendar_sourced: set[str] = set()
    playwright_earnings = 0

    try:
        from investment_engine.portfolio.symbols import to_display_symbol
        from investment_engine.portfolio.symbols import to_yahoo_symbol
        from investment_engine.research import web_researcher
        from investment_engine.research.market_data import is_etf_like

        if getattr(settings, "use_playwright_fallback", True):
            etf_displays: set[str] = set()
            for asset in assets or []:
                if isinstance(asset, dict) and is_etf_like(asset):
                    for ref in (asset.get("broker_symbol"), asset.get("yahoo_symbol")):
                        try:
                            if ref:
                                etf_displays.add(to_display_symbol(str(ref)))
                        except Exception:
                            continue
            needed = [
                display
                for display, value in (earnings or {}).items()
                if display not in etf_displays
                and (
                    str(value).startswith(("timeout", "error"))
                    or value in ("no_data", "unavailable")
                )
            ][:15]
            if needed:
                import time as _time

                yahoo_by_display: dict[str, str] = {}
                for asset in assets or []:
                    if not isinstance(asset, dict):
                        continue
                    try:
                        ref = str(asset.get("broker_symbol") or asset.get("yahoo_symbol") or "")
                        if not ref:
                            continue
                        display = to_display_symbol(ref)
                        yahoo = str(asset.get("yahoo_symbol") or "")
                        if not yahoo:
                            try:
                                yahoo = str(to_yahoo_symbol(ref, display, None) or "")
                            except Exception:
                                yahoo = ""
                        if display and yahoo:
                            yahoo_by_display.setdefault(display, yahoo)
                    except Exception:
                        continue
                playwright_earnings += fill_earnings_layer2(
                    earnings,
                    needed,
                    fetch_calendar=lambda: (web_researcher.fetch_all_earnings_sync(7) or []),
                    fetch_yahoo_date=recent_earnings_date,
                    to_display=to_display_symbol,
                    to_yahoo=yahoo_by_display.get,
                    sleep=_time.sleep,
                )
                calendar_sourced = {
                    str(display)
                    for display, value in (earnings or {}).items()
                    if isinstance(value, str)
                    and re.match(r"^\d{4}-\d{2}-\d{2}", value)
                    and str(display) not in dated_before_l2
                }
    except Exception as exc:
        logger.debug("Earnings layer 2 skipped: %s: %s", type(exc).__name__, exc)

    return EarningsPhase(
        earnings=earnings,
        dated_before_l2=dated_before_l2,
        calendar_sourced=calendar_sourced,
        playwright_earnings=playwright_earnings,
    )

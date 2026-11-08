"""Build the day-trader universe: S&P 500 + portfolio + EU/China extras."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from .config import DayTraderConfig

logger = logging.getLogger(__name__)


def _safe_display(symbol: str) -> str:
    try:
        from investment_engine.portfolio.symbols import to_display_symbol
        return to_display_symbol(symbol)
    except Exception:
        return str(symbol).split("_")[0].upper()


def _safe_yahoo(symbol: str, display: str) -> str | None:
    try:
        from investment_engine.portfolio.symbols import to_yahoo_symbol
        return to_yahoo_symbol(symbol, display)
    except Exception:
        return None


def build_universe_symbols(
    config: DayTraderConfig,
    portfolio_symbols: Iterable[str] | None = None,
) -> list[str]:
    """Return an ordered, deduplicated list of Yahoo symbols for the scanner.

    Priority: config extras (ETFs/EU/China), portfolio holdings, then S&P 500.
    The cap is ``config.universe.max_symbols``.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def add(sym: Any) -> None:
        if sym is None:
            return
        s = str(sym).strip()
        if not s:
            return
        key = s.upper()
        if key in seen:
            return
        seen.add(key)
        ordered.append(s)

    # 1) explicit extras (ETFs, EU, China, etc.)
    for sym in config.universe.extra_symbols or []:
        add(sym)

    # 2) portfolio holdings (converted to Yahoo symbols)
    if config.universe.include_portfolio and portfolio_symbols:
        for sym in portfolio_symbols:
            if not sym:
                continue
            display = _safe_display(str(sym))
            yahoo = _safe_yahoo(str(sym), display)
            add(yahoo or display)

    # 3) S&P 500 / Nasdaq-100
    if config.universe.include_sp500 or config.universe.include_nasdaq100:
        try:
            from investment_engine.discovery.universe import build_universe
            for sym in build_universe(
                include_sp500=config.universe.include_sp500,
                include_nasdaq100=config.universe.include_nasdaq100,
            ):
                add(sym)
        except Exception as exc:
            logger.warning("Universe fetch failed: %s", type(exc).__name__)

    return ordered[: max(1, int(config.universe.max_symbols or 500))]


def write_universe_file(symbols: Iterable[str], path: str | Path) -> Path:
    """Write the scanner's ``SYMBOL|Name`` universe format."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{s}|{s}" for s in symbols]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path

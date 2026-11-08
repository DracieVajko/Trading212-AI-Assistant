"""earnings_calendar.py — Earnings calendar for discovery and alerting.

Fetches upcoming earnings dates from yfinance for a list of tickers,
caches results, and provides a simple interface for filtering upcoming
earnings within a time window.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


class EarningsCalendar:
    """Earnings calendar fetcher with per-symbol caching.

    Uses yfinance to fetch upcoming earnings dates. Results are cached
    per-symbol to avoid repeated network calls during a single run.
    """

    def __init__(self, cache_ttl_s: float = 86400.0):
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl = cache_ttl_s
        self._cache_ts: float = 0.0

    def _fetch(self, ticker: str) -> list[dict[str, Any]] | None:
        """Fetch earnings dates for a single ticker from yfinance."""
        import yfinance as yf

        try:
            ticker_obj = yf.Ticker(ticker)
            earnings_dates = ticker_obj.earnings_dates
            if earnings_dates is None or earnings_dates.empty:
                return []
            # earnings_dates returns a DataFrame with earnings date column
            results = []
            for idx, row in earnings_dates.iterrows():
                results.append({
                    "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                    "eps_estimate": row.get("EPS Estimate"),
                    "eps_actual": row.get("Reported EPS"),
                })
            return results
        except Exception as exc:
            logger.debug("earnings: %s fetch failed: %s", ticker, type(exc).__name__)
            return None

    def get_earnings(self, ticker: str) -> list[dict[str, Any]] | None:
        """Get earnings dates for a ticker, using cache when available."""
        ticker = str(ticker).upper().strip()
        now = time.time()

        # Check cache
        if ticker in self._cache and (now - self._cache_ts) < self._cache_ttl:
            return self._cache[ticker]

        # Fetch fresh
        result = self._fetch(ticker)
        self._cache[ticker] = result
        self._cache_ts = now
        return result

    def get_upcoming_earnings(
        self,
        tickers: list[str],
        within_days: int = 7,
    ) -> dict[str, list[dict[str, Any]]]:
        """Get upcoming earnings for multiple tickers within a time window.

        Args:
            tickers: List of ticker symbols.
            within_days: Only return earnings within this many days.

        Returns:
            Dict mapping ticker -> list of upcoming earnings events.
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=within_days)
        result: dict[str, list[dict[str, Any]]] = {}

        for ticker in tickers:
            earnings = self.get_earnings(ticker)
            if not earnings:
                continue
            upcoming = []
            for e in earnings:
                try:
                    e_date = datetime.fromisoformat(e["date"]).replace(tzinfo=timezone.utc)
                    if now <= e_date <= cutoff:
                        upcoming.append(e)
                except (ValueError, TypeError):
                    continue
            if upcoming:
                result[ticker] = upcoming

        return result

    def clear_cache(self) -> None:
        """Clear the earnings cache."""
        self._cache.clear()
        self._cache_ts = 0.0


# Singleton instance for convenience
_earnings_calendar: EarningsCalendar | None = None


def get_earnings_calendar() -> EarningsCalendar:
    """Get the singleton earnings calendar instance."""
    global _earnings_calendar
    if _earnings_calendar is None:
        _earnings_calendar = EarningsCalendar()
    return _earnings_calendar


def get_upcoming_earnings(
    tickers: list[str],
    within_days: int = 7,
) -> dict[str, list[dict[str, Any]]]:
    """Convenience function to get upcoming earnings for tickers."""
    return get_earnings_calendar().get_upcoming_earnings(tickers, within_days)

"""investment_engine/discovery — Discovery Engine for finding new opportunities.

Modules:
- universe.py: Build stock universe (S&P 500, Nasdaq-100, etc.)
- screener.py: Technical screening (MACD, Bollinger, channel, quality)
- signals_ext.py: Extra signals (SMA cross, Bollinger, channel, quality, hype)
- trackers.py: External signal trackers (Cramer inverse, 13F, insider clusters)
- discovery.py: Score candidates, run discovery
"""
from __future__ import annotations

from .universe import build_universe
from .screener import run_screener
from .discovery import run_discovery, score_candidate
from .discovery_report import write_discovery_report

__all__ = ["build_universe", "run_screener", "run_discovery", "score_candidate", "write_discovery_report"]

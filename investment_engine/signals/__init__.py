"""Signal recording and evaluation (backtesting foundation)."""

from __future__ import annotations

from .signal_recorder import get_signals, record_portfolio_signals, record_signal

__all__ = ["get_signals", "record_portfolio_signals", "record_signal"]

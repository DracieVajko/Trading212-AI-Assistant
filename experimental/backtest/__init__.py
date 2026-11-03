"""Isolated experimental backtest module - advisory research only.

No broker API calls, no live data, no secrets, no automated trading.
All inputs are local CSV/parquet OHLCV with explicit EUR normalization.

This package is not integrated with the production pipeline. See
``experimental/README.md`` for its status, test command, and migration rule.
"""

from experimental.backtest.validate import ValidationError, ValidationReport, validate_dataframe

__all__ = ["ValidationError", "ValidationReport", "validate_dataframe"]

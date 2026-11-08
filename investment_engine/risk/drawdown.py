"""drawdown.py — Drawdown analysis for portfolio risk management.

Computes drawdown series, maximum drawdown, drawdown duration, and related
risk metrics from equity curve or returns data.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_drawdown_series(equity_curve: pd.Series) -> pd.Series:
    """Compute drawdown series from equity curve.

    Args:
        equity_curve: Series of portfolio values over time.

    Returns:
        Series of drawdown values (negative values, 0 at peaks).
    """
    if equity_curve is None or len(equity_curve) == 0:
        return pd.Series(dtype=float)

    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return drawdown.fillna(0.0)


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """Compute maximum drawdown from equity curve.

    Args:
        equity_curve: Series of portfolio values over time.

    Returns:
        Maximum drawdown as positive value (e.g., 0.15 for 15% drawdown).
    """
    if equity_curve is None or len(equity_curve) == 0:
        return 0.0

    drawdown = compute_drawdown_series(equity_curve)
    return float(drawdown.min() * -1)  # Return as positive value


def compute_max_drawdown_duration(equity_curve: pd.Series) -> int:
    """Compute maximum drawdown duration in days.

    Args:
        equity_curve: Series of portfolio values over time.

    Returns:
        Maximum number of consecutive days in drawdown.
    """
    if equity_curve is None or len(equity_curve) == 0:
        return 0

    drawdown = compute_drawdown_series(equity_curve)
    in_drawdown = drawdown < 0

    max_duration = 0
    current_duration = 0
    for is_dd in in_drawdown:
        if is_dd:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0

    return int(max_duration)


def compute_recovery_time(equity_curve: pd.Series) -> int:
    """Compute recovery time from maximum drawdown.

    Args:
        equity_curve: Series of portfolio values over time.

    Returns:
        Number of days to recover from max drawdown, or -1 if not recovered.
    """
    if equity_curve is None or len(equity_curve) == 0:
        return -1

    drawdown = compute_drawdown_series(equity_curve)
    max_dd_idx = drawdown.idxmin()

    if pd.isna(max_dd_idx) or drawdown.loc[max_dd_idx] >= 0:
        return 0  # No drawdown

    # Find recovery point (when equity exceeds pre-drawdown peak)
    peak_value = equity_curve.loc[: max_dd_idx].max()
    recovery_idx = equity_curve.loc[max_dd_idx:][
        equity_curve.loc[max_dd_idx:] >= peak_value
    ].index

    if len(recovery_idx) == 0:
        return -1  # Not yet recovered

    return int((recovery_idx[0] - max_dd_idx).days)


def compute_calmar_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
) -> float:
    """Compute Calmar ratio (annualized return / max drawdown).

    Args:
        returns: Series of returns.
        risk_free_rate: Annual risk-free rate.
        trading_days_per_year: Number of trading days per year.

    Returns:
        Calmar ratio.
    """
    if len(returns) == 0:
        return 0.0

    annualized_return = float(returns.mean() * trading_days_per_year)

    # Reconstruct equity curve for drawdown
    equity_curve = (1 + returns).cumprod()
    max_drawdown = abs(float(compute_drawdown_series(equity_curve).min()))

    if max_drawdown == 0:
        return float("inf") if annualized_return > 0 else 0.0

    return float(annualized_return / abs(max_drawdown))

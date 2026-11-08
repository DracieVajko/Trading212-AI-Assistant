"""sharpe_sortino.py — Sharpe and Sortino ratio calculations.

Provides risk-adjusted return metrics for portfolio performance evaluation.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
) -> float:
    """Compute Sharpe ratio.

    Args:
        returns: Series of returns.
        risk_free_rate: Annual risk-free rate.
        trading_days_per_year: Number of trading days per year.

    Returns:
        Sharpe ratio.
    """
    if returns.empty or len(returns) < 2:
        return 0.0

    excess_returns = returns - risk_free_rate / trading_days_per_year
    mean_return = excess_returns.mean()
    std_return = returns.std()

    if std_return == 0:
        return 0.0

    return float(mean_return / std_return * np.sqrt(trading_days_per_year))


def compute_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
    target_return: float = 0.0,
) -> float:
    """Compute Sortino ratio.

    Args:
        returns: Series of returns.
        risk_free_rate: Annual risk-free rate.
        trading_days_per_year: Number of trading days per year.
        target_return: Target return for downside deviation (default 0).

    Returns:
        Sortino ratio.
    """
    if returns.empty or len(returns) < 2:
        return 0.0

    excess_returns = returns - risk_free_rate / trading_days_per_year
    downside_returns = returns[returns < target_return]

    if len(downside_returns) == 0:
        return float("inf") if excess_returns.mean() > 0 else 0.0

    downside_std = downside_returns.std()

    if downside_std == 0:
        return 0.0

    return float(
        excess_returns.mean() / downside_std * np.sqrt(trading_days_per_year)
    )


def compute_information_ratio(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    trading_days_per_year: int = 252,
) -> float:
    """Compute Information Ratio.

    Args:
        returns: Series of portfolio returns.
        benchmark_returns: Series of benchmark returns.
        trading_days_per_year: Number of trading days per year.

    Returns:
        Information ratio.
    """
    if returns.empty or benchmark_returns.empty or len(returns) < 2:
        return 0.0

    # Align returns
    combined = pd.concat([returns, benchmark_returns], axis=1).dropna()
    if len(combined) < 2:
        return 0.0

    active_returns = combined.iloc[:, 0] - combined.iloc[:, 1]
    tracking_error = active_returns.std()

    if tracking_error == 0:
        return 0.0

    return float(
        active_returns.mean() / tracking_error * np.sqrt(trading_days_per_year)
    )


def compute_treynor_ratio(
    returns: pd.Series,
    market_returns: pd.Series,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
) -> float:
    """Compute Treynor ratio.

    Args:
        returns: Series of portfolio returns.
        market_returns: Series of benchmark/market returns.
        risk_free_rate: Annual risk-free rate.
        trading_days_per_year: Number of trading days per year.

    Returns:
        Treynor ratio.
    """
    if returns.empty or market_returns.empty or len(returns) < 2:
        return 0.0

    combined = pd.concat([returns, market_returns], axis=1).dropna()
    if len(combined) < 2:
        return 0.0

    portfolio_returns = combined.iloc[:, 0]
    market_returns_aligned = combined.iloc[:, 1]

    # Calculate beta
    covariance = portfolio_returns.cov(market_returns)
    market_variance = market_returns.var()

    if market_variance == 0:
        return 0.0

    beta = covariance / market_variance

    excess_return = portfolio_returns.mean() - risk_free_rate / trading_days_per_year
    if excess_return == 0:
        return 0.0

    return float(excess_return / beta)

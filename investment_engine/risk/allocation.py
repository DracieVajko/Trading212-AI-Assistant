"""allocation.py — Portfolio allocation engine.

Provides various portfolio allocation methods:
- Equal weight
- Risk parity
- Minimum variance
- Maximum Sharpe ratio
- Market cap weighted
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def equal_weight_allocation(
    tickers: list[str],
) -> dict[str, float]:
    """Equal weight allocation.

    Args:
        tickers: List of ticker symbols.

    Returns:
        Dict of ticker -> equal weight.
    """
    if not tickers:
        return {}
    weight = 1.0 / len(tickers)
    return {ticker: weight for ticker in tickers}


def risk_parity_allocation(
    returns: pd.DataFrame,
) -> dict[str, float]:
    """Risk parity allocation - equal risk contribution from each asset.

    Args:
        returns: DataFrame of returns with datetime index and ticker columns.

    Returns:
        Dict of ticker -> weight.
    """
    from .risk_parity import compute_risk_parity_weights

    return compute_risk_parity_weights(returns)


def min_variance_allocation(
    returns: pd.DataFrame,
    no_short: bool = True,
) -> dict[str, float]:
    """Minimum variance portfolio allocation.

    Args:
        returns: DataFrame of returns.
        no_short: If True, constrain weights to be non-negative.

    Returns:
        Dict of ticker -> weight.
    """
    if returns is None or returns.empty or len(returns.columns) < 1:
        return {}

    cov_matrix = returns.cov()
    n_assets = len(cov_matrix.columns)

    # Initial guess: equal weights
    initial_weights = np.ones(n_assets) / n_assets

    # Objective: minimize portfolio variance
    def objective(weights: np.ndarray) -> float:
        return float(weights @ cov_matrix.values @ weights)

    # Constraints: weights sum to 1
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1}

    # Bounds: non-negative if no_short
    bounds = [(0, 1) if no_short else (-1, 1) for _ in range(n_assets)]

    from scipy.optimize import minimize

    result = minimize(
        objective,
        initial_weights,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    if not result.success:
        logger.warning(f"Min variance optimization failed: {result.message}")
        return equal_weight_allocation(list(cov_matrix.columns))

    return {ticker: float(w) for ticker, w in zip(cov_matrix.columns, result.x)}


def max_sharpe_allocation(
    returns: pd.DataFrame,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
    no_short: bool = True,
) -> dict[str, float]:
    """Maximum Sharpe ratio allocation.

    Args:
        returns: DataFrame of returns.
        risk_free_rate: Annual risk-free rate.
        trading_days_per_year: Number of trading days per year.
        no_short: If True, constrain weights to be non-negative.

    Returns:
        Dict of ticker -> weight.
    """
    if returns is None or returns.empty or len(returns.columns) < 1:
        return {}

    mean_returns = returns.mean() * trading_days_per_year
    cov_matrix = returns.cov() * trading_days_per_year
    n_assets = len(cov_matrix.columns)

    # Initial guess: equal weights
    initial_weights = np.ones(n_assets) / n_assets

    # Objective: negative Sharpe ratio (minimize negative Sharpe = maximize Sharpe)
    def objective(weights: np.ndarray) -> float:
        portfolio_return = float(np.sum(weights * mean_returns))
        portfolio_vol = float(
            np.sqrt(weights @ cov_matrix.values @ weights)
        )
        if portfolio_vol == 0:
            return 0.0
        return -(portfolio_return - risk_free_rate) / portfolio_vol

    # Constraints: weights sum to 1
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1}

    # Bounds: non-negative if no_short
    bounds = [(0, 1) if no_short else (-1, 1) for _ in range(n_assets)]

    from scipy.optimize import minimize

    result = minimize(
        objective,
        initial_weights,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    if not result.success:
        logger.warning(f"Max Sharpe optimization failed: {result.message}")
        return equal_weight_allocation(list(cov_matrix.columns))

    return {ticker: float(w) for ticker, w in zip(cov_matrix.columns, result.x)}


def risk_parity_allocation(
    returns: pd.DataFrame,
) -> dict[str, float]:
    """Risk parity allocation - equal risk contribution from each asset.

    Args:
        returns: DataFrame of returns with datetime index and ticker columns.

    Returns:
        Dict of ticker -> weight.
    """
    from investment_engine.risk.risk_parity import compute_risk_parity_weights

    return compute_risk_parity_weights(returns)


def equal_risk_contribution_allocation(
    returns: pd.DataFrame,
) -> dict[str, float]:
    """Alias for risk_parity_allocation."""
    return risk_parity_allocation(returns)


def compute_optimal_portfolio(
    returns: pd.DataFrame,
    method: str = "max_sharpe",
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
    **kwargs: Any,
) -> dict[str, float]:
    """Compute optimal portfolio allocation.

    Args:
        returns: DataFrame of returns.
        method: Allocation method ('equal', 'risk_parity', 'min_variance', 'max_sharpe').
        risk_free_rate: Annual risk-free rate.
        trading_days_per_year: Number of trading days per year.
        **kwargs: Additional arguments passed to specific allocation method.

    Returns:
        Dict of ticker -> weight.
    """
    if returns is None or returns.empty or len(returns.columns) == 0:
        return {}

    if method == "equal":
        return equal_weight_allocation(list(returns.columns))
    elif method == "risk_parity":
        return risk_parity_allocation(returns)
    elif method == "min_variance":
        return min_variance_allocation(returns)
    elif method == "max_sharpe":
        return max_sharpe_allocation(returns, risk_free_rate, trading_days_per_year)
    else:
        raise ValueError(f"Unknown allocation method: {method}")


def compute_portfolio_stats(
    weights: dict[str, float],
    returns: pd.DataFrame,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
) -> dict[str, float]:
    """Compute portfolio statistics for given weights and returns.

    Args:
        weights: Dict of ticker -> weight.
        returns: DataFrame of returns.
        risk_free_rate: Annual risk-free rate.
        trading_days_per_year: Number of trading days per year.

    Returns:
        Dict with portfolio statistics.
    """
    from investment_engine.risk.sharpe_sortino import compute_sharpe_ratio, compute_sortino_ratio

    # Align weights with returns columns
    weights_array = np.array([weights.get(col, 0.0) for col in returns.columns])

    # Portfolio returns
    portfolio_returns = (returns * weights_array).sum(axis=1)

    total_return = float((1 + portfolio_returns).prod() - 1)
    years = len(returns) / trading_days_per_year
    annualized_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 else 0.0

    sharpe_ratio = compute_sharpe_ratio(portfolio_returns, risk_free_rate, trading_days_per_year)
    sortino_ratio = compute_sortino_ratio(portfolio_returns, risk_free_rate, trading_days_per_year)

    # Max drawdown
    cumulative = (1 + portfolio_returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = float(drawdown.min())

    return {
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "sharpe_ratio": float(sharpe_ratio),
        "sortino_ratio": float(sortino_ratio),
        "max_drawdown": float(max_drawdown),
    }

"""correlation.py — Rolling correlation and covariance analysis.

Provides rolling correlation and covariance matrix computation for portfolio
risk analysis. Helps identify concentration risks and diversification benefits.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_correlation_matrix(
    returns_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute correlation matrix from returns DataFrame.

    Args:
        returns: DataFrame with datetime index and ticker columns of returns.

    Returns:
        Correlation matrix DataFrame.
    """
    if returns.empty or len(returns.columns) < 2:
        return pd.DataFrame()
    return returns.corr()


def compute_covariance_matrix(
    returns_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute covariance matrix from returns DataFrame.

    Args:
        returns_df: DataFrame with datetime index and ticker columns of returns.

    Returns:
        Covariance matrix DataFrame.
    """
    if returns_df.empty or len(returns_df.columns) < 2:
        return pd.DataFrame()
    return returns_df.cov()


def compute_portfolio_variance(
    weights: dict[str, float],
    cov_matrix: pd.DataFrame,
) -> float:
    """Compute portfolio variance from weights and covariance matrix.

    Args:
        weights: Dict of ticker -> weight.
        cov_matrix: Covariance matrix DataFrame.

    Returns:
        Portfolio variance.
    """
    if not weights or cov_matrix.empty:
        return 0.0

    w = np.array([weights.get(t, 0.0) for t in cov_matrix.index])
    cov = cov_matrix.values
    return float(w @ cov @ w)


def compute_portfolio_volatility(
    weights: dict[str, float],
    cov_matrix: pd.DataFrame,
) -> float:
    """Compute portfolio volatility from weights and covariance matrix.

    Args:
        weights: Dict of ticker -> weight.
        cov_matrix: Covariance matrix DataFrame.

    Returns:
        Portfolio volatility (annualized).
    """
    var = compute_portfolio_variance(weights, cov_matrix)
    return float(np.sqrt(var) * np.sqrt(252))


def compute_correlation_stats(
    corr_matrix: pd.DataFrame,
) -> dict[str, float]:
    """Compute correlation statistics from correlation matrix.

    Args:
        corr_matrix: Correlation matrix DataFrame.

    Returns:
        Dict with average correlation, max correlation, min correlation.
    """
    if corr_matrix.empty or len(corr_matrix) < 2:
        return {
            "avg_correlation": 0.0,
            "max_correlation": 0.0,
            "min_correlation": 0.0,
            "n_assets": 0,
        }

    # Exclude diagonal (self-correlation = 1.0)
    mask = ~np.eye(corr_matrix.shape[0], dtype=bool)
    off_diag = corr_matrix.values[mask]

    return {
        "avg_correlation": float(np.mean(off_diag)),
        "max_correlation": float(np.max(off_diag)),
        "min_correlation": float(np.min(off_diag)),
        "n_assets": len(corr_matrix.columns),
    }


def compute_concentration_from_correlation(
    corr_matrix: pd.DataFrame,
) -> float:
    """Compute concentration risk from correlation matrix.

    High average correlation indicates high concentration risk.
    Returns a score from 0 (diversified) to 1 (highly concentrated).
    """
    if corr_matrix.empty or len(corr_matrix) < 2:
        return 0.0

    mask = ~np.eye(corr_matrix.shape[0], dtype=bool)
    off_diag = corr_matrix.values[mask]
    avg_corr = float(np.mean(off_diag))

    # Normalize: correlation of 1 = max concentration, 0 = perfectly diversified
    return max(0.0, min(1.0, avg_corr))


def compute_diversification_score(
    weights: dict[str, float],
    corr_matrix: pd.DataFrame | None = None,
) -> dict[str, float]:
    """Compute diversification score combining concentration and correlation.

    Args:
        weights: Dict of ticker -> weight.
        corr_matrix: Optional correlation matrix.

    Returns:
        Dict with diversification score (0-1, higher is better diversified).
    """
    n_assets = len(weights)
    if n_assets == 0:
        return {"diversification_score": 0.0, "n_assets": 0}

    # Equal weight would be 1/n
    equal_weight = 1.0 / n_assets
    weights_array = np.array([weights.get(t, 0.0) for t in weights.keys()])

    # Concentration component (lower HHI = more diversified)
    hhi = float(np.sum(weights_array ** 2))
    max_hhi = 1.0  # All in one position
    min_hhi = 1.0 / n_assets  # Perfectly equal
    concentration_score = 1.0 - (hhi - min_hhi) / (max_hhi - min_hhi) if max_hhi > min_hhi else 1.0

    # Correlation component (lower avg correlation = more diversified)
    corr_score = 1.0
    if corr_matrix is not None and len(corr_matrix) > 1:
        mask = ~np.eye(corr_matrix.shape[0], dtype=bool)
        off_diag = corr_matrix.values[mask]
        avg_corr = float(np.mean(off_diag))
        corr_score = max(0.0, 1.0 - avg_corr)

    # Combine: 70% concentration, 30% correlation
    div_score = 0.7 * concentration_score + 0.3 * corr_score

    return {
        "diversification_score": float(div_score),
        "concentration_score": float(concentration_score),
        "correlation_score": float(corr_score),
        "n_assets": n_assets,
        "hhi": float(hhi),
    }


def compute_var(
    returns: pd.Series,
    confidence_level: float = 0.95,
) -> float:
    """Compute Value at Risk (VaR) at given confidence level.

    Args:
        returns: Series of returns.
        confidence_level: Confidence level (e.g., 0.95 for 95% VaR).

    Returns:
        VaR value (positive number representing potential loss).
    """
    if returns.empty or len(returns) < 2:
        return 0.0
    return float(-np.percentile(returns, (1 - confidence_level) * 100))


def compute_cvar(
    returns: pd.Series,
    confidence_level: float = 0.95,
) -> float:
    """Compute Conditional Value at Risk (CVaR / Expected Shortfall).

    Args:
        returns: Series of returns.
        confidence_level: Confidence level (e.g., 0.95 for 95% CVaR).

    Returns:
        CVaR value (positive number representing expected loss in tail).
    """
    if returns.empty or len(returns) < 2:
        return 0.0
    var_threshold = np.percentile(returns, (1 - confidence_level) * 100)
    tail_returns = returns[returns <= var_threshold]
    if len(tail_returns) == 0:
        return float(-var_threshold)
    return float(-tail_returns.mean())

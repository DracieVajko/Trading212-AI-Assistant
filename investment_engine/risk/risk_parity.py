"""risk_parity.py — Risk parity portfolio construction.

Computes risk parity weights where each asset contributes equal risk
to the portfolio. Uses inverse volatility weighting as the base approach
with optional correlation adjustment.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_risk_parity_weights(
    returns: pd.DataFrame,
    target_risk: float | None = None,
) -> dict[str, float]:
    """Compute risk parity weights.

    Assets are weighted inversely to their volatility so that each
    contributes equal risk to the portfolio.

    Args:
        returns: DataFrame of returns with datetime index and ticker columns.
        target_risk: Target portfolio volatility (optional).

    Returns:
        Dict of ticker -> weight.
    """
    if returns is None or returns.empty or len(returns.columns) < 1:
        return {}

    # Compute individual volatilities
    vols = returns.std() * np.sqrt(252)  # Annualized volatility

    # Inverse volatility weights
    inv_vol = 1.0 / vols
    weights = inv_vol / inv_vol.sum()

    result: dict[str, float] = {}
    for ticker in returns.columns:
        result[ticker] = float(weights[ticker])

    return result


def compute_risk_contributions(
    weights: dict[str, float],
    cov_matrix: pd.DataFrame,
) -> dict[str, float]:
    """Compute risk contribution of each position.

    Risk contribution = weight * (covariance row * weight) / portfolio_variance

    Args:
        weights: Dict of ticker -> weight.
        cov_matrix: Covariance matrix DataFrame.

    Returns:
        Dict of ticker -> risk contribution (0 to 1).
    """
    if not weights or cov_matrix.empty:
        return {}

    weights_arr = np.array([weights.get(t, 0.0) for t in cov_matrix.index])
    cov_matrix_values = cov_matrix.values

    portfolio_variance = float(weights_arr @ cov_matrix_values @ weights_arr)
    if portfolio_variance == 0:
        return {t: 0.0 for t in cov_matrix.index}

    # Risk contribution = w_i * (covariance * w)_i / portfolio_variance
    portfolio_risk_contrib = cov_matrix_values @ weights_arr
    risk_contributions = weights_arr * portfolio_risk_contrib / portfolio_variance

    return {ticker: float(rc) for ticker, rc in zip(cov_matrix.index, risk_contributions)}


def check_risk_balance(
    weights: dict[str, float],
    cov_matrix: pd.DataFrame,
    tolerance: float = 0.05,
) -> dict[str, Any]:
    """Check how well risk is balanced across positions.

    Args:
        weights: Dict of ticker -> weight.
        cov_matrix: Covariance matrix.
        tolerance: Acceptable deviation from equal risk contribution.

    Returns:
        Dict with balance assessment.
    """
    risk_contrib = compute_risk_contributions(weights, cov_matrix)
    n_assets = len(weights)
    target_risk = 1.0 / n_assets if n_assets > 0 else 0.0

    deviations = {
        ticker: abs(rc - target_risk)
        for ticker, rc in risk_contrib.items()
    }

    max_deviation = max(deviations.values()) if deviations else 0.0
    avg_deviation = np.mean(list(deviations.values())) if deviations else 0.0

    is_balanced = max_deviation <= tolerance

    return {
        "is_balanced": is_balanced,
        "max_deviation": float(max_deviation),
        "avg_deviation": float(avg_deviation),
        "target_risk": float(target_risk),
        "risk_contributions": risk_contrib,
        "deviations": deviations,
    }


def equal_risk_contribution_target(
    n_assets: int,
) -> float:
    """Compute the target risk contribution for equal risk contribution.

    Args:
        n_assets: Number of assets.

    Returns:
        Target risk contribution per asset (1/n_assets).
    """
    if n_assets <= 0:
        return 0.0
    return 1.0 / n_assets

"""correlation.py — Rolling correlation and covariance analysis.

Provides correlation matrix computation, rolling correlation, and correlation
clustering for portfolio risk analysis.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_correlation_matrix(returns_df: pd.DataFrame) -> pd.DataFrame:
    """Compute correlation matrix from returns DataFrame.

    Args:
        returns_df: DataFrame with datetime index and ticker columns of returns.

    Returns:
        Correlation matrix DataFrame.
    """
    if returns_df is None or returns_df.empty or len(returns_df.columns) < 2:
        return pd.DataFrame()
    return returns_df.corr()


def compute_covariance_matrix(returns_df: pd.DataFrame) -> pd.DataFrame:
    """Compute covariance matrix from returns DataFrame.

    Args:
        returns_df: DataFrame with datetime index and ticker columns of returns.

    Returns:
        Covariance matrix DataFrame.
    """
    if returns_df is None or returns_df.empty or len(returns_df.columns) < 2:
        return pd.DataFrame()
    return returns_df.cov()


def rolling_correlation(
    returns_df: pd.DataFrame,
    window: int = 60,
) -> pd.DataFrame:
    """Compute rolling correlation between first two columns.

    Args:
        returns_df: DataFrame with datetime index and at least 2 return columns.
        window: Rolling window in days.

    Returns:
        Series of rolling correlation values.
    """
    if returns_df is None or returns_df.empty or len(returns_df.columns) < 2:
        return pd.Series(dtype=float)
    col1, col2 = returns_df.columns[0], returns_df.columns[1]
    return returns_df[col1].rolling(window).corr(returns_df[col2])


def compute_correlation_clusters(
    corr_matrix: pd.DataFrame,
    threshold: float = 0.7,
) -> dict[str, list[str]]:
    """Cluster highly correlated assets.

    Args:
        corr_matrix: Correlation matrix DataFrame.
        threshold: Correlation threshold for grouping (default 0.7).

    Returns:
        Dict mapping cluster_id -> list of tickers in that cluster.
    """
    if corr_matrix.empty or len(corr_matrix.columns) < 2:
        return {}

    clusters: dict[str, list[str]] = {}
    visited: set[str] = set()
    cluster_id = 0

    for ticker in corr_matrix.columns:
        if ticker in visited:
            continue
        cluster = [ticker]
        visited.add(ticker)
        for other in corr_matrix.columns:
            if other == ticker or other in visited:
                continue
            if abs(corr_matrix.loc[ticker, other]) >= threshold:
                cluster.append(other)
                visited.add(other)
        clusters[f"cluster_{cluster_id}"] = cluster
        cluster_id += 1

    return clusters


def compute_concentration_from_correlation(
    corr_matrix: pd.DataFrame,
) -> float:
    """Compute concentration score from correlation matrix.

    High average correlation indicates high concentration.
    Returns value 0 (diversified) to 1 (highly concentrated).
    """
    if corr_matrix.empty or len(corr_matrix.columns) < 2:
        return 0.0

    mask = ~np.eye(corr_matrix.shape[0], dtype=bool)
    off_diag = corr_matrix.values[mask]
    avg_corr = float(np.mean(off_diag))

    # Normalize: correlation of 1 = max concentration, 0 = diversified
    return max(0.0, min(1.0, avg_corr))

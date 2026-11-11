"""Peer-to-peer benchmarking: relative strength within a sector.

Compares a ticker against its industry peers on margins, cash flow, debt
and valuation. Returns a relative rank and a competitive-advantage score.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _safe(val: Any) -> float | None:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def benchmark_peers(
    target_ticker: str,
    peers: dict[str, dict[str, Any]],
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Benchmark a target ticker against its peers.

    Args:
        target_ticker: the ticker to benchmark.
        peers: dict of ticker -> {metric: value} for all peers (including target).
        metrics: list of metrics to compare. Defaults to common fundamentals.

    Returns:
        dict with relative ranks, peer comparison, and competitive advantage score.
    """
    if metrics is None:
        metrics = ["profit_margin", "operating_margin", "free_cash_flow", "debt_to_equity", "pe_ratio", "roe"]

    if target_ticker not in peers:
        return {"ticker": target_ticker, "error": "target not in peers", "relative_strength": 0.0}

    # Higher is better for these metrics
    higher_better = {"profit_margin", "operating_margin", "free_cash_flow", "roe", "revenue_growth"}
    # Lower is better for these
    lower_better = {"debt_to_equity", "pe_ratio", "pb_ratio", "ev_ebitda"}

    peer_tickers = list(peers.keys())
    n = len(peer_tickers)
    if n < 2:
        return {"ticker": target_ticker, "error": "need at least 2 peers", "relative_strength": 0.0}

    ranks: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        values = {t: _safe(peers[t].get(metric)) for t in peer_tickers}
        valid = {t: v for t, v in values.items() if v is not None}
        if len(valid) < 2:
            ranks[metric] = {"target_rank": None, "target_value": values.get(target_ticker), "peer_avg": None}
            continue

        sorted_tickers = sorted(valid.keys(), key=lambda t: valid[t], reverse=(metric in higher_better))
        # For lower_better, reverse=False (ascending) gives best rank 0
        if metric in lower_better:
            sorted_tickers = sorted(valid.keys(), key=lambda t: valid[t])
        target_rank = sorted_tickers.index(target_ticker) + 1 if target_ticker in sorted_tickers else None
        peer_avg = sum(valid.values()) / len(valid)
        ranks[metric] = {
            "target_rank": target_rank,
            "target_value": values.get(target_ticker),
            "peer_avg": round(peer_avg, 4),
            "total_peers": len(valid),
        }

    # Competitive advantage score: fraction of metrics where target is top half
    scored_metrics = [m for m in metrics if ranks.get(m, {}).get("target_rank") is not None]
    if not scored_metrics:
        adv_score = 0.0
    else:
        top_half = sum(
            1 for m in scored_metrics
            if ranks[m]["target_rank"] <= (ranks[m]["total_peers"] / 2.0)
        )
        adv_score = round(top_half / len(scored_metrics), 2)

    # Build comparison table
    comparison = []
    for metric in metrics:
        r = ranks.get(metric, {})
        comparison.append({
            "metric": metric,
            "target": r.get("target_value"),
            "peer_avg": r.get("peer_avg"),
            "target_rank": r.get("target_rank"),
            "total_peers": r.get("total_peers"),
        })

    return {
        "ticker": target_ticker,
        "peer_count": n,
        "competitive_advantage": adv_score,
        "relative_strength": adv_score,
        "ranks": ranks,
        "comparison": comparison,
    }


def sector_relative_strength(
    tickers: list[str],
    peers: dict[str, dict[str, Any]],
    metrics: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Benchmark all tickers in a list against the full peer set."""
    results = []
    for tick in tickers:
        results.append(benchmark_peers(tick, peers, metrics))
    results.sort(key=lambda x: x.get("competitive_advantage", 0), reverse=True)
    return results

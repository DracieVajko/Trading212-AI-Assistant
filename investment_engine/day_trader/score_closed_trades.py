"""Persist demo training scores for closed trades."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .scoring import score_demo_trade

ROOT = Path(__file__).resolve().parents[2]
SCORES_PATH = ROOT / "history" / "demo" / "scores.jsonl"


def score_closed_demo_trades(
    trades: list[dict[str, Any]],
    *,
    scores_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Score closed trades and append them to history/demo/scores.jsonl."""
    out: list[dict[str, Any]] = []
    for trade in trades or []:
        score = score_demo_trade(trade)
        row = {**trade, **asdict(score)}
        out.append(row)
    if out:
        path = Path(scores_path) if scores_path is not None else SCORES_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for row in out:
                fh.write(json.dumps(row, default=str) + "\n")
    return out

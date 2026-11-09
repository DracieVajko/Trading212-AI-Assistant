"""Persist demo training scores for closed trades."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .scoring import score_demo_trade

ROOT = Path(__file__).resolve().parents[2]
SCORES_PATH = ROOT / "history" / "demo" / "scores.jsonl"

_KEY_FIELDS = ("order_id", "symbol", "side", "executed_at", "closed_at")


def _score_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Identity of a closed trade for deduplication."""
    return tuple(row.get(field) for field in _KEY_FIELDS)


def _load_existing_keys(path: Path) -> set[tuple[Any, ...]]:
    """Read score keys already persisted; ignore malformed lines."""
    keys: set[tuple[Any, ...]] = set()
    if not path.exists():
        return keys
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return keys
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(row, dict):
            keys.add(_score_key(row))
    return keys


def score_closed_demo_trades(
    trades: list[dict[str, Any]],
    *,
    scores_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Score closed trades and append new ones to history/demo/scores.jsonl.

    Rows are deduplicated by ``(order_id, symbol, side, executed_at,
    closed_at)`` against existing lines in the file, so re-scoring the same
    trade does not append a duplicate. Malformed existing lines are ignored.

    Returns the scored rows produced from this call; rows already present in
    the file are returned but not persisted again.
    """
    out: list[dict[str, Any]] = []
    for trade in trades or []:
        score = score_demo_trade(trade)
        row = {**trade, "demo_score": asdict(score)}
        out.append(row)
    if out:
        path = Path(scores_path) if scores_path is not None else SCORES_PATH
        existing = _load_existing_keys(path)
        new_rows: list[dict[str, Any]] = []
        for row in out:
            key = _score_key(row)
            if key in existing:
                continue
            existing.add(key)
            new_rows.append(row)
        if new_rows:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                for row in new_rows:
                    fh.write(json.dumps(row, default=str) + "\n")
    return out

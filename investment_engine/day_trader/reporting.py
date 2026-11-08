"""Reporting helpers for the day-trader pack."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .state import write_json


def write_day_trader_report(
    state_root: str | Path,
    payload: dict[str, Any],
    reports_dir: str | Path,
) -> Path:
    """Write day_trader_brief.md and day_trader.json. Return the markdown path."""
    state_root = Path(state_root)
    reports_dir = Path(reports_dir)
    current = reports_dir / "current"
    current.mkdir(parents=True, exist_ok=True)

    md_path = current / "day_trader_brief.md"
    json_path = current / "day_trader.json"

    write_json(json_path, payload)

    lines: list[str] = []
    lines.append("# Day Trader Brief")
    lines.append("")
    lines.append(f"Status: **{payload.get('status', 'UNKNOWN')}**")
    lines.append(f"Generated: {payload.get('generated_at', '')}")
    lines.append("")
    lines.append("## Premarket watchlist")
    watchlist = payload.get("watchlist") or {}
    hits = watchlist.get("hits") if isinstance(watchlist, dict) else None
    if not hits:
        lines.append("No hits this run.")
    else:
        lines.append("| Symbol | Setup | Price | Volume |")
        lines.append("|---|---|---|---|")
        for h in hits[:20]:
            if not isinstance(h, dict):
                continue
            lines.append(
                f"| {h.get('symbol', '?')} | {h.get('setup', h.get('reason', ''))} "
                f"| {h.get('price', '')} | {h.get('volume', '')} |"
            )
    lines.append("")
    lines.append("## Catalysts")
    news = payload.get("news") or {}
    if isinstance(news, dict) and news:
        lines.append(f"News items: {len(news)}")
    else:
        lines.append("No news fetched.")
    analyst = payload.get("analyst") or {}
    if isinstance(analyst, dict) and analyst:
        lines.append(f"Analyst facts: {len(analyst)}")
    pelosi = payload.get("pelosi") or {}
    if isinstance(pelosi, dict) and pelosi:
        lines.append(f"Pelosi disclosures: {len(pelosi)}")
    lines.append("")
    lines.append("## Errors")
    errors = payload.get("errors") or []
    if errors:
        for e in errors:
            lines.append(f"- {e.get('stage', '?')}: {e.get('error', '')}")
    else:
        lines.append("None.")
    lines.append("")
    lines.append("**No orders were sent (execution disabled).**")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path

"""pie_exposure.py — detect standalone holdings outside PIEs.

Trading 212 allows a position to be held both inside a PIE (pieQuantity > 0)
and as a standalone holding (quantity > pieQuantity). This module computes the
standalone (outside-PIE) quantity for each ticker and exposes it to the
rotation engine so that trim/reduce recommendations account for both portions.

Design rules:
- Never overwrites broker/API positions (pie_metadata.py contract).
- Graceful degradation: if PIE CSVs are missing, all positions are treated as
  standalone (pie_qty = 0).
- Uses canonical display symbols (investment_engine.portfolio.symbols) for matching.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PieExposure:
    """Per-ticker PIE vs standalone breakdown."""
    ticker: str
    pie_qty: float = 0.0
    total_qty: float = 0.0
    standalone_qty: float = 0.0
    pie_names: list[str] = field(default_factory=list)

    @property
    def is_standalone_only(self) -> bool:
        return self.pie_qty <= 0 and self.total_qty > 0

    @property
    def has_standalone(self) -> bool:
        return self.standalone_qty > 0


def load_pie_quantities(pies_dir: str | Path = "PIEs") -> Dict[str, float]:
    """Load {ticker: total_pie_qty} from all PIE CSV exports.

    Reads every *.csv in *pies_dir* (and subdirs), sums 'Owned quantity'
    per ticker. Returns empty dict if no CSVs found (graceful degradation).
    """
    pies_path = Path(pies_dir)
    result: Dict[str, float] = {}
    if not pies_path.exists():
        logger.debug("pie_exposure: no PIEs dir at %s; all positions standalone", pies_path)
        return result

    for csv_path in pies_path.rglob("*.csv"):
        # Skip examples/ and config/ subdirs
        parts = csv_path.parts
        if "examples" in parts or "config" in parts:
            continue
        try:
            with open(csv_path, "r", encoding="utf-8", errors="ignore") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    ticker = str(row.get("Slice") or row.get("Ticker") or "").strip().upper()
                    if not ticker or ticker == "TOTAL":
                        continue
                    qty_str = row.get("Owned quantity") or row.get("owned_quantity") or "0"
                    try:
                        qty = float(qty_str)
                    except (ValueError, TypeError):
                        qty = 0.0
                    if qty > 0:
                        result[ticker] = result.get(ticker, 0.0) + qty
        except Exception as exc:
            logger.debug("pie_exposure: could not read %s: %s", csv_path, exc)

    logger.info("pie_exposure: loaded %d tickers from PIE CSVs", len(result))
    return result


def detect_standalone_holdings(
    portfolio_rows: list[dict],
    pies_dir: str | Path = "PIEs",
) -> Dict[str, PieExposure]:
    """For each portfolio row, compute pie_qty vs total_qty.

    Returns {ticker: PieExposure} with standalone_qty = total_qty - pie_qty.
    If total_qty <= pie_qty, standalone_qty = 0 (all held in PIE).
    """
    pie_qty_map = load_pie_quantities(pies_dir)
    exposures: Dict[str, PieExposure] = {}

    for row in (portfolio_rows or []):
        ticker = str(row.get("ticker") or row.get("display") or "").strip().upper()
        if not ticker:
            continue
        total_qty = float(row.get("quantity") or row.get("pieQuantity") or 0.0)
        pie_qty = pie_qty_map.get(ticker, 0.0)
        standalone = max(0.0, total_qty - pie_qty)
        exposures[ticker] = PieExposure(
            ticker=ticker,
            pie_qty=pie_qty,
            total_qty=total_qty,
            standalone_qty=standalone,
        )

    return exposures


def standalone_summary(exposures: Dict[str, PieExposure]) -> str:
    """Human-readable summary of standalone holdings (for report inclusion)."""
    lines = []
    for t, e in exposures.items():
        if e.has_standalone:
            lines.append(f"  - {t}: pie={e.pie_qty:.4f}, total={e.total_qty:.4f}, standalone={e.standalone_qty:.4f}")
    if not lines:
        return "No standalone holdings detected (all positions held inside PIEs)."
    return "Standalone holdings (outside PIEs):\n" + "\n".join(lines)

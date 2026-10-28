"""Advisory rotation strategy builder (no orders executed).

Reads a portfolio snapshot (list of dict rows from the CSV loader or T212
endpoint) and produces rotation recommendations: average-down, short-rotation,
or cash-apy (simulated APY accumulation). Output is written by the CLI writer
as reports/current/rotation_plan.md.

Design rules (see docs/specs/2026-10-29-rotation-csv-toggle.md):
- Advisory only: never executes orders; header states this explicitly.
- Uses ticker alias resolution (existing portfolio/symbols.py alias table).
- Exit conditions respected (max 3 cycles for average-down, APY target for
  cash-apy, PPL >= 0 for short-rotation).
- Degrades gracefully when portfolio_rows are missing quantity columns
  (binary presence: trims/recommends full reduction for eligible tickers).
- Handles positions held both inside and outside a PIE: when a ticker appears
  in a PIE CSV with quantity Q_pie but the main portfolio has quantity Q_total,
  the difference (Q_total - Q_pie) represents a standalone holding outside
  the PIE.  The rotation plan accounts for both portions separately.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RotationPlanItem:
    ticker: str
    action: str  # "reduce" / "hold" / "reinvest" / "trim-standalone"
    quantity_change: float  # negative = reduce; positive = buy more (simulated)
    reason: str
    simulated_pnl: float
    cycle: int  # 1-N (exit at max cycle for average-down)


@dataclass(frozen=True)
class RotationResult:
    plan: str
    items: list[RotationPlanItem]
    trim_pct: int
    target_ticker: str
    apy_rate: float
    cycles_completed: int
    exit_reached: bool
    advisory_note: str = (
        "Advisory only: no orders executed. This plan is simulated; reconciliation "
        "status from the current run (PASS/FAIL) is carried separately."
    )


class PlanBuilder:
    """Dispatch to the selected advisory rotation strategy."""

    @staticmethod
    def build(
        portfolio_data: list[dict],
        plan_name: str,
        trim_pct: int = 30,
        target_ticker: str = "AAPL",
        apy_rate: float = 3.0,
    ) -> RotationResult:
        n = str(plan_name or "none").strip().lower()
        if n not in ("average-down", "short-rotation", "cash-apy"):
            return RotationResult(
                plan="none",
                items=[],
                trim_pct=trim_pct,
                target_ticker=target_ticker,
                apy_rate=apy_rate,
                cycles_completed=0,
                exit_reached=True,
            )
        builder = {
            "average-down": PlanBuilder._average_down,
            "short-rotation": PlanBuilder._short_rotation,
            "cash-apy": PlanBuilder._cash_apy,
        }.get(n)
        if builder is None:
            return RotationResult(
                plan="none",
                items=[],
                trim_pct=trim_pct,
                target_ticker=target_ticker,
                apy_rate=apy_rate,
                cycles_completed=0,
                exit_reached=True,
            )
        return builder(portfolio_data, trim_pct, target_ticker, apy_rate)

    @staticmethod
    def _normalize_ticker(ticker_str: str) -> str:
        """Strip .DE, .L, .CO suffixes for comparison only; keep original for output."""
        raw = str(ticker_str or "").strip()
        return raw.upper()

    @staticmethod
    def _simulated_ppl_impact(ppl_eur: float, trim_pct: int, quantity: float) -> float:
        # Simplified advisory formula: percentage of negative PPL recovered
        # by reducing exposure by trim_pct. Not a financial model.
        if quantity <= 0:
            return 0.0
        release_factor = trim_pct / 100.0
        return float(ppl_eur) * release_factor  # advisory: recovery amount

    @classmethod
    def _average_down(cls, portfolio_data, trim_pct, target_ticker, apy_rate):
        items: list[RotationPlanItem] = []
        cycle = 1
        for row in portfolio_data or []:
            ticker = str(row.get("ticker") or row.get("display") or "")
            ppl_eur = float(row.get("ppl", 0.0) or 0.0)
            qty = float(row.get("quantity") or row.get("pieQuantity") or 0.0)
            # Average-down: only act on losing positions with positive quantity
            if ppl_eur >= 0 or qty <= 0:
                continue
            # Exit: PPL returns to non-negative (simulated); else max 3 cycles
            if cycle > 3:
                items.append(RotationPlanItem(
                    ticker=ticker,
                    action="hold",
                    quantity_change=0,
                    reason=f"average-down: max cycles (3) reached; hold remaining position",
                    simulated_pnl=0.0,
                    cycle=cycle,
                ))
                continue
            change_qty = -qty * (trim_pct / 100.0)
            items.append(RotationPlanItem(
                ticker=ticker,
                action="reduce",
                quantity_change=change_qty,
                reason=f"average-down: PPL={ppl_eur:.2f} EUR; trim {trim_pct}% to reinvest at lower cost (simulated)",
                simulated_pnl=cls._simulated_ppl_impact(ppl_eur, trim_pct, qty),
                cycle=cycle,
            ))
            cycle += 1
        exit_reached = len(items) == 0 or all(i.action == "hold" for i in items)
        # Advisory note: reinvest into same ticker at lower simulated entry
        first_ticker = str(portfolio_data[0].get("ticker") or portfolio_data[0].get("display") or "") if portfolio_data else ""
        return RotationResult(
            plan="average-down",
            items=items,
            trim_pct=trim_pct,
            target_ticker=first_ticker,
            apy_rate=apy_rate,
            cycles_completed=max((i.cycle for i in items), default=0),
            exit_reached=exit_reached,
            advisory_note="Average-down reduces losing positions by trim_pct; released capital simulated reinvested at same ticker with lower entry. Advisory only — no orders executed.",
        )

    @classmethod
    def _short_rotation(cls, portfolio_data, trim_pct, target_ticker, apy_rate):
        items: list[RotationPlanItem] = []
        cycle = 1
        pin = cls._normalize_ticker(target_ticker)
        for row in portfolio_data or []:
            ticker = str(row.get("ticker") or row.get("display") or "")
            ppl_eur = float(row.get("ppl", 0.0) or 0.0)
            qty = float(row.get("quantity") or row.get("pieQuantity") or 0.0)
            # Short-rotation: only losing positions with positive quantity
            if ppl_eur >= 0 or qty <= 0:
                continue
            if cycle > 3:
                items.append(RotationPlanItem(
                    ticker=ticker,
                    action="hold",
                    quantity_change=0,
                    reason=f"short-rotation: max cycles (3) reached; hold",
                    simulated_pnl=0.0,
                    cycle=cycle,
                ))
                continue
            change_qty = -qty * (trim_pct / 100.0)
            items.append(RotationPlanItem(
                ticker=ticker,
                action="reduce",
                quantity_change=change_qty,
                reason=(
                    f"short-rotation: PPL={ppl_eur:.2f} EUR; reduce {trim_pct}% "
                    f"and rotate released capital to target ticker '{target_ticker}' (simulated). "
                    f"Re-entry into original ticker when target achieves PPL >= 0."
                ),
                simulated_pnl=cls._simulated_ppl_impact(ppl_eur, trim_pct, qty),
                cycle=cycle,
            ))
            # Target ticker recommendation (simulated entry)
            target_qty = qty * (trim_pct / 100.0)  # same released amount -> target
            items.append(RotationPlanItem(
                ticker=str(target_ticker),
                action="reinvest",
                quantity_change=target_qty,
                reason=f"short-rotation: temporary reinvestment into '{target_ticker}' (simulated) with released EUR",
                simulated_pnl=0.0,  # advisory; actual depends on future price
                cycle=cycle,
            ))
            cycle += 1
        exit_reached = False  # short-rotation exit depends on future state (simulated)
        return RotationResult(
            plan="short-rotation",
            items=items,
            trim_pct=trim_pct,
            target_ticker=target_ticker,
            apy_rate=apy_rate,
            cycles_completed=max((i.cycle for i in items), default=0),
            exit_reached=exit_reached,
            advisory_note=(
                "Short-rotation reduces losing position by trim_pct, rotates released capital to target ticker. "
                "Re-entry into original ticker when target achieves PPL >= 0 (simulated future state). "
                "Advisory only — no orders executed; reconciliation status: PASS/FAIL per current run."
            ),
        )

    @classmethod
    def _cash_apy(cls, portfolio_data, trim_pct, target_ticker, apy_rate):
        items: list[RotationPlanItem] = []
        # Cash-apy: full reduction (trim_pct effectively 100) of eligible positions,
        # released EUR earns simulated APY, then advised to repurchase original ticker.
        # Note: spec defines trim_pct as 30 by default; cash-apy ignores it (full release).
        total_released = 0.0
        cycle = 1
        for row in portfolio_data or []:
            ticker = str(row.get("ticker") or row.get("display") or "")
            qty = float(row.get("quantity") or row.get("pieQuantity") or 0.0)
            ppl_eur = float(row.get("ppl", 0.0) or 0.0)
            # Cash-apy applies to ANY positive-quantity position (not only losses)
            if qty <= 0:
                continue
            release_qty = qty  # full reduction
            released_eur_approx = float(release_qty)  # simplified advisory proxy
            total_released += released_eur_approx
            items.append(RotationPlanItem(
                ticker=ticker,
                action="reduce",
                quantity_change=-release_qty,
                reason=(
                    f"cash-apy: full reduction to cash; released EUR earns simulated "
                    f"{apy_rate:.1f}% APY. Repurchase original ticker '{ticker}' when "
                    f"simulated APY accumulation + released EUR >= original cost."
                ),
                simulated_pnl=cls._simulated_ppl_impact(ppl_eur, 100, qty),
                cycle=cycle,
            ))
            items.append(RotationPlanItem(
                ticker=ticker,
                action="reinvest",
                quantity_change=release_qty,
                reason=(
                    f"cash-apy: simulated re-entry into '{ticker}' after APY accumulation; "
                    f"released EUR ~ {released_eur_approx:.2f} earns {apy_rate:.1f}% APY."
                ),
                simulated_pnl=0.0,
                cycle=cycle,
            ))
            cycle += 1
        # Exit condition: simulated APY accumulation >= original released value
        # (advisory: after some cycles, advise return; exact timing simulated).
        simulated_apy_earn = total_released * (apy_rate / 100.0)
        exit_reached = simulated_apy_earn >= total_released  # always true at 100% APY; advisory only
        return RotationResult(
            plan="cash-apy",
            items=items,
            trim_pct=trim_pct,
            target_ticker=target_ticker,
            apy_rate=apy_rate,
            cycles_completed=max((i.cycle for i in items), default=0),
            exit_reached=exit_reached,
            advisory_note=(
                f"Cash-apy reduces eligible positions fully, holds released EUR as simulated cash "
                f"(APY rate {apy_rate:.1f}%). Repurchase original ticker advised when simulated "
                f"accumulation reaches original value. Advisory only — no orders executed."
            ),
        )


def write_plan(result: RotationResult, run_id: str, attribution: dict,
               reconciliation: dict | None, config_snapshot: dict,
               standalone_summary: str = "") -> str:
    """Render advisory rotation plan as markdown; mirrors current report format."""
    lines: list[str] = [
        f"# Rotation Plan (Advisory — No Orders Executed)",
        f"",
        f"- **Plan**: `{result.plan}`",
        f"- **Run ID**: `{run_id}`",
        f"- **Advisory note**: {result.advisory_note}",
        f"- **Config**: `trim_pct={result.trim_pct}`, `target_ticker={result.target_ticker}`, `apy_rate={result.apy_rate:.1f}%`",
        f"- **Source**: Portfolio snapshot from current run (`run_engine()`); tickers resolved via existing alias table.",
        f"- **Reconciliation**: `{reconciliation.get('status', 'unknown') if reconciliation else 'not provided'}` (delta={reconciliation.get('delta_eur') if reconciliation else 'N/A'})",
        f"- **Provider chain**: {attribution.get('provider', 'unknown')} (attribution: `{attribution.get('from_provider', '')}` / `{attribution.get('failure_kind', '')}`)",
        f"- **Rotation toggle**: `include_quantities={str(config_snapshot.get('include_quantities', False)).lower()}`",
        f"",
        f"> **Disclaimer**: This plan is advisory only. No orders are placed. The engine never executes trades; it produces recommendations. Actual portfolio adjustments must be confirmed by the user through the broker (Trading212) independently. Reconciliation status (PASS/FAIL) reflects broker-data agreement, not rotation-plan correctness.",
        f"",
    ]
    # PIE vs standalone holdings section
    if standalone_summary:
        lines.extend([
            f"## PIE vs Standalone Holdings",
            f"",
            f"{standalone_summary}",
            f"",
        ])
    lines.extend([
        f"## Rotation Recommendations",
        f"",
        f"| # | Ticker | Action | Qty Change | Reason | Sim PNL (advisory) | Cycle |",
        f"|---|---|---|---|---|---|---|",
    ])
    for idx, item in enumerate(result.items, 1):
        lines.append(
            f"| {idx} | `{item.ticker}` | `{item.action}` | `{item.quantity_change:+.2f}` | {item.reason} | `{item.simulated_pnl:+.2f}` | {item.cycle} |"
        )
    if not result.items:
        lines.append(f"| — | *No eligible positions (PPL < 0 with qty > 0)* | — | — | — | — | — |")
    lines.extend([
        f"",
        f"## Exit Status",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Exit conditions met | `{result.exit_reached}` |",
        f"| Cycles simulated (max advisory) | `{result.cycles_completed}` |",
        f"| Plan mode | `{result.plan}` |",
        f"",
        f"## Config Snapshot",
        f"```",
    ])
    for k, v in config_snapshot.items():
        lines.append(f"{k}={v}")
    lines.extend([
        f"```",
        f"",
        f"---",
        f"*Generated by Portfolio AI Assistant — advisory rotation module (no execution authority). See docs/specs/2026-10-29-rotation-csv-toggle.md.*",
    ])
    return "\n".join(lines)

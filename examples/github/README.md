# Example Outputs — Portfolio AI Assistant

This directory contains **anonymized example outputs** from the Portfolio AI Assistant script.
Portfolio values and costs are retained (they are not personal data); tickers, dates, and
account identifiers have been replaced with generic values.

## What the script produces

| File | Description |
|------|-------------|
| `portfolio_snapshot.md` | Broker account summary, position reconciliation, holdings table, PIE breakdown |
| `rotation_plan_average_down.md` | Advisory rotation plan (average-down strategy) |
| `rotation_plan_short_rotation.md` | Advisory rotation plan (short-rotation strategy) |
| `rotation_plan_cash_apy.md` | Advisory rotation plan (cash-apy strategy) |
| `PIEs/*.csv` | Example PIE (pie) CSV exports with tickers, invested value, value, result, quantity |

## Rotation plan example (average-down)

The rotation plan is **advisory only** — no orders are executed. It recommends:
- Reducing losing positions by `trim_pct` (default 30%)
- Reinvesting released capital at the same ticker (average-down) or target ticker (short-rotation)
- Holding cash for APY (cash-apy)

See `rotation_plan_average_down.md` for a full example output.

## PIE CSV format

PIE CSV exports from Trading212 contain columns:
- `Slice` — ticker symbol
- `Name` — company name
- `Invested value` — amount invested
- `Value` — current market value
- `Result` — unrealized P&L
- `Owned quantity` — shares held in this PIE
- `Dividends gained/cash/reinvested` — dividend tracking

When a position is held **both inside and outside a PIE**, the difference
(`portfolio_quantity - pie_quantity`) represents a standalone holding outside
the PIE. The engine accounts for both portions separately.

## How to run

```bash
py -3.12 portfolio_ai_assistant.py --config portfolio_config.json --investment-engine --generate-full-report --rotation-plan average-down --include-quantities
```

Output files are written to `reports/current/`:
- `portfolio_decision_brief.md`
- `t212_portfolio_snapshot.md`
- `portfolio_analysis.json`
- `rotation_plan.md` (when `--rotation-plan` is non-none)
- `portfolio_intelligence_brief.md`

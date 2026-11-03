# Experimental backtest sandbox

This directory is intentionally isolated from the production pipeline. It is
not imported by `investment_engine/`, `trading212/`, or
`portfolio_ai_assistant.py`.

- `backtest/` — vectorized backtest engine, metrics, validation, walk-forward,
  and the `tech_pie_pullback_v1` strategy.
- `tests/` — the sandbox's own pytest suite.

Status: research sandbox, not a supported product surface. It is excluded from
the main package boundary and may change or be removed without a production
migration. To run its tests:

```cmd
py -3.12 -m pytest experimental/tests -q
```

Production backtesting is not exposed through the CLI. If this sandbox is ever
promoted, add an explicit `investment_engine.backtest` package and a migration
note here first.

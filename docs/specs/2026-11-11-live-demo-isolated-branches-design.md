# Live and demo branches in one run

Date: 2026-11-11
Status: implemented

## Problem

A scheduled run analysed the live account and, separately, a day-trader pack
that could place demo orders. Three things were wrong:

1. The demo side never analysed the demo portfolio — it planned from a screener
   and executed on the demo account, so demo and live were not comparable.
2. Reruns duplicated orders. Dedupe hashed `date|symbol|side|quantity|reason`,
   so the same idea with a slightly different size produced a new hash and a
   second order an hour later.
3. There was no single run that produced both views.

## Decisions (agreed with the operator)

| Decision | Choice |
|---|---|
| What "live" means | Real data and recommendations only. Live order execution stays disabled. |
| Duplicate rule | One order per symbol + side per trading day, regardless of size or plan changes. |
| Trading day | The New York calendar date. |
| Branch execution | Live branch first, demo branch after it, in one process. |
| Shared data | Asset universe, market data, news corpus. |
| Isolated data | Portfolio snapshot, prompt context, AI provider instance, decisions, orders, reports. |

## Architecture

```
run
├─ shared: asset universe | market data | news corpus (process-level cache)
├─ branch LIVE  (read-only)
│   ├─ fetches the live account itself
│   ├─ own provider instance + own prompt built from live holdings
│   └─ recommendations only — never places an order
└─ branch DEMO
    ├─ own snapshot from the demo account (/equity/portfolio + summary)
    ├─ own provider instance + own prompt built from demo holdings
    └─ the only branch allowed to place orders
```

`investment_engine/branches.py` owns this. `run_branch(mode, ...)` fetches or
injects the branch snapshot and calls the engine with `portfolio_context["mode"]`,
which is also the mode written to history.

The demo snapshot is converted into the canonical snapshot shape the pipeline
already understands (`status`, `account_summary`, `cash`, `all_positions`), so no
second pipeline is needed. Values come from the broker's own `walletImpact`
block, so no FX guesswork is introduced.

### Shared data

* `fetch_all_news_parallel` caches its corpus per process, keyed by trading date,
  news settings and the symbol list. The demo branch reuses the corpus the live
  branch fetched.
* `prepare_run` skips `reset_market_data_registry()` when the branch context sets
  `reuse_market_data=True`, so OHLCV bars are not downloaded twice.
* Both branches run on the same asset universe; only the portfolio context
  differs.

### Order ledger

`investment_engine/order_ledger.py` answers "has this symbol+side already been
traded today?" by reading:

* `history/<mode>/trades.jsonl` — what reached the broker;
* `data/day_trader/audit.db` `order_intents` — what was attempted, including
  resting orders.

Only statuses that reached the broker count (`PLACED`, `FILLED`,
`PARTIALLY_FILLED`, `SUBMITTED`). `FAILED`, `BLOCKED` and the transient `PENDING`
row of the in-flight call are ignored; the current intent is excluded explicitly.

The day is the New York calendar date, so a plan made an hour before the open and
another an hour after it are the same day and the second is blocked.

The check runs inside `execute_demo_plan` before any order reaches the broker, and
returns `BLOCKED` with the original order id and time in the reason.

## Reports

| Branch | Location |
|---|---|
| Live | `reports/current/` (unchanged, so existing readers keep working) |
| Demo | `reports/current/demo/` |
| Archive | `reports/archive/<run_id>-demo/` |

## Failure isolation

A failing branch never cancels the other one: each branch is wrapped, logged and
reported separately. If the demo snapshot cannot be fetched, the live report is
still published and the demo failure is printed with its exception type.

## Testing

* `tests/test_order_ledger.py` — day conversion, history and audit sources,
  quantity changes, symbol/side/day isolation, failed rows ignored, live history
  does not block demo.
* `tests/test_branches.py` — demo snapshot contract, zero-quantity rows, broker
  error handling, per-branch snapshot injection, stale override cleared for live,
  separate report folders.
* `tests/conftest.py` — an autouse fixture points the ledger at a temporary
  history root so tests are never blocked by what the operator traded today.
* `tests/test_day_trader_execute.py` — the existing suite plus exit sizing from
  the owned quantity.

## CLI

```
--branches both   # default: live report + demo execution
--branches live   # live only
--branches demo   # demo only
```

Default can also be set with `settings.run_branches` in `portfolio_config.json`.

## Known limitations

* The demo branch reuses the engine's advisory decisions; demo **orders** still
  come from the day-trader pack (sizing, bracket, risk gate). They are demo-only
  and now ledger-protected, but they are not derived from the demo branch's AI
  text.
* Because a single local model is loaded at a time, both branches serialise on
  inference. Wall time is roughly the sum of both branches' AI stages.
* The demo branch only executes when the day-trader execution flags are enabled.

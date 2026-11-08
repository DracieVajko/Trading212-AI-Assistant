# Day Trader Skill Integration — Design

**Date:** 2026-11-06
**Status:** Draft for user review
**Source:** https://github.com/jakeschincariol/day-trader-skill
**Vendored commit:** `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` (2026-10-20)
**License:** MIT (Copyright (c) 2026 Jake Schincariol)

## 1. Context

The source repository contains 11 Claude skills for day trading. Each skill is a
`SKILL.md` plus a standalone Python tool that reads public data (Yahoo Finance,
Nasdaq Trader symbol directories, SEC EDGAR, House Clerk) and writes JSON state
to a `trader/` folder.

The portfolio bot is a batch, advisory, long-term portfolio assistant. It has:

- a read-only Trading 212 client (`trading212/`) that refuses non-GET calls;
- a Python skill registry (`investment_engine/skills/`) with structured outputs;
- a single daily report pipeline (`portfolio_ai_assistant.py` → `run_engine`);
- Windows Task Scheduler entry points (`run_automated.bat`);
- no order-placement capability.

The user wants all 11 skills available, running automatically every day, with
buy support implemented but disabled. The path to enablement is: recommendations
only → demo money → live money.

## 2. Goals

1. Vendor all 11 skills with their tests and license, pinned to one commit.
2. Run the daily read-only research pack automatically and include it in the
   daily report.
3. Run the trade-planning pack (entry, exit, time machine, budget, risk) and
   produce advisory tickets.
4. Implement a Trading 212 execution layer that is **hard-disabled by default**
   and can later be enabled for demo, then live, behind explicit gates.
5. Keep the existing long-term portfolio signals and the new day-trade signals
   completely separate.
6. Never send an order unless every execution gate passes.

## 3. Non-goals

- Replacing the existing long-term portfolio engine or its signal model.
- Automatic live trading in this phase.
- Copying the upstream Claude plugin/marketplace metadata into our runtime.
- Using the upstream `trader-broker` ticket approval as our execution gate; it
  only renders tickets and records a chat reply.

## 4. Approaches considered

| Approach | Verdict |
| --- | --- |
| **A. Vendor + Python adapter + session runner** | **Selected.** Keeps upstream algorithms, supports automatic daily runs, isolates the external code. |
| B. Reimplement all methods natively | Rejected: large effort, divergence risk, no upstream fixes. |
| C. Install only as `.claude/skills` | Rejected: not part of the automated report/session. |

## 5. Architecture

```
vendor/day_trader_skill/              # MIT copy, pinned commit, LICENSE
  VENDORED_COMMIT
  trader-*/                           # 11 skill folders (SKILL.md + *.py)
  tests/                              # upstream offline tests + fixtures

investment_engine/day_trader/
  __init__.py
  config.py                           # DayTraderConfig + validation
  runner.py                           # subprocess wrapper, --json parsing
  state.py                            # state root, archive, corruption recovery
  session.py                          # premarket/open/manage/close orchestration
  market_calendar.py                  # NYSE sessions, holidays, ET clock
  reporting.py                        # day_trader_brief.md + JSON
  broker/
    __init__.py
    t212_orders.py                    # demo/live order client (allowlisted endpoints)
    guard.py                          # execution gates
    bracket.py                        # entry + stop + target state machine
    audit.py                          # SQLite order_intents/order_events
```

### 5.1 Vendoring

- Copy `trader-*`, `tests/`, `LICENSE`, `README.md` into
  `vendor/day_trader_skill/`.
- Add `VENDORED_COMMIT` containing the SHA above.
- Do not copy `.git/` or `.claude-plugin/`.
- Record the source URL and license in `vendor/day_trader_skill/README.vendor.md`.
- Updating the vendor copy is a deliberate task: diff upstream, re-run upstream
  tests, update `VENDORED_COMMIT`.

### 5.2 Runner

`runner.run_tool(skill, args, timeout_s, json_mode=True) -> ToolResult`

- Executes the vendored script with `sys.executable` (Python 3.12).
- Uses `subprocess.run([...], cwd=state_root, shell=False)`.
- Sets `PYTHONIOENCODING=utf-8`; passes `SEC_USER_AGENT` when configured.
- Parses stdout as JSON when `--json` is used; keeps raw text otherwise.
- Returns `ok`, `exit_code`, `payload`, `stdout`, `stderr`, `duration_s`.
- Never raises for a tool failure; the caller records a degraded stage.
- Per-tool default timeouts: scanner 900 s, timemachine 300 s, news/analyst/
  pelosi 120 s, entry/exit/budget/risk/ticket/alerts 60 s.

### 5.3 State

All external tools run with `cwd = data/day_trader`, so their default
`trader/...` paths resolve to `data/day_trader/trader/`.

```
data/day_trader/
  trader/                  # external tools' working state
    config.json            # generated from DayTraderConfig
    universe.txt
    watchlist.json
    plan.json
    orders.json
    timemachine.json
    prices.json
    alerts.json
    portfolio.json
    state/
  sessions/YYYY-MM-DD/     # per-session snapshots and logs
  audit.db                 # our SQLite order audit
  KILL_SWITCH              # presence blocks every order attempt
```

- `state.py` creates directories, writes the generated `trader/config.json`,
  archives the day's state at close, and recovers corrupt JSON by moving it to
  `*.corrupt-<timestamp>` before recreating a default.
- The upstream state format is preserved so its tickets and tests remain usable.

## 6. Configuration

Add an optional `day_trader` block to `portfolio_config.json`. Code defaults are
safe (disabled) when the block is missing.

```json
{
  "day_trader": {
    "enabled": true,
    "auto_run": true,
    "state_dir": "data/day_trader",
    "timezone": "America/New_York",
    "universe_limit": 200,
    "watchlist_limit": 20,
    "scan": {
      "min_price": 5,
      "min_volume": 1000000,
      "or_minutes": 15
    },
    "budget": {
      "account_currency": "EUR",
      "account_value": 1000,
      "max_loss_per_trade": 10,
      "max_daily_loss": 30,
      "max_trades_per_day": 2,
      "max_position_pct": 20,
      "cash_buffer_pct": 10
    },
    "schedule": {
      "premarket_et": "09:00",
      "orb_et": "09:50",
      "close_et": "15:55"
    },
    "execution": {
      "enabled": false,
      "broker": "trading212",
      "environment": "demo",
      "auto_approve": false,
      "max_order_eur": 50,
      "max_daily_orders": 2,
      "allowed_sides": ["BUY"],
      "live_ack": ""
    },
    "report": {
      "max_hits": 10,
      "include_pelosi": true
    }
  }
}
```

Rules:

- All budget values are in the **account currency** (`account_currency`, default
  `EUR`). The upstream tools use `_usd` key names internally; the adapter maps
  our values into `trader/config.json` unchanged and treats the numbers as the
  account currency. No implicit USD/EUR conversion is performed.
- The effective day-trade budget is
  `min(budget.account_value, broker free cash)`; if free cash is lower, the
  session uses the broker figure and records the cap in the report.
- `execution.enabled` defaults to `false` and is independent of `enabled`.
- `environment` accepts `demo` or `live`; `demo` is the only accepted value
  until the demo runbook has passed.
- `auto_approve` defaults to `false`. An unattended session with
  `auto_approve=false` produces tickets only.
- `live_ack` must be an empty string by default. Enabling live later requires an
  explicit acknowledgement value in config **and** an environment variable.

## 7. CLI

Add to `portfolio_ai_assistant.py`:

| Flag | Behaviour |
| --- | --- |
| `--day-trader` | Run the premarket read-only pack once, write the day-trader report. |
| `--day-trader-session` | Run the full session until the close phase (dry-run by default). |
| `--day-trader-report` | Regenerate the report from existing state; no network. |
| `--day-trader-allow-orders` | Permit the execution layer to attempt orders if **all** gates pass. Not used by the scheduled task. |

The default scheduled task uses `--day-trader-session` without
`--day-trader-allow-orders`.

## 8. Daily session

All times are America/New_York.

| Phase | Time | Actions |
| --- | --- | --- |
| Pre-market | 09:00 | `scan.py daily --limit 200`, news on hits, analyst on top N, Pelosi index. Write watchlist and report. |
| Open | 09:50 | `scan.py orb --watchlist`, `entry.py check` for each hit. |
| Plan | On trigger | `exit.py plan`, `timemachine.py run`, `size.py`, `check.py`, `ticket.py show`. |
| Manage | After entry | Alerts and order-state reconciliation (stop/target siblings). |
| Close | 15:55 | `alerts.py check`, flatten ticket, archive state, final report. |

- Weekends and NYSE holidays: exit with `MARKET_CLOSED`.
- The session is resumable: each phase records a checkpoint in
  `data/day_trader/trader/state/`.
- Network or tool failure marks the stage `DEGRADED`; the session continues and
  the report lists the failed stage. A failed stage can never trigger an order.
- Scheduler entry point: a new `run_day_trader.bat` (same `cd /d "%~dp0"` as the
  other launchers) starts at **14:45 Europe/Bratislava** and runs
  `--day-trader-session`. The session converts `09:00`/`09:50`/`15:55` ET with
  `zoneinfo`, waits for the pre-market phase, and exits after the close phase.
  The exact Windows task time is documented in `docs/DayTrader.md`; only one
  task is needed because the session owns the intraday clock.

## 9. Reporting

New files:

- `reports/current/day_trader_brief.md`
- `reports/current/day_trader.json`

The brief contains:

1. Session header: date, phase, market status, execution mode
   (`DISABLED` / `DEMO` / `LIVE`), reconciliation status.
2. Pre-market watchlist: symbol, setup, price, volume, reason, top N.
3. Catalysts: news headlines, earnings facts, Pelosi disclosures.
4. Active plans: entry, stop, target, Time Machine odds, budget size, risk
   verdict.
5. Tickets: READY / BLOCKED with the exact reason.
6. A banner: “No orders were sent” unless execution is enabled; when enabled,
   the environment and approval mode are shown.

`portfolio_intelligence_brief.md` gets one short section linking to the
day-trader brief. Day-trade signals are never written into the long-term
`portfolio_rows[].signal` field.

## 10. Execution layer

### 10.1 Trading 212 API facts

- Demo: `https://demo.trading212.com/api/v0`
- Live: `https://live.trading212.com/api/v0`
- Auth: HTTP Basic `base64(api_key:api_secret)`.
- Order endpoints: `POST /equity/orders/market`, `/limit`, `/stop`,
  `/stop-limit`; `GET /equity/orders`, `GET /equity/orders/{id}`,
  `DELETE /equity/orders/{id}`.
- Sell orders use a negative `quantity`.
- No native bracket/OCO. We emulate a bracket with separate stop and target
  sell orders and cancel the sibling when one fills.
- API is beta; endpoints and fields must be verified in the demo environment
  before enabling live.

### 10.2 Credentials

Use separate credentials from the read-only client:

- `T212_DEMO_API_KEY` / `T212_DEMO_API_SECRET`
- `T212_LIVE_API_KEY` / `T212_LIVE_API_SECRET`
- `T212_ORDER_ENABLED=1`
- `T212_ORDER_ENV=demo|live`
- `T212_LIVE_ACK=I_UNDERSTAND_LIVE_TRADING` (live only)

The existing read-only `Trading212Auth` remains GET-only and is never reused
for order placement. The order client has an allowlist of order endpoints and
accepts only POST/GET/DELETE on those paths.

### 10.3 Gates

An order intent must pass every gate:

1. `day_trader.execution.enabled is True`.
2. `T212_ORDER_ENABLED=1` and the selected environment credentials exist.
3. `environment == demo`; live additionally requires `T212_ORDER_ENV=live`,
   `T212_LIVE_ACK=I_UNDERSTAND_LIVE_TRADING`, and a matching non-empty
   `execution.live_ack` in config.
4. `auto_approve is True` for unattended placement; otherwise ticket only.
5. `data/day_trader/KILL_SWITCH` does not exist.
6. Reconciliation is `PASS` and the account currency is EUR.
7. Order notional ≤ `max_order_eur`; daily order count ≤ `max_daily_orders`;
   daily realized loss ≤ `max_daily_loss`.
8. Symbol is in the current watchlist/plan; side is in `allowed_sides`.

Any failure returns `BLOCK` with a machine-readable reason. A block is final
for that intent and is recorded in the audit.

### 10.4 Bracket state machine

1. Prepare an entry intent (market or limit) from `plan.json` / `orders.json`.
2. Check idempotency: no open order for the same symbol/side/quantity, and no
   audit row in a terminal state for the same plan fingerprint.
3. Place the entry order.
4. Poll `GET /equity/orders/{id}` until filled, cancelled, or the entry window
   closes. On timeout, cancel the entry.
5. On fill, place the stop sell and the target sell (two separate orders).
6. Poll both. When one fills or is cancelled, cancel the sibling.
7. At `close_et`, cancel any remaining siblings and, if a position is still
   open and flatten is enabled, place a market sell.
8. Record every event in `data/day_trader/audit.db`.

The exact order types are chosen from the plan: limit entry when the plan has a
limit price, market otherwise; stop sell for the stop; limit sell for the
target.

### 10.5 Audit

SQLite `data/day_trader/audit.db`:

- `order_intents`: id, session_date, symbol, side, quantity, order_type,
  limit_price, stop_price, fingerprint, status, created_at, updated_at.
- `order_events`: id, intent_id, event, broker_order_id, payload_json
  (redacted), created_at.

`fingerprint = sha256(session_date|symbol|side|quantity|entry|stop|target)`
for idempotency.

## 11. Error handling

- External tool failure: stage `DEGRADED`, report reason, continue.
- Network timeout: bounded per-tool timeout; one retry at most where the tool
  already implements it; never an unbounded loop.
- Corrupt state: move to `.corrupt-<ts>`, recreate defaults, record `DEGRADED`.
- Market closed: `MARKET_CLOSED`, no tools run.
- Order failure: record the broker response (redacted), mark the intent
  `FAILED`, never retry a placement automatically; a retry requires a new
  intent and a fresh guard pass.
- A crash must leave the read-only portfolio report and the day-trader state
  recoverable.

## 12. Testing

- Unit:
  - runner JSON parsing, timeout, non-zero exit;
  - config validation and safe defaults;
  - guard matrix: every gate independently blocks;
  - bracket state machine with a mocked order client;
  - idempotency and duplicate suppression;
  - report rendering with fixtures;
  - ET session/holiday calculations with a frozen clock.
- Integration:
  - run the vendored upstream tests offline:
    `python -m unittest discover -s vendor/day_trader_skill/tests -v`;
  - adapter smoke test for each of the 11 tools with `--help` and `--json`
    where offline fixtures exist;
  - end-to-end dry-run session using offline fixtures.
- Execution tests use a fake HTTP transport. No test may call demo or live
  Trading 212 endpoints.
- Regression: the existing full test suite must pass (current baseline:
  874 passed, 3 skipped, 5 known pre-existing failures).

## 13. Rollout phases

1. **Foundation** — vendor, runner, config, state, premarket read-only pack,
   report, tests. No order code.
2. **Planning** — entry, exit, time machine, budget, risk, tickets, report,
   tests. Still no order code.
3. **Session** — full daily orchestration, alerts, scheduler entry point,
   docs.
4. **Execution-ready** — T212 order client, guard, bracket, audit, mocked
   tests. `execution.enabled=false`; no scheduled run uses
   `--day-trader-allow-orders`.
5. **Enablement** — demo runbook, then live runbook with explicit
   acknowledgement, monitoring, and a kill-switch drill.

## 14. Acceptance criteria

- All 11 vendored tools run from the vendored path with Python 3.12.
- The daily session produces `day_trader_brief.md` and `day_trader.json`.
- `execution.enabled=false` produces **zero** POST calls to any broker
  endpoint; a test asserts this.
- Demo placement is possible only with all gates passing; live placement
  requires the explicit acknowledgement.
- Every order attempt is auditable and idempotent.
- Existing portfolio tests remain green; new tests cover the adapter, guards,
  bracket state machine, and reporting.
- No secrets appear in logs, reports, or audit payloads.
- All runtime output stays under `PortfolioAI_Assistant`.

## 15. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Yahoo endpoints are unofficial and rate-limited | Default `--limit 200` plus portfolio/watchlist symbols; backoff; report `DEGRADED` |
| Full-universe scan is slow | Never scan the full universe by default; configurable limit |
| T212 API is beta and order semantics may change | Pin docs/date, demo-first, mock tests, verify in demo before live |
| Upstream repo has one commit / no releases | Vendor SHA, keep upstream tests, review diffs deliberately |
| Day trading is high risk | Execution disabled by default; paper first; caps; kill switch |
| Scheduler/timezone drift | All session times in ET via `zoneinfo`; market calendar; explicit `MARKET_CLOSED` |
| External code safety | MIT, stdlib-only, review `subprocess` use (`pdftotext` only), no shell=True in our runner |

## 16. Open decisions

None blocking. Defaults are chosen conservatively:

- `enabled: true` for the read-only pack in the user's config, `execution.enabled: false`.
- Daily universe limited to 200 symbols plus the current portfolio/watchlist.
- Demo is the only allowed execution environment until the demo runbook passes.
- Automatic buys remain off; tickets are advisory.

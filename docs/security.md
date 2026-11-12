# Security & Execution Boundaries

This document describes the **actual** implementation, not an idealised one.
Read it before trusting any "read-only" claim.

## Three layers, three different contracts

1. **Read-only portfolio analysis** (`trading212/` package + `Trading212Auth`).
   - `Trading212Auth.make_request` raises `ValueError` for any non-GET method.
   - `Trade212Client` only exposes GET helpers. No order endpoints exist here.
   - This is the layer the main pipeline uses for the live account.

2. **Demo order execution** (`investment_engine/day_trader/broker/t212_orders.py`).
   - `T212OrderClient` supports GET, POST (market/limit/stop/stop-limit) and
     DELETE (cancel). It targets `https://demo.trading212.com` when
     `environment="demo"` and `https://live.trading212.com` when `"live"`.
   - Demo POST/DELETE are allowed at the low level. The higher-level guard
     (`guard.evaluate`) and `execute_demo_plan` enforce demo-only execution:
     - `execution.enabled` must be true, `execution.environment == "demo"`.
     - `T212_DEMO_ORDER_ENABLED=1` (or `T212_ORDER_ENABLED=1`) and
       `T212_ORDER_ENV=demo` must match.
     - reconciliation must be `PASS`, account currency must be EUR, kill switch
       file must be absent, daily order/loss limits respected, notional cap
       respected, and manual approval present (or `auto_approve` in demo).
     - `execute_demo_plan` additionally refuses to run unless
       `client.environment == "demo"` and consults `order_ledger` for
       one-order-per-symbol-and-side-per-New-York-day deduplication.
   - The client host is bound to the `environment` argument at construction;
     a demo client can never reach the live host by URL confusion.

3. **Live-capable low-level integration** (same `T212OrderClient`, environment
   `"live"`). Retained intentionally for mirroring live positions into the
   demo account (`mirror_to_demo`, reads live positions, places demo orders).
   - POST/DELETE on a live client are blocked unless **both**
     `T212_LIVE_ORDER_ENABLED=1` **and** `T212_LIVE_ACK=I_UNDERSTAND_LIVE_TRADING`
     (and the value matches `execution.live_ack` in config).
   - `auto_approve` is forbidden in live mode; live mode also requires
     `execution.live_ack` to be set in config (validated by `DayTraderConfig`).
   - No shipped configuration sets these. Live execution is disabled by default.

## Environment variables

| Variable | Effect |
|---|---|
| `TRADING212_API_KEY`, `TRADING212_API_SECRET`, `TRADING212_ACCOUNT_ID` | Broker credentials (read-only key recommended) |
| `TRADING212_ENABLED` | Enable broker integration |
| `T212_DEMO_ORDER_ENABLED` / `T212_ORDER_ENABLED` | Allow demo execution |
| `T212_ORDER_ENV` | Must equal `demo` or `live` to match config |
| `T212_LIVE_ORDER_ENABLED` | Enable low-level live writes (default 0) |
| `T212_LIVE_ACK` | Must equal `I_UNDERSTAND_LIVE_TRADING` |
| `T212_DEMO_ALLOW_UNVERIFIED_RECON` | Treat missing recon as PASS in demo (opt-in) |
| `API_ONLY` / `LOAD_GUARD` | Provider execution mode / load guard kill switch |

## Authentication contract

Trading212 uses HTTP Basic Authentication: the API key is the username and
the password is left empty (`Authorization: Basic base64(api_key:)`). An
optional api_secret, if supplied, is used as the password. Verify against
the current official API documentation before changing this.

## Kill switch

A file at `data/day_trader/KILL_SWITCH` blocks all execution (checked by
`guard.evaluate`). `cleanup.bat` / `purge_outputs.bat` never touch `history/`.

## Secrets and data

- `api.env`, `portfolio_config.json`, `investment_policy.json`,
  `custom_rules.json`, `history/`, `data/`, `reports/`, `results/` are
  gitignored and must never be committed.
- Logs redact `Authorization` / `Bearer` / `key=` values.
- News is sanitized for prompt-injection shapes before use.
- Outbound traffic is GET-only market data plus configured LLM endpoints;
  queries carry public identifiers only.

## Residual risk

- The low-level client is live-capable by construction; safety depends on
  environment variables and the host binding, not on the absence of code.
- Demo execution places real orders on the demo account; the demo account
  is paper money but the code path is the same shape as a live one.
- Tests mock all broker interactions; no test makes a real broker request.
- Third-party feed quality and LLM output are untrusted inputs.
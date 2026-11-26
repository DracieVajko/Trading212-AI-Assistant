# Security & Execution Boundaries

This document describes the **actual** implementation, not an idealised one.
Read it before trusting any "read-only" claim.

## Secret storage (outside the workspace)

Credentials are **never** stored in the project tree. They live in an external
file:

```
~/.portfolio-secrets/api.env   (Windows: C:\\Users\\<you>\\.portfolio-secrets\\api.env)
```

Override the location with `PORTFOLIO_SECRETS_FILE`.

- `investment_engine.secrets.load_secrets()` reads this file into `os.environ`
  at startup. The Python process needs the values; the agent (OpenCode) does
  not.
- `opencode.json` denies `read`/`edit`/`glob`/`external_directory`/`shell`
  access to `*.env`, `*.env.*` and `~/.portfolio-secrets/**`, so the agent
  cannot open or print the file even if asked. See `SECRET_POLICY.md`.
- `api.env.example` in the repo contains only placeholders and is safe to
  commit.
- `verify_environment.py` still checks that no secret file is tracked by git.

## Three layers, three different contracts

1. **Read-only portfolio analysis** (`trading212/` package + `Trading212Auth`).
   - `Trading212Auth.make_request` raises `ValueError` for any non-GET method.
   - `Trade212Client` only exposes GET helpers. No order endpoints exist here.
   - This is the layer the main pipeline uses for the live account snapshot.

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

3. **Live order execution** (same `T212OrderClient`, environment `"live"`).
   - Enabled only when `T212_LIVE_ORDER_ENABLED=1`,
     `T212_LIVE_ACK=I_UNDERSTAND_LIVE_TRADING` (matching `execution.live_ack`)
     and `T212_LIVE_BUY_AUTO_APPROVE=1`.
   - Both BUY and SELL are allowed when `live_buy_auto_approve` is set;
     otherwise live SELL requires `manual_approval` (no auto-approve).
   - Per-order caps: `max_order_eur` (default 50), `max_sell_eur` (default 100).
   - `auto_approve` is forbidden in live mode unless `live_buy_auto_approve`.
   - Stop-loss / take-profit orders default to GTC (no 24h expiry).
   - No shipped configuration enables live execution; it is opt-in via env.

| Variable | Effect |
|---|---|
| `TRADING212_API_KEY`, `TRADING212_API_SECRET`, `TRADING212_ACCOUNT_ID` | Broker credentials (read-only key recommended) |
| `TRADING212_ENABLED` | Enable broker integration |
| `T212_DEMO_ORDER_ENABLED` / `T212_ORDER_ENABLED` | Allow demo execution |
| `T212_ORDER_ENV` | Must equal `demo` or `live` to match config |
| `T212_LIVE_ORDER_ENABLED` | Enable low-level live writes (default 0) |
| `T212_LIVE_ACK` | Must equal `I_UNDERSTAND_LIVE_TRADING` |
| `T212_LIVE_BUY_AUTO_APPROVE` | Auto-approve live trades (buys + sells) when 1 |
| `T212_MAX_SELL_EUR` | (config) per-sell cap on live/demo (default 100 EUR) |
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

- Secrets live in `~/.portfolio-secrets/api.env` (outside the workspace, outside git).
  Loaded by `investment_engine.secrets.load_secrets()`. The agent (OpenCode)
  is blocked by `opencode.json` permission rules from reading `*.env` or the
  secrets directory. See `SECRET_POLICY.md`.
- `api.env.example` in the repo contains only placeholders and is safe to commit.
- `portfolio_config.json`, `investment_policy.json`, `custom_rules.json`,
  `history/`, `data/`, `reports/`, `results/` are gitignored and must never be committed.
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
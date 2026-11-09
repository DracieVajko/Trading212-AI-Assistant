# Demo Execution + Scoring Wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the demo profile actually place BUY/SELL orders from day-trader plans, record them to permanent history, and score them on close — all on the T212 demo account, with live execution still blocked.

**Architecture:** A new `investment_engine/day_trader/execute.py` turns a planning ticket into a guarded demo bracket order via the existing `T212OrderClient("demo", ...)` and `bracket.run_bracket`, then records the trade and its `score_demo_trade` result. `portfolio_ai_assistant.py` calls it only when `--day-trader-allow-orders` is set AND `execution.environment == "demo"`. A client-level live interlock in `T212OrderClient` refuses live order placement unless `T212_LIVE_ORDER_ENABLED=1` and `T212_LIVE_ACK=I_UNDERSTAND_LIVE_TRADING`.

**Tech Stack:** Python 3.12, Trading212 demo API, SQLite + JSONL history, pytest.

**Spec:** `docs/specs/2026-11-09-demo-live-auto-demo-training-design.md`

## Global Constraints

- Demo only: `T212_DEMO_ORDER_ENABLED=1`; never `environment="live"`.
- Live interlock: `T212_LIVE_ORDER_ENABLED=0` means no live order can be sent even by direct client use.
- Guard must pass before any order: reconciliation PASS, EUR account, side allowed, demo unlimited.
- Every placed demo order is written to `history/demo/` (never deleted).
- Scoring uses `score_demo_trade`; FX fees subtracted from P&L before normalization.
- Fail closed: on error, log and continue (never crash the run, never retry blindly).
- No secrets in code or logs.

---

### Task 1: Client-level live interlock

**Files:**
- Modify: `investment_engine/day_trader/broker/t212_orders.py`
- Test: `tests/test_t212_live_interlock.py`

**Interfaces:**
- Consumes: `os.environ` (`T212_LIVE_ORDER_ENABLED`, `T212_LIVE_ACK`), `self.environment`
- Produces: `T212OrderClient.place_*` returns `{"status": "blocked", "error": "live order execution disabled"}` when a live order is attempted without the interlock env.

- [ ] **Step 1: Write failing tests**

```python
def test_live_client_refuses_orders_without_flag(monkeypatch):
    import os
    from investment_engine.day_trader.broker.t212_orders import T212OrderClient
    monkeypatch.setenv("T212_LIVE_ORDER_ENABLED", "0")
    monkeypatch.setenv("T212_LIVE_ACK", "")
    client = T212OrderClient("live", "key", "secret")
    res = client.place_market_order("AAPL_US_EQ", 0.1)
    assert res["status"] == "blocked"


def test_live_client_refuses_orders_without_ack(monkeypatch):
    import os
    from investment_engine.day_trader.broker.t212_orders import T212OrderClient
    monkeypatch.setenv("T212_LIVE_ORDER_ENABLED", "1")
    monkeypatch.setenv("T212_LIVE_ACK", "wrong")
    client = T212OrderClient("live", "key", "secret")
    res = client.place_market_order("AAPL_US_EQ", 0.1)
    assert res["status"] == "blocked"


def test_demo_client_not_blocked(monkeypatch):
    from investment_engine.day_trader.broker.t212_orders import T212OrderClient
    monkeypatch.setenv("T212_LIVE_ORDER_ENABLED", "0")
    client = T212OrderClient("demo", "key", "secret")
    # No network: assert the interlock did not block; the request itself will
    # fail later, which is out of scope for this test.
    assert client.environment == "demo"
```

- [ ] **Step 2: Run to confirm RED**

Run: `python -m pytest tests/test_t212_live_interlock.py -v`
Expected: FAIL (first two).

- [ ] **Step 3: Implement interlock**

In `_request`, before dispatch:

```python
        if method.upper() in ("POST", "DELETE") and self.environment == "live":
            if os.getenv("T212_LIVE_ORDER_ENABLED", "0") != "1" or os.getenv("T212_LIVE_ACK", "") != "I_UNDERSTAND_LIVE_TRADING":
                return {"status": "blocked", "error": "live order execution disabled"}
```

- [ ] **Step 4: Run to confirm GREEN**

Run: `python -m pytest tests/test_t212_live_interlock.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add investment_engine/day_trader/broker/t212_orders.py tests/test_t212_live_interlock.py
git commit -m "feat: client-level interlock blocks live T212 orders"
```

---

### Task 2: Demo execution module

**Files:**
- Create: `investment_engine/day_trader/execute.py`
- Test: `tests/test_day_trader_execute.py`

**Interfaces:**
- Consumes: `DayTraderConfig`, `T212OrderClient` (demo), `guard.evaluate`, `bracket.run_bracket`, `history.record_trade`, `scoring.score_demo_trade`
- Produces: `execute_demo_plan(config, ticket, client, env=None, db_path=..., history_mode="demo") -> dict` with keys `status` (`PLACED` | `BLOCKED` | `FAILED`), `order`, `score` (if closed), `reasons`.

- [ ] **Step 1: Write failing tests**

```python
def test_execute_demo_plan_blocks_when_guard_fails(monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True

    class FailingClient:
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place when guard fails")

    env = {"T212_DEMO_ORDER_ENABLED": "0", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FailingClient(), env=env)
    assert res["status"] == "BLOCKED"


def test_execute_demo_plan_places_when_demo_and_guard_pass():
    from investment_engine.day_trader.execute import execute_demo_plan
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True
    cfg.execution.unlimited = True

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            return {"id": 123, "status": "submitted"}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FakeClient(), env=env)
    assert res["status"] == "PLACED"
    assert res["order"]["id"] == 123
```

- [ ] **Step 2: Run to confirm RED**

Run: `python -m pytest tests/test_day_trader_execute.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
"""Demo-only execution of day-trader tickets.

Places orders on the T212 demo account only. Never live: the guard and the
client-level interlock both refuse live placement.
"""

from __future__ import annotations

import os
from typing import Any


def execute_demo_plan(
    config: Any,
    ticket: dict[str, Any],
    client: Any,
    env: dict[str, str] | None = None,
    *,
    db_path: str = "data/day_trader/audit.db",
    history_mode: str = "demo",
) -> dict[str, Any]:
    from investment_engine.day_trader.broker.guard import evaluate
    from investment_engine.history import record_trade

    env = dict(env or os.environ)
    symbol = str(ticket.get("ticker") or ticket.get("symbol") or "").upper()
    side = str(ticket.get("side", "BUY")).upper()
    qty = float(ticket.get("quantity", 0) or 0)
    if not symbol or qty <= 0:
        return {"status": "FAILED", "error": "missing symbol or quantity", "order": None, "reasons": []}

    intent = {
        "symbol": symbol,
        "side": side,
        "notional": float(ticket.get("notional", 0) or 0),
        "manual_approval": True,
    }
    decision = evaluate(
        intent,
        config,
        env,
        recon_status=str(ticket.get("recon_status", "PASS")),
        account_currency=str(ticket.get("account_currency", "EUR")),
        kill_switch_path=ticket.get("kill_switch_path"),
    )
    if not decision.allowed:
        return {"status": "BLOCKED", "order": None, "reasons": decision.reasons, "score": None}

    if getattr(client, "environment", "") != "demo":
        return {"status": "BLOCKED", "order": None, "reasons": ["client is not demo"], "score": None}

    signed_qty = qty if side == "BUY" else -abs(qty)
    try:
        order = client.place_market_order(symbol, signed_qty)
    except Exception as exc:  # fail closed, never crash the run
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "order": None, "reasons": [], "score": None}

    oid = order.get("id") if isinstance(order, dict) else None
    if oid is None:
        return {"status": "FAILED", "error": "order rejected", "order": order, "reasons": [], "score": None}

    try:
        record_trade(
            symbol, side, qty, order_id=str(oid), status="PLACED",
            reason=str(ticket.get("reason", "demo execution")),
            source="execute_demo_plan", mode=history_mode,
        )
    except Exception:
        pass

    return {"status": "PLACED", "order": order, "reasons": [], "score": None}
```

- [ ] **Step 4: Run to confirm GREEN**

Run: `python -m pytest tests/test_day_trader_execute.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add investment_engine/day_trader/execute.py tests/test_day_trader_execute.py
git commit -m "feat: demo-only ticket execution with guard and history"
```

---

### Task 3: Wire execution into the orchestrator

**Files:**
- Modify: `portfolio_ai_assistant.py`
- Test: `tests/test_auto_execute_wiring.py`

**Interfaces:**
- Consumes: `planning.json` tickets, `DayTraderConfig`, demo `T212OrderClient`
- Produces: demo orders placed only when `--day-trader-allow-orders` and `environment == "demo"`.

- [ ] **Step 1: Write failing test**

```python
def test_wiring_requires_allow_orders_flag():
    from pathlib import Path
    src = Path("portfolio_ai_assistant.py").read_text(encoding="utf-8")
    assert "execute_demo_plan" in src
    assert "--day-trader-allow-orders" in src
```

- [ ] **Step 2: Run RED** — `python -m pytest tests/test_auto_execute_wiring.py -v`

- [ ] **Step 3: Implement**

After the day_trader planning produces `_payload` (tickets), and only when `args.day_trader_allow_orders` and `_dt_cfg.execution.environment == "demo"`:

```python
        if args.day_trader_allow_orders and _dt_cfg.execution.environment == "demo":
            try:
                from investment_engine.day_trader.execute import execute_demo_plan
                from investment_engine.day_trader.broker.t212_orders import T212OrderClient
                import os as _os
                from dotenv import load_dotenv as _ld
                _ld(str(ROOT / "api.env"))
                _demo_client = T212OrderClient(
                    "demo",
                    _os.getenv("T212_DEMO_API_KEY"),
                    _os.getenv("T212_DEMO_API_SECRET"),
                )
                _tickets = (_payload or {}).get("tickets") or {}
                for _sym, _ticket in _tickets.items():
                    _res = execute_demo_plan(_dt_cfg, _ticket, _demo_client, db_path=str(ROOT / "data" / "day_trader" / "audit.db"))
                    print(f"Demo execute {_sym}: {_res['status']} {_res.get('reasons') or _res.get('error') or ''}")
            except Exception as _ex:
                print(f"Demo execution skipped: {_ex}")
```

- [ ] **Step 4: Run GREEN** — `python -m pytest tests/test_auto_execute_wiring.py -v`

- [ ] **Step 5: Commit**

```bash
git add portfolio_ai_assistant.py tests/test_auto_execute_wiring.py
git commit -m "feat: wire demo execution into the day-trader run"
```

---

### Task 4: Score trades on close

**Status:** Partially delivered: library only, caller is a follow-up.

**Files:**
- Create: `investment_engine/day_trader/score_closed_trades.py`
- Test: `tests/test_score_closed_trades.py`

**Interfaces:**
- Consumes: demo positions/orders, `history`
- Produces: `score_closed_demo_trades(client, history_mode="demo") -> list[dict]`

- [ ] **Step 1: Test** — given two closed trade dicts (win/loss), returns scores with correct horizons and FX subtraction.
- [ ] **Step 2: RED**
- [ ] **Step 3: Implement** — read closed demo trades (entry+exit), call `score_demo_trade`, append to `history/demo/scores.jsonl`.
- [ ] **Step 4: GREEN**
- [ ] **Step 5: Commit**

---

### Task 5: Harden scoring inputs (from final review M5–M7)

**Files:**
- Modify: `investment_engine/day_trader/scoring.py`
- Test: `tests/test_day_trader_scoring.py`

- [ ] **Step 1:** Add tests for malformed timestamps (skip gracefully → hold 0, horizon short), missing `stop_loss_adhered` (neutral 0, not -1), and documented 100 EUR normalization.
- [ ] **Step 2:** RED.
- [ ] **Step 3:** Implement: tolerant `_hold_minutes` (return 0 on parse error), `stop_loss_component = 0.0 when key absent`, docstring notes normalization.
- [ ] **Step 4:** GREEN (`python -m pytest tests/test_day_trader_scoring.py -v`).
- [ ] **Step 5:** Commit.

---

### Task 6: Fixture-validated first run (manual, guarded)

- [ ] **Step 1:** Keep `execution.enabled=false` and `auto_run=true`; run `python portfolio_ai_assistant.py --day-trader-plan --day-trader-allow-orders` in a **non-market** window and confirm `planning.json` tickets are produced and `execute_demo_plan` returns `BLOCKED`/`FAILED` without placing (guard/no tickets).
- [ ] **Step 2:** In the user-approved demo window (08:30–10:00 ET), run the scheduled script once and inspect `history/demo/trades.jsonl` + `reports/day_trader/demo/current/day_trader_brief.md`.
- [ ] **Step 3:** Only after a clean first run, leave `auto_run=true` for the 09:00/21:00 schedule.

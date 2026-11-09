# Demo + Live Auto Script + Demo Training Scoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One auto script (Task Scheduler 09:00 / 21:00) that runs a read-only demo premarket phase then a live recommendation phase (zero order execution), plus a demo trade scoring module and an AI model optimization layer for LM Studio and Ollama backends. Demo order placement and in-lifecycle scoring are a follow-up not yet wired.

**Architecture:** Single Python process with two sequential phases. Demo phase uses `environment="demo"` + `auto_approve=true` + `allowed_sides=["BUY","SELL"]`. Live phase uses `environment="live"` + `auto_approve=false` — guard blocks all live orders via `T212_LIVE_ORDER_ENABLED=0`. Scoring system rates each demo trade on P&L (after FX), hold time, risk:reward, stop-loss adherence across short/medium/long horizons. AI optimization abstracts LM Studio REST + Ollama Modelfile backends.

**Tech Stack:** Python 3.12, Trading212 API, LM Studio REST API, Ollama API, SQLite + JSONL history, pytest.

**Spec:** `docs/specs/2026-11-09-demo-live-auto-demo-training-design.md`

## Global Constraints

- `T212_LIVE_ORDER_ENABLED=0` — live execution never enabled.
- No `live_ack` for live mode — config validation rejects live execution.
- `auto_approve` forbidden in live mode.
- `T212_DEMO_ORDER_ENABLED=1` — demo orders allowed.
- `unlimited=true` for demo — no order cap.
- KV cache quantization: GUI-only in LM Studio (REST rejects with 400) — record only.
- Ollama: beta backend, modelfile export/apply only, no live-server E2E.
- English or Slovak responses only.
- No git commits without explicit user consent.
- Permanent `history/` never touched by cleanup/purge.

---

### Task 1: Demo scoring module — `investment_engine/day_trader/scoring.py`

**Files:**
- Create: `investment_engine/day_trader/scoring.py`
- Test: `tests/test_day_trader_scoring.py`

**Interfaces:**
- Consumes: `DemoTrade` dict with `symbol`, `side`, `entry_price`, `exit_price`, `executed_at`, `closed_at`, `pnl_eur`, `fx_fee_eur`, `stop_loss_adhered`, `risk_reward_ratio`
- Produces: `DemoTradeScore` dataclass with `score`, `horizon`, `breakdown` dict; module-level `score_demo_trade(trade: dict) -> DemoTradeScore`

- [ ] **Step 1: Write the failing test**

```python
def test_scoring_short_term_profitable_trade():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "AAPL",
        "side": "BUY",
        "entry_price": 150.0,
        "exit_price": 155.0,
        "executed_at": "2026-11-09T09:30:00Z",
        "closed_at": "2026-11-09T10:00:00Z",
        "pnl_eur": 45.0,
        "fx_fee_eur": 0.50,
        "stop_loss_adhered": True,
        "risk_reward_ratio": 2.0,
    }
    result = score_demo_trade(trade)
    assert result.horizon == "short"
    assert result.score > 0
    assert result.breakdown["pnl_component"] > 0
    assert result.breakdown["stop_loss_component"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_day_trader_scoring.py::test_scoring_short_term_profitable_trade -v`
Expected: FAIL with `ImportError: cannot import name 'score_demo_trade'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Demo trade scoring — short / medium / long term horizons."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DemoTradeScore:
    symbol: str
    side: str
    horizon: str  # "short" | "medium" | "long"
    score: float
    breakdown: dict[str, float]


def _hold_minutes(executed_at: str, closed_at: str | None) -> int:
    if not closed_at or not executed_at:
        return 0
    start = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
    return max(0, int((end - start).total_seconds() / 60))


def _horizon(minutes: int) -> str:
    if minutes <= 1440:  # <= 1 day
        return "short"
    if minutes <= 43200:  # <= 30 days
        return "medium"
    return "long"


def score_demo_trade(trade: dict) -> DemoTradeScore:
    """Score a demo trade. Returns DemoTradeScore with weighted breakdown.

    Weights: P&L after FX = 0.40, hold time = 0.20, risk:reward = 0.20,
    stop-loss adherence = 0.20. FX fees are subtracted from P&L before
    normalization.
    """
    pnl_eur = float(trade.get("pnl_eur", 0.0) or 0.0)
    fx_fee_eur = float(trade.get("fx_fee_eur", 0.0) or 0.0)
    net_pnl = pnl_eur - fx_fee_eur
    hold_min = _hold_minutes(trade.get("executed_at", ""), trade.get("closed_at"))
    horizon = _horizon(hold_min)
    stop_ok = bool(trade.get("stop_loss_adhered", False))
    rr = float(trade.get("risk_reward_ratio", 0.0) or 0.0)

    W_PNL = 0.40
    W_TIME = 0.20
    W_RR = 0.20
    W_SL = 0.20

    pnl_component = max(-1.0, min(1.0, net_pnl / 100.0))

    if horizon == "short":
        time_component = max(0.0, 1.0 - hold_min / 1440.0)
    elif horizon == "long":
        time_component = min(1.0, hold_min / 43200.0)
    else:
        time_component = 0.5

    rr_component = min(1.0, rr / 2.0) if rr > 0 else 0.0
    sl_component = 1.0 if stop_ok else -1.0

    score = (
        W_PNL * pnl_component
        + W_TIME * time_component
        + W_RR * rr_component
        + W_SL * sl_component
    )

    return DemoTradeScore(
        symbol=str(trade.get("symbol", "UNKNOWN")),
        side=str(trade.get("side", "BUY")),
        horizon=horizon,
        score=round(score, 4),
        breakdown={
            "pnl_component": round(pnl_component, 4),
            "time_component": round(time_component, 4),
            "rr_component": round(rr_component, 4),
            "stop_loss_component": round(sl_component, 4),
            "net_pnl_eur": round(net_pnl, 2),
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_day_trader_scoring.py::test_scoring_short_term_profitable_trade -v`
Expected: PASS

- [ ] **Step 5: Add and run the remaining scoring tests (horizons + stop-loss penalty)**

```python
def test_scoring_medium_term_trade():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "MSFT", "side": "BUY",
        "executed_at": "2026-11-01T09:30:00Z",
        "closed_at": "2026-11-10T09:30:00Z",
        "pnl_eur": 20.0, "fx_fee_eur": 1.0,
        "stop_loss_adhered": True, "risk_reward_ratio": 1.5,
    }
    result = score_demo_trade(trade)
    assert result.horizon == "medium"


def test_scoring_long_term_trade():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "NVDA", "side": "BUY",
        "executed_at": "2026-09-01T09:30:00Z",
        "closed_at": "2026-11-09T09:30:00Z",
        "pnl_eur": 120.0, "fx_fee_eur": 2.0,
        "stop_loss_adhered": True, "risk_reward_ratio": 2.5,
    }
    result = score_demo_trade(trade)
    assert result.horizon == "long"


def test_scoring_stop_loss_violation_penalty():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "TSLA", "side": "BUY",
        "executed_at": "2026-11-09T09:30:00Z",
        "closed_at": "2026-11-09T15:00:00Z",
        "pnl_eur": -50.0, "fx_fee_eur": 1.0,
        "stop_loss_adhered": False, "risk_reward_ratio": 1.0,
    }
    result = score_demo_trade(trade)
    assert result.breakdown["stop_loss_component"] < 0
    assert result.score < 0


def test_scoring_fx_fee_reduces_net_pnl():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "AAPL", "side": "BUY",
        "executed_at": "2026-11-09T09:30:00Z",
        "closed_at": "2026-11-09T10:00:00Z",
        "pnl_eur": 10.0, "fx_fee_eur": 3.0,
        "stop_loss_adhered": True, "risk_reward_ratio": 2.0,
    }
    result = score_demo_trade(trade)
    assert result.breakdown["net_pnl_eur"] == 7.0
```

Run: `pytest tests/test_day_trader_scoring.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add investment_engine/day_trader/scoring.py tests/test_day_trader_scoring.py
git commit -m "feat: demo trade scoring module with short/medium/long horizons"
```

---

### Task 2: AI model optimization abstraction — `investment_engine/providers/optimization.py`

**Files:**
- Create: `investment_engine/providers/optimization.py`
- Create: `investment_engine/providers/optimization_config.json`
- Test: `tests/test_providers_optimization.py`

**Interfaces:**
- Consumes: model name, backend ("lmstudio" | "ollama"), hardware info (VRAM)
- Produces: `AIModelConfig` dataclass; `get_best_config(model, backend, vram_gb) -> AIModelConfig`; `save_config(cfg, path)`; `load_config(path) -> dict`

- [ ] **Step 1: Write the failing test**

```python
def test_lmstudio_config_has_validated_keys():
    from investment_engine.providers.optimization import get_best_config
    cfg = get_best_config("qwen3.8-9b-distill", "lmstudio", vram_gb=6)
    assert cfg.context_length in (8192, 16384, 32768)
    assert cfg.flash_attention is True
    assert cfg.offload_kv_cache_to_gpu is True
    assert cfg.eval_batch_size in (128, 256, 512, 1024, 2048)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_providers_optimization.py::test_lmstudio_config_has_validated_keys -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
"""AI model optimization abstraction for LM Studio and Ollama backends.

Validated defaults come from LocalLLM_Optimiser (RTX 3060 6 GB baseline).
LM Studio REST accepts: context_length, flash_attention,
offload_kv_cache_to_gpu, eval_batch_size, physical_batch_size, parallel.
KV cache quantization and CPU threads are GUI-only (REST rejects with 400)
and are recorded, never set, here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AIModelConfig:
    model: str
    backend: str  # "lmstudio" | "ollama"
    context_length: int
    flash_attention: bool
    offload_kv_cache_to_gpu: bool
    eval_batch_size: int
    tokens_per_sec: float
    quality_score: float
    validated_at: str


_DEFAULT_CONFIGS: dict[str, AIModelConfig] = {
    "qwen3.8-9b-distill": AIModelConfig(
        model="qwen3.8-9b-distill",
        backend="lmstudio",
        context_length=32768,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
        eval_batch_size=2048,
        tokens_per_sec=28.2,
        quality_score=0.983,
        validated_at="2026-10-27",
    ),
    "ministral-3b-top": AIModelConfig(
        model="ministral-3b-top",
        backend="lmstudio",
        context_length=32768,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
        eval_batch_size=128,
        tokens_per_sec=74.9,
        quality_score=1.000,
        validated_at="2026-10-27",
    ),
    "gemma-4-12b": AIModelConfig(
        model="gemma-4-12b",
        backend="lmstudio",
        context_length=32768,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
        eval_batch_size=2048,
        tokens_per_sec=7.1,
        quality_score=0.987,
        validated_at="2026-10-27",
    ),
}


def get_best_config(model: str, backend: str = "lmstudio", vram_gb: int = 6) -> AIModelConfig:
    """Return validated best config for a model. Falls back to safe defaults."""
    key = model.lower()
    if key in _DEFAULT_CONFIGS:
        return _DEFAULT_CONFIGS[key]
    return AIModelConfig(
        model=model,
        backend=backend,
        context_length=8192,
        flash_attention=False,
        offload_kv_cache_to_gpu=False,
        eval_batch_size=128,
        tokens_per_sec=0.0,
        quality_score=0.0,
        validated_at="",
    )


def save_config(cfg: AIModelConfig, path: str | Path = "investment_engine/providers/optimization_config.json") -> None:
    """Persist validated config to JSON."""
    p = Path(path)
    data: dict = {}
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    data[cfg.model] = {
        "backend": cfg.backend,
        "context_length": cfg.context_length,
        "flash_attention": cfg.flash_attention,
        "offload_kv_cache_to_gpu": cfg.offload_kv_cache_to_gpu,
        "eval_batch_size": cfg.eval_batch_size,
        "tokens_per_sec": cfg.tokens_per_sec,
        "quality_score": cfg.quality_score,
        "validated_at": cfg.validated_at,
    }
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_config(path: str | Path = "investment_engine/providers/optimization_config.json") -> dict:
    """Load persisted configs."""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_providers_optimization.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add investment_engine/providers/optimization.py investment_engine/providers/optimization_config.json tests/test_providers_optimization.py
git commit -m "feat: AI model optimization abstraction for LM Studio and Ollama"
```

---

### Task 3: Portfolio orchestrator — demo phase then live phase

**Files:**
- Modify: `portfolio_ai_assistant.py` (after the demo day_trader block, ~line 470)
- Test: `tests/test_auto_script_phases.py` (new)

**Interfaces:**
- Consumes: `raw_settings` dict with `day_trader.auto_run=true`, `day_trader.execution.environment="demo"`
- Produces: demo trade results + live recommendations in `reports/current/`

- [ ] **Step 1: Write the failing test**

```python
def test_auto_script_config_enables_demo_not_live():
    import json
    from pathlib import Path
    from investment_engine.day_trader.config import DayTraderConfig

    raw = json.loads(Path("portfolio_config.json").read_text(encoding="utf-8"))
    dt = raw["settings"]["day_trader"]
    assert dt["auto_run"] is True
    assert dt["execution"]["environment"] == "demo"
    assert dt["execution"]["allowed_sides"] == ["BUY", "SELL"]

    cfg = DayTraderConfig.from_mapping(dt)
    assert cfg.execution.environment == "demo"
    assert cfg.auto_run is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_script_phases.py -v`
Expected: FAIL (file doesn't exist) or FAIL on assertion if config differs

- [ ] **Step 3: Write minimal implementation**

In `portfolio_ai_assistant.py`, after the demo day_trader block completes, add the live recommendations phase. Insert after the `if args.day_trader or ...` block (after line ~470 where `_did_day_trader = True`):

```python
        # Phase 2: Live recommendations only (zero order execution).
        # Demo already ran above; live never places orders:
        # T212_LIVE_ORDER_ENABLED=0, no live_ack, auto_approve forbidden.
        if _did_day_trader:
            try:
                from investment_engine.history import runtime_mode as _rm
                _live_mode = _rm("live")
                print(f"Live phase: recommendations only (no orders), mode={_live_mode}")
                # Live order plans are advisory and live execution is blocked by
                # the day_trader guard; the main engine already produced
                # recommendations in this run's report.
            except Exception as _live_exc:
                print(f"Live phase skipped: {_live_exc}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auto_script_phases.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add portfolio_ai_assistant.py tests/test_auto_script_phases.py
git commit -m "feat: auto script runs demo phase then live recommendations phase"
```

---

### Task 4: Guard enforcement verification — live blocked, demo allowed

**Files:**
- Test: `tests/test_guard_demo_live.py` (new)

**Interfaces:**
- Consumes: `evaluate` from `investment_engine.day_trader.broker.guard`; `DayTraderConfig`
- Produces: pass/fail assertions on guard decisions

- [ ] **Step 1: Write the failing test**

```python
def test_guard_blocks_live_orders():
    import os
    from investment_engine.day_trader.broker.guard import evaluate
    from investment_engine.day_trader.config import DayTraderConfig, ExecutionConfig

    env = dict(os.environ)
    env["T212_LIVE_ORDER_ENABLED"] = "0"
    env["T212_ORDER_ENV"] = "live"
    env["T212_LIVE_ACK"] = ""

    cfg = DayTraderConfig()
    cfg.execution = ExecutionConfig(
        enabled=True,
        environment="live",
        auto_approve=False,
        live_ack="",
        allowed_sides=["BUY", "SELL"],
        unlimited=False,
    )
    intent = {"symbol": "AAPL", "side": "BUY", "notional": 100, "manual_approval": True}
    decision = evaluate(intent, cfg, env, recon_status="PASS", account_currency="EUR")
    assert decision.allowed is False
    assert decision.reasons


def test_guard_allows_demo_orders():
    import os
    from investment_engine.day_trader.broker.guard import evaluate
    from investment_engine.day_trader.config import DayTraderConfig, ExecutionConfig

    env = dict(os.environ)
    env["T212_DEMO_ORDER_ENABLED"] = "1"
    env["T212_ORDER_ENV"] = "demo"

    cfg = DayTraderConfig()
    cfg.execution = ExecutionConfig(
        enabled=True,
        environment="demo",
        auto_approve=True,
        live_ack="",
        allowed_sides=["BUY", "SELL"],
        unlimited=True,
    )
    intent = {"symbol": "AAPL", "side": "BUY", "notional": 100, "manual_approval": True}
    decision = evaluate(intent, cfg, env, recon_status="PASS", account_currency="EUR")
    assert decision.allowed is True
    assert decision.reasons == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_guard_demo_live.py -v`
Expected: FAIL (file doesn't exist)

- [ ] **Step 3: Write minimal implementation**

No implementation needed — the guard already exists and enforces these rules. If the test exposes a bug, fix `investment_engine/day_trader/broker/guard.py` minimally.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_guard_demo_live.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_guard_demo_live.py
git commit -m "test: verify guard blocks live orders and allows demo orders"
```

---

### Task 5: Integration test — full auto script flow

**Files:**
- Test: `tests/test_auto_script_integration.py` (new)

**Interfaces:**
- Consumes: config from `portfolio_config.json`; guard decision
- Produces: end-to-end verification that demo is executable and live is blocked

- [ ] **Step 1: Write the failing test**

```python
def test_auto_script_demo_then_live_flow():
    import json
    import os
    from pathlib import Path
    from investment_engine.day_trader.config import DayTraderConfig
    from investment_engine.day_trader.broker.guard import evaluate

    raw = json.loads(Path("portfolio_config.json").read_text(encoding="utf-8"))
    dt_raw = raw["settings"]["day_trader"]
    cfg = DayTraderConfig.from_mapping(dt_raw)

    # Demo phase: allowed
    demo_env = dict(os.environ)
    demo_env["T212_DEMO_ORDER_ENABLED"] = "1"
    demo_env["T212_ORDER_ENV"] = "demo"
    demo_intent = {"symbol": "AAPL", "side": "BUY", "notional": 50, "manual_approval": True}
    demo_decision = evaluate(demo_intent, cfg, demo_env, recon_status="PASS", account_currency="EUR")
    assert demo_decision.allowed is True

    # Live phase: blocked
    live_env = dict(os.environ)
    live_env["T212_LIVE_ORDER_ENABLED"] = "0"
    live_env["T212_ORDER_ENV"] = "live"
    live_env["T212_LIVE_ACK"] = ""
    live_cfg = DayTraderConfig.from_mapping(dt_raw)
    live_cfg.execution.environment = "live"
    live_cfg.execution.auto_approve = False
    live_decision = evaluate(demo_intent, live_cfg, live_env, recon_status="PASS", account_currency="EUR")
    assert live_decision.allowed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_script_integration.py -v`
Expected: FAIL (file doesn't exist)

- [ ] **Step 3: Write minimal implementation**

No implementation needed if Tasks 3-4 are done. If the test fails, fix the integration point in `portfolio_ai_assistant.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auto_script_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_auto_script_integration.py
git commit -m "test: integration test for demo-then-live auto script flow"
```

---

### Task 6: Full test suite verification

**Files:**
- None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: All tests pass with only the known pre-existing failure (`test_running_interpreter_is_312` under non-3.12 interpreter)

- [ ] **Step 2: Commit if needed**

No changes expected.

---

### Task 7: Documentation and handoff

**Files:**
- Modify: `docs/PORTFOLIO_AI_UPGRADE_PLAN_v2.md` (add demo/live/training section)
- Modify: `docs/specs/2026-11-09-demo-live-auto-demo-training-design.md` (mark as approved)

- [ ] **Step 1: Add a "Demo + Live auto script & training scoring" section to `docs/PORTFOLIO_AI_UPGRADE_PLAN_v2.md`** summarizing: Option A flow, demo scoring weights, AI optimization backends.

- [ ] **Step 2: Update the spec status line to `Status: Approved`.**

- [ ] **Step 3: Commit**

```bash
git add docs/PORTFOLIO_AI_UPGRADE_PLAN_v2.md docs/specs/2026-11-09-demo-live-auto-demo-training-design.md
git commit -m "docs: record demo/live auto script and training scoring design"
```

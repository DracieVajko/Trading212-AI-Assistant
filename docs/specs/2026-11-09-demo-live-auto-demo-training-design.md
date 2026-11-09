# Spec: Unified Auto Script — Demo + Live + Demo Training Scoring

**Date:** 2026-11-09
**Author:** Portfolio AI Assistant team
**Status:** Approved

## Goal

One auto script (Task Scheduler 09:00 / 21:00) that runs two phases per execution:
1. **Demo phase** — currently runs the read-only premarket scan and writes the day-trader brief. Demo order placement and in-lifecycle scoring are a planned follow-up (not yet wired).
2. **Live phase** — AI recommendations only, zero order execution (live remains locked).

Plus:
- AI model optimization layer (LM Studio + Ollama backends) using LocalLLM_Optimiser patterns.
- Demo training scoring: points up/down per trade weighted by P&L (after FX fees), hold time, risk:reward, stop-loss adherence.

## Scope

In scope:
- `run_automated.bat` — passes `--day-trader --day-trader-allow-orders` to run the read-only premarket day-trader phase.
- `portfolio_ai_assistant.py` — runs the demo premarket scan/brief, then the live phase, in one process.
- `investment_engine/day_trader/config.py` — `auto_run=true`, `environment="demo"`, `allowed_sides=["BUY","SELL"]` (config only; no orders are placed yet).
- `investment_engine/day_trader/premarket.py` — demo trading window 08:30–10:00 ET, `allow_short=True`.
- `investment_engine/day_trader/scoring.py` (NEW) — demo trade scoring module, short/medium/long term buckets (unit-tested; not wired into the trade lifecycle).
- `investment_engine/providers/optimization.py` (NEW) — AI model optimization abstraction for LM Studio + Ollama.
- `investment_engine/providers/optimization_config.json` (NEW) — persisted best settings per model.
- Guard already blocks live execution (`T212_LIVE_ORDER_ENABLED=0`, no `live_ack`, `auto_approve` forbidden live).
- History: demo trades recorded to `history/demo/` (permanent, never purged) — routine path exists; no live demo trades yet.

Follow-up (not in this branch):
- Demo order placement on the T212 demo account (delivered: demo-only market entry plus optional stop/target exits, gated by `--day-trader-allow-orders` and `environment="demo"`).
- In-lifecycle demo trade scoring: wiring `scoring.py` into the demo trade path so each trade is scored when executed/closed.
- Lifecycle scoring caller (score_closed_trades is a library; wiring to closed demo trades is a follow-up)

Out of scope:
- Live order execution (explicitly forbidden).
- Ollama live-server E2E (beta in LocalLLM_Optimiser, mocked only).
- vLLM / llama.cpp (phase-2 stub only).
- GUI for scoring (CLI + JSONL only).
- UI / frontend changes.

## Architecture

```
Scheduled Task (09:00 / 21:00)
  └─ run_automated.bat
       └─ portfolio_ai_assistant.py
            ├─ Phase 1: DEMO (read-only premarket scan; order placement not wired)
            │     ├─ Premarket scan → watchlist
            │     ├─ Planning (entry/exit/stop/target via bracket emulation)
            │     ├─ Guard evaluate (demo env → ALLOWED)
            │     ├─ [NOT YET WIRED — follow-up] Place demo orders (market + stop + target)
            │     ├─ [NOT YET WIRED — follow-up] Score each trade (scoring.py is unit-tested only)
            │     ├─ Record to history/demo/ (JSONL + SQLite)
            │     └─ Write reports/day_trader/<mode>/current/day_trader_brief.md
            │
            └─ Phase 2: LIVE (recommendations only)
                  ├─ AI recommendations (qwen3.6 decision + Gemma writer)
                  ├─ Order plans (informational only)
                  ├─ Guard evaluate (live env → BLOCKED)
                  ├─ Print live-phase notice (recommendations only, no orders)
                  └─ Main engine writes the live report
```

## Data Model

**DemoTradeScore** (dataclass):
- symbol: str
- side: str ("BUY"/"SELL")
- horizon: str ("short" | "medium" | "long")
- score: float (weighted sum)
- breakdown: dict[str, float] (per-component scores)

**AIModelConfig** (dataclass):
- model: str
- backend: str ("lmstudio" | "ollama")
- context_length: int
- flash_attention: bool
- offload_kv_cache_to_gpu: bool
- eval_batch_size: int
- tokens_per_sec: float
- quality_score: float
- validated_at: str (ISO)

## Scoring Formula

```
score = pnl_weight * normalized_pnl
      + time_weight * time_score
      + rr_weight * rr_score
      + sl_weight * stop_loss_score
```

- `pnl_weight = 0.40` — profit/loss after FX fees (dominant); fees are subtracted from P&L before normalization.
- `time_weight = 0.20` — hold time vs. horizon target (shorter = better for short term).
- `rr_weight = 0.20` — risk:reward ratio (≥ 1:2 → full points).
- `sl_weight = 0.20` — stop-loss adherence (honored → +1, violated → -1, i.e. -0.20 weighted).
- FX fees are subtracted from P&L before normalization (no separate penalty term).

Horizon buckets:
- **short:** hold ≤ 1 day
- **medium:** 1 day < hold ≤ 30 days
- **long:** hold > 30 days

## Constraints

- Live execution: `T212_LIVE_ORDER_ENABLED=0`, no `live_ack`, `auto_approve=false` live. Never changed by this spec.
- Demo execution: `T212_DEMO_ORDER_ENABLED=1`, `unlimited=true`, `max_daily_orders=1000`.
- English or Slovak responses only.
- No git commits without explicit user consent.
- Permanent `history/` never touched by cleanup/purge.
- KV cache quantization: LM Studio GUI-only (REST rejects with 400). Record but do not set via REST.
- Ollama: beta backend, modelfile export/apply only. No live-server E2E yet.

## Files

Create:
- `investment_engine/day_trader/scoring.py`
- `investment_engine/providers/optimization.py`
- `investment_engine/providers/optimization_config.json`
- `tests/test_day_trader_scoring.py`
- `tests/test_providers_optimization.py`
- `docs/specs/2026-11-09-demo-live-auto-demo-training-design.md` (this file)

Modify:
- `portfolio_ai_assistant.py` — add live phase after demo phase.
- `run_automated.bat` — already updated with `--day-trader --day-trader-allow-orders`.
- `portfolio_config.json` — `auto_run=true` (already set).
- `investment_engine/day_trader/config.py` — ensure `auto_run` default handled.

# Rotation + CSV Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI toggle `--include-quantities` (CSV/XLSX loader strips/keeps quantity columns) and advisory rotation plan (`--rotation-plan {none,average-down,short-rotation,cash-apy}`) that writes `reports/current/rotation_plan.md`. No orders executed; advisory only.

**Architecture:** `portfolio_config.json` gets `include_quantities` (bool, default False) and `rotation_plan` (str, default "none"). `portfolio_ai_assistant.py` parses args; loader drops/keeps quantity; `investment_engine/rotation.py` builds plan from current portfolio; report writer formats markdown. No cloud/provider/code-change overlap with load-guard work (separate file set).

**Tech Stack:** Python 3.12, existing pandas/yfinance for loader, pure Python for rotation logic.

**Spec:** `docs/specs/2026-10-29-rotation-csv-toggle.md` (all 5 sections A–E approved by user). Load-guard spec (`docs/specs/2026-10-28-provider-busy-guard-design.md`) remains independent.

**Dependency ruling (recorded):** `Task 5` from load-guard plan (`main.py` preflight integration) must be verified before `portfolio_ai_assistant.py` is edited (same file). Rotation touches CLI arg block; preflight touches loop body — no function-level overlap, but file-level overlap requires verified Task 5 first or an explicit deferred-ruling. Default: finish load-guard verification as pre-step.

## Global Constraints

- `portfolio_config.json` backward-compatible: missing `include_quantities` / `rotation_plan` defaults to False / "none" (current behaviour unchanged).
- `portfolio_ai_assistant.py`: argparse added only if not already present; CLI args never replace config-file values (arg > config > default).
- Rotation advisory only: no `requests.post` to any broker; `rotation_plan.md` header states `Source: advisory only; no orders executed; reconciliation: PASS/FAIL` copied from current brief.
- `rotation_target` (default `AAPL`) validated against existing static alias table (`investment_engine/portfolio/symbols.py`). Invalid alias → rotation skipped with log warning (`Rotation: invalid target alias`), not crash.
- No `portfolio_performance.toml` mutations (performance baseline stays manual-only).
- New dependency: none (pure Python; markdown writer uses existing `markdown`-style formatting from `portfolio_decision_brief.md`).
- Git: per-task commit with user authorization (granted for this session); push never; spec self-reviewed (A–E approved).

## Review Focus

1. Toggle off by default (`include_quantities=False`) — backward compatibility → `test_loader_default_false_keeps_quantities_strip` (C1)
2. Rotation advisory — file header asserts no orders → `test_rotation_header_has_advisory_disclaimer` (D3)
3. Rotation exit conditions respected (average-down max 3 cycles; cash-apy exit when APY+released >= cost) — `test_rotation_exit_conditions` (B3)
4. Config missing new keys → defaults applied, no crash → `test_config_missing_keys_default` (E1)
5. `rotation_target` alias validated; invalid → skip with warning → `test_rotation_invalid_target_warning` (B4)

---

### Pre-step (load-guard dependency): Verify / defer Task 5

- [ ] **Step 0.1: Read load-guard plan progress** — open `.superpowers/sdd/2026-10-28-provider-busy-guard/progress.md`.
- [ ] **Step 0.2: Run verification command**

```bash
py -3.12 -m pytest tests/test_load_guard.py -v -k "preflight_busy or revive"
```

Expected (per ledger): PASS if Task 5 complete; else FAIL with clear message.
- [ ] **Step 0.3: If FAIL → finish Task 5 (run integration tests, ledger fix, commit)** per `docs/superpowers/plans/2026-10-28-provider-busy-guard.md`. If PASS → record in this plan's ledger (`docs/superpowers/plans/2026-10-29-rotation-csv-toggle.md` progress file — create at `.superpowers/sdd/2026-10-29-rotation-csv-toggle.md/progress.md`) the line:
`Load-guard dependency: PASS (Task 5 complete at commit <hash>, preflight/revive verified)`.
- [ ] **Step 0.4: Create this plan's workspace**

```bash
mkdir -p .superpowers/sdd/2026-10-29-rotation-csv-toggle
printf 'docs/specs/2026-10-29-rotation-csv-toggle.md\n' > .superpowers/sdd/2026-10-29-rotation-csv-toggle/plan-path
echo '*\n' > .superpowers/sdd/.gitignore
```

- [ ] **Step 0.5: Ledger identity line** — `echo '# SDD ledger — plan: docs/superpowers/plans/2026-10-29-rotation-csv-toggle.md' >> .superpowers/sdd/2026-10-29-rotation-csv-toggle/progress.md`

---

### Task 1: Config / CLI knobs (toggle + rotation)

**Files:**
- Modify: `portfolio_config.json` (new root keys; add to repo file if present; else create sample)
- Modify: `investment_engine/config/settings.py` (optional: add `include_quantities`, `rotation_plan`, `rotation_trim_pct`, `rotation_target`, `apy_rate` fields using `_env_bool` / `_env_int` / `_env`)
- Modify: `portfolio_ai_assistant.py` (add argparse, read `--include-quantities` / `--rotation-plan`)
- Test: `tests/test_rotation.py` (tests 5, 6 of Review Focus: toggle default + config missing)

**Interfaces:**
- Consumes: `portfolio_config.json` (existing config loader if any; else CLI-only).
- Produces: `include_quantities: bool` (default False), `rotation_plan: str` ("none"), `rotation_trim_pct: int` (30), `rotation_target: str` ("AAPL"), `apy_rate: float` (3.0) available in `portfolio_ai_assistant.py` and in rotation module.

- [ ] **Step 1: Write failing tests**

```python
def test_config_default_toggle_false():
    import json, tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({"provider":"auto"}, f); path = f.name
    # load config; assert include_quantities defaults False when missing

def test_config_missing_keys_default():
    # same structure: missing rotation_plan -> "none"
```

(Exact config loader invocation depends on existing `portfolio_config.json` usage pattern; check file existence first — if missing, add to `tests/fixtures/portfolio_config.json` or create minimal file for test only.)

- [ ] **Step 2: Run tests (expect FAIL on missing args/keys)**
- [ ] **Step 3: Implement** — add `argparse` to `portfolio_ai_assistant.py` (if missing), add config fields (either through `portfolio_config.json` parsing or `settings.py`), default False/"none"/30/"AAPL"/3.0.
- [ ] **Step 4: Run `tests/test_rotation.py -k default` (expect PASS)**
- [ ] **Step 5: Commit (gate)** — `feat: config + CLI knobs for rotation and toggle`

### Task 2: CSV loader toggle (`include_quantities`)

**Files:**
- Modify: loader function in `portfolio_ai_assistant.py` or `investment_engine/main.py` that reads CSV/XLSX portfolio data (check which file reads `portfolio_performance.toml`, CSV, or T212 exports — grep for `portfolio_performance.toml` or `.csv` in the codebase first).
- Test: `tests/test_rotation.py` (test 1 of Review Focus — toggle off keeps strip)

**Interfaces:**
- Produces: `load_portfolio_data(source_path: str, include_quantities: bool) -> list[dict]`. When False: each row dict excludes `quantity`, `pieQuantity`, `averagePrice`, `currentPrice`; keeps `ticker`, `ppl`, `initialFillDate`, `frontend`. When True: includes all columns present in source.

- [ ] **Step 1: Read loader code** — grep `portfolio_performance.toml`, `read_csv`, `.xlsx`, `csv` in `portfolio_ai_assistant.py` and `investment_engine/`. Note the exact function that builds the portfolio list.
- [ ] **Step 2: Write failing test** (`test_loader_default_false_keeps_quantities_strip`)
- [ ] **Step 3: Implement** — wrap loader with conditional column drop (pandas `drop(columns=[...])` or dict comprehension before passing downstream).
- [ ] **Step 4: Verify PASS**
- [ ] **Step 5: Commit** — `feat: loader toggle include_quantities`

### Task 3: Rotation algorithm (`rotation.py`) — average-down + short-rotation contract

**Files:**
- Create: `investment_engine/rotation.py`
- Test: `tests/test_rotation.py`

**Interfaces:**
- Produces: `PlanResult = namedtuple("PlanResult", ["plan", "ticker", "action", "quantity_change", "reason", "simulated_pnl", "cycle"]); RotationBuilder.build(portfolio_data: list[dict], plan_name: str, trim_pct: int, target_ticker: str) -> list[PlanResult]`.

Algorithm contract (per spec §4):
- Input `portfolio_data`: rows with `ticker`, `ppl`, `quantity` (if include_quantities=True; else binary presence), `initialFillDate`.
- Filter eligible: positions with `ppl < 0` (average-down / short-rotation) OR `quantity > 0` (cash-apy requires positive quantity to release).
- `trim_pct`: percentage of current quantity to release (default 30; config `rotation_trim_pct`). For `cash-apy`: trim_pct = 100 (full release).
- `rotation_target`: ticker alias (validated against `portfolio/symbols.py` alias table; if invalid, skip rotation with warning reason string).
- Simulated PNL for rotation recommendation: `simulated_pnl = quantity_change * (target_suggested_entry - current_cost) / current_cost` (simplified advisory formula; exactly the advisory note, not a trade execution).
- Exit conditions: `average-down`: PPL >= 0 OR cycle >= 3; `short-rotation`: PPL >= 0 on new ticker; `cash-apy`: `simulated_apy_earn + released_value >= original_cost`.

- [ ] **Step 1: Write failing tests** — `test_rotation_average_down`, `test_rotation_short_target_alias_validation`, `test_rotation_exit_conditions`, `test_rotation_invalid_target_warning`.
- [ ] **Step 2: Verify FAIL** (function missing / import missing).
- [ ] **Step 3: Implement** `investment_engine/rotation.py` with exact interface and contract above.
- [ ] **Step 4: Verify PASS** (`tests/test_rotation.py -v`)
- [ ] **Step 5: Commit** — `feat: rotation algorithm (advisory)`

### Task 4: Cash-apy rotation + report writer

**Files:**
- Modify: `investment_engine/rotation.py` (add `cash-apy` branch to `RotationBuilder.build`)
- Create: report writer in `investment_engine/reporting/` or `investment_engine/rotation.py` (function `write_rotation_plan(results: list[PlanResult], settings) -> str` that writes markdown)
- Modify: `portfolio_ai_assistant.py` (wire `--rotation-plan` to call `build()` + `write()`, save to `reports/current/`)
- Test: `tests/test_rotation.py` (`test_cash_apy_exit_condition`, `test_report_header_advisory_disclaimer`)

**Interfaces:**
- Produces: `write_rotation_plan` writes `reports/current/rotation_plan.md` with sections: header (plan, timestamp, advisory disclaimer, attribution line copied from current brief format), table (ticker, action, quantity change, reason, simulated PNL, cycle), config footer (`trim_pct`, `target`, `apy_rate`), exit-status line.

- [ ] **Step 1: Write failing tests**
- [ ] **Step 2: Verify FAIL**
- [ ] **Step 3: Implement** `cash-apy` branch (simulated APY accumulation using `apy_rate` setting; exit condition check) + markdown writer.
- [ ] **Step 4: Verify PASS**
- [ ] **Step 5: Commit** — `feat: cash-apy rotation + rotation_plan.md writer`

### Task 5: CLI wiring (`portfolio_ai_assistant.py`)

**Files:**
- Modify: `portfolio_ai_assistant.py`
- Test: `tests/test_rotation.py` (test `test_cli_args_accepted` if CLI framework supports it; else manual verification command in step 4)

- [ ] **Step 1: Inspect CLI** — check if `portfolio_ai_assistant.py` uses `sys.argv`, `argparse`, or `click`. Note exact insertion point.
- [ ] **Step 2: Write minimal test / dry-run** — `test_cli_args_accepted` (can be a simple import test that argparse doesn't crash with `--rotation-plan=average-down` and `--include-quantities`).
- [ ] **Step 3: Implement** — add args; read from config file as override; wire loader (`--include-quantities`) and rotation (`--rotation-plan` non-none calls `build()` + `write()`).
- [ ] **Step 4: Verify** — run the CLI dry-run (no T212 connection needed): `py -3.12 portfolio_ai_assistant.py --config portfolio_config.json --rotation-plan=none --include-quantities`. Expected: exits cleanly, `rotation_plan.md` NOT created; `Rotation: disabled` in log.
- [ ] **Step 5: Commit** — `feat: CLI args --include-quantities --rotation-plan`

### Task 6: Config file + env wiring

**Files:**
- Modify: `portfolio_config.json` (add `include_quantities`, `rotation_plan`, `rotation_trim_pct`, `rotation_target`, `apy_rate`)
- Modify: `api.env` (commented block documenting new env keys `INCLUDE_QUANTITIES`, `ROTATION_PLAN`, `ROTATION_TRIM_PCT`, `ROTATION_TARGET`, `ROTATION_APY_RATE`)
- Test: `tests/test_rotation.py` (`test_config_default` from Task 1 extended)
- No new dependency; `portfolio_config.json` is already in `.gitignore`? Check; if tracked, add to `.gitignore` only the user-local file, not the sample.

- [ ] **Step 1: Update config / env**
- [ ] **Step 2: Verify** — load config file; assert defaults applied when new keys missing.
- [ ] **Step 3: Commit** — `docs/config: rotation toggle + rotation plan config/env`

### Task 7: Full-branch verification (rotation suite + load-guard compatibility check)

- [ ] **Step 1: Run rotation test suite fully**

```bash
py -3.12 -m pytest tests/test_rotation.py -v
```
Expected: PASS, all Review Focus cases covered.

- [ ] **Step 2: Compatibility with load-guard (no overlap)** — verify `portfolio_ai_assistant.py` CLI args don't break `portfolio_config.json` load; no `LM Studio` / `Ollama` references in rotation module.

- [ ] **Step 3: Read `portfolio_config.json`** — confirm backward-compatible; new keys present; old runs still work with missing keys.
- [ ] **Step 4: Ledger final lines** — collect all `Ruling:` lines from this plan's execution (Task 5 dependency, CLI arg insertion choice, report writer format) into `.superpowers/sdd/2026-10-29-rotation-csv-toggle/progress.md`.
- [ ] **Step 5: Final review recommendation** — recommend Native (same session, no subagent) since rotation is one module + CLI wiring; user already selected Native for load-guard. Suggest `subagent-driven-development` only if future rotation expansions (e.g., multi-ticker portfolio optimization) become complex.

---

## Ledger initial (pre-implementation)

- `Plan: docs/superpowers/plans/2026-10-29-rotation-csv-toggle.md` — created.
- `Spec: docs/specs/2026-10-29-rotation-csv-toggle.md` — all sections A–E approved (user: A=schválená, B=schválená, C=schválená, D=schválená, E=schválená).
- `Approach: C — CLI + report` (user selection).
- `Dependency ruling: load-guard Task 5 must be verified before portfolio_ai_assistant.py edited.`
- `Workspace: .superpowers/sdd/2026-10-29-rotation-csv-toggle/progress.md` created with identity line.
- `Task 0: dependency verification pending` (load-guard preflight/revive test run before rotation CLI wiring).

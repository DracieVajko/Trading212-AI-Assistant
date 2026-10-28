# Design: Rotation Strategy + CSV/XLSX Toggle (CLI + Report)

Status: DRAFT — pending section approvals (see Decision Log)
Plan reference: `docs/superpowers/plans/2026-10-28-provider-busy-guard.md`

## 1. Scope (chosen: Approach C — CLI + report)

Two independent subsystems:

A. **Data input toggle** (`--include-quantities`) — when reading T212 CSV/XLSX
   inputs (raw endpoint dump, portfolio snapshot, cash-flow history), the loader
   either ignores the quantity column (`pieQuantity` / `quantity`) and treats
   every row as a ticker presence (`True/False`), OR includes quantities for
   rotation calculations. Default `False` (backward compatible; today all
   analysis treats positions as binary presence except reconciliation which
   reads raw endpoint fields independently).

B. **Rotation strategy module** (`--rotation-plan {none,average-down,short-rotation,cash-apy}`) —
   a new `investment_engine/rotation.py` module that reads the current
   portfolio snapshot, applies the selected plan, and writes
   `reports/current/rotation_plan.md`. No orders are executed — advisory-only
   (same contract as the decision brief and portfolio_decision_brief.md).

Both subsystems are CLI-gated. The load-guard design spec (`docs/specs/2026-10-28-provider-busy-guard-design.md`) stays independent.

## 2. Design Sections (approval required per section)

### Section A: Architecture (read; approve/reject/revise)

```
portfolio_ai_assistant.py --config portfolio_config.json \
  [--include-quantities] \
  [--rotation-plan {none,average-down,short-rotation,cash-apy}]
```

- New CLI flags parsed in `portfolio_ai_assistant.py` (reading from `sys.argv` or `argparse` if already present). If `argparse` is not in the file yet, add it as the minimal addition (one import, 2 new `add_argument` lines).
- `--include-quantities`: passed as a boolean through `config_dict` to `_fetch_t212_data` and to the CSV loader. When False, the loader strips the `quantity` / `pieQuantity` field before passing the row to downstream modules (symbol resolution, reconciliation, rotation engine).
- `--rotation-plan`: triggers `rotation.Plan.build()` (Task 7 in this plan). Output: `reports/current/rotation_plan.md` (markdown table: ticker, current quantity, action: reduce/hold/reinvest, reason, expected PPL). When `none`: no rotation file written; `main()` logs `Rotation: disabled` at INFO.

### Section B: Rotation Algorithm Contract (read; approve/reject/revise)

Input: current portfolio (from T212 API — same data source as `portfolio_decision_brief.md`).
Rules (per user's clarification: all positions eligible, not just PIE; 3 strategies):

| Plan | Trigger | Action on losing position (PPL < 0) | Reinvestment target | Exit condition |
|---|---|---|---|---|
| `average-down` | PPL < 0, quantity > 0 | Reduce position by 25-50% (configurable `rotation_trim_pct`, default 30); released EUR buys the same ticker at lower cost (simulated — report only; actual order not placed) | Same ticker (simulated lower entry) | PPL >= 0 OR 3 rotation cycles completed |
| `short-rotation` | PPL < 0, quantity > 0 | Reduce by `trim_pct`; released EUR buys a different ticker (user-selected `rotation_target`, default `AAPL` or from `watchlist` if set) | Different ticker | PPL on new ticker >= 0; then report advises returning to original ticker |
| `cash-apy` | Any position OR when `total_equity` < target (simulated) | Full reduction to 0; released EUR held as cash (simulated daily APY from `portfolio_performance.toml` `net_deposits_eur` rate or a new `apy_rate` knob, default 3%) | Cash (simulated APY gain) | When accumulated simulated APY + released EUR >= original position cost; advise repurchase |

Output file format (markdown): section header (plan name, run timestamp), table (ticker / action / quantity change / reason / simulated PNL / cycle), rule footer (`rotation_trim_pct`, `rotation_target`, `apy_rate` values used), attribution note (`Source: advisory only; no orders executed; T212 reconciliation PASS` copied from current brief).

Constraints (spec §5, carried): never executes orders; never modifies `portfolio_performance.toml`; attribution includes `provider_chain` note and `Reconciliation: PASS/FAIL` copied from current run; rotation file only written when `--rotation-plan` is non-none; kill-switch `ROTATION_PLAN=none` (env override) disables regardless of CLI.

### Section C: Data Loader Toggle (read; approve/reject/revise)

The CSV loader (used in `_fetch_t212_data`'s reconciliation and snapshot reading) checks `include_quantities`. Implementation points:
- `portfolio_config.json` gets `include_quantities: bool` (default false) in the root dict; `portfolio_ai_assistant.py` passes it through the settings chain (`EngineSettings` or direct dict, depending on existing plumbing).
- When False: loader strips `quantity`, `pieQuantity`, `averagePrice`, `currentPrice` columns before building position objects; reconciliation uses only `ticker`, `ppl`, `initialFillDate` (same as today, since reconciliation uses endpoint fields, not CSV columns — but toggle ensures future CSV exports without quantities work identically).
- No new CSV parser dependency: reuse `pandas.read_csv` / `feedparser` existing in requirements; just drop columns by name.

### Section D: Integration Points (read; approve/reject/revise)

Files touched (new + modified):
- NEW: `investment_engine/rotation.py`
- NEW: `tests/test_rotation.py` (offline; monkeypatched portfolio data from `tests/test_providers_modes.py` fixtures; no HTTP; no T212 connection)
- Modify: `portfolio_ai_assistant.py` (add argparse arguments; wire `--include-quantities` into loader; wire `--rotation-plan` into rotation.build + report writer)
- Modify: `reports/current/rotation_plan.md` writer (new small function `reporting.rotation_brief` mirroring `portolio_decision_brief.md` structure)
- Modify: `reports/current/portfolio_decision_brief.md` (optional: add one line referencing rotation when enabled)
- Modify: `portfolio_config.json` (add `include_quantities` and `rotation_plan` fields; backward-compatible — missing keys default to False and "none")

No changes to cloud providers, T212 auth, or load-guard code (Task 5 of previous spec continues independently).

### Section E: Config + Env (spec §5 carried; approve/reject/revise)

New environment/config keys (defaults safe / backward-compatible):

```
# CLI args (argparse):
--include-quantities  (store_true, default False)
--rotation-plan {none,average-down,short-rotation,cash-apy} (default none)

# Config file (portfolio_config.json, new keys):
include_quantities: false
rotation_plan: "none"
rotation_trim_pct: 30
rotation_target: "AAPL"  # ticker alias; validated against static alias table
apy_rate: 3.0            # annual % for cash-apy simulation

# Env override (kill-switch / automation):
INCLUDE_QUANTITIES=0|1
ROTATION_PLAN=none
```

Test matrix (`tests/test_rotation.py`):
1. `average-down` — losing position (`PPL` < 0) produces trim recommendation + same-ticker reinvest note.
2. `short-rotation` — same input, different target ticker recommendation.
3. `cash-apy` — same input, full-reduction + simulated APY line; exit-condition check.
4. Toggle off (`include_quantities=False`) — loader strips quantity columns; rotation gets only ticker presence (no quantity-based trim percentage — rotation defaults to binary: full reduce for all eligible tickers).
5. Rotation disabled (`rotation_plan=none`) — no `rotation_plan.md` file created; log line `Rotation: disabled` only.
6. Config file missing new keys — defaults applied (`False` / `"none"`) without error.

No destructive operations (per agent-operating-rules); commit steps per section; push never; git consent per task (user granted "commit per task" for this session).

---

## 3. Open dependency (prior work ledger line)

`Task 5 (load-guard):` `main.py` edit exists (preflight busy-guard integration + revive); `test_preflight_busy_skips_with_cooldown` and `test_revive_blocked_by_busy` still require verification run. Before implementing Section C (rotation CLI wiring that also touches `portfolio_ai_assistant.py`), the load-guard Task 5 must be closed (either verified or explicitly deferred in ledger) so the same file (`portfolio_ai_assistant.py`) is not edited by two open branches.

**Decision needed:** finish `Task 5` verification (run the integration tests, ledger result) before opening Section C, OR explicitly defer it (`Final: deferred: load-guard Task 5 — preflight/revive tests not yet verified; rotation touches different CLI arg block, no function-level overlap`) and proceed.

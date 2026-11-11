# Day Trader Integration — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vendor the day-trader skill pack and add a runnable, offline-safe premarket
read-only pack (scanner, news, analyst, pelosi) that writes a separate
`day_trader_brief.md` + `day_trader.json`, with no order code.

**Architecture:** Vendor copy under `vendor/day_trader_skill/` plus a new
`investment_engine/day_trader/` adapter package. The runner invokes vendored
scripts via `subprocess` with `--json` and parses output. State lives in
`data/day_trader/trader/`. The CLI gains `--day-trader`. No changes to the
long-term portfolio signal path.

**Tech Stack:** Python 3.12, stdlib (subprocess, json, pathlib, sqlite3), MIT
vendored code, pytest.

**Spec:** `docs/specs/2026-11-06-day-trader-skill-integration-design.md`

## Global Constraints

- Python 3.12 only; `py_compile` must pass for new modules.
- All runtime output under `PortfolioAI_Assistant`.
- Vendored code is MIT; keep `LICENSE` and `VENDORED_COMMIT`.
- No secrets in logs/reports.
- Execution layer is NOT implemented in this phase; `execution.enabled` defaults
  to `false` and no order code exists yet.
- Existing tests must remain green (baseline: 874 passed, 3 skipped, 5 known
  pre-existing failures).
- No git commits without explicit user consent.

## Review Focus

Inputs most likely to bite a user of this software, with the test that pins
each one:

1. **Offline run with no network** — the pack must produce a valid degraded
   report instead of crashing. (Task 6, `test_runner_offline_degraded`)
2. **Missing vendored script** — the runner must report a clear error, not
   raise. (Task 3, `test_runner_missing_script`)
3. **Corrupt state JSON** — state manager must recover and recreate defaults.
   (Task 4, `test_state_recovers_corrupt`)
4. **Empty scanner result** — the report must still render and say "no hits".
   (Task 6, `test_report_empty_watchlist`)
5. **Wrong working directory** — the pack must write under the project root.
   (Task 7, `test_day_trader_flag_runs_from_parent`)

---

### Task 1: Vendor the external repository

**Files:**
- Create: `vendor/day_trader_skill/` (copy of `trader-*`, `tests/`, `LICENSE`,
  `README.md`)
- Create: `vendor/day_trader_skill/VENDORED_COMMIT`
- Create: `vendor/day_trader_skill/README.vendor.md`

- [ ] **Step 1: Copy the vendored files.**

Use `robocopy` or Python to copy `trader-*`, `tests/`, `LICENSE`, `README.md`
from the cloned repo (`<temp>/opencode/day-trader-skill`)
into `vendor/day_trader_skill/`. Do not copy `.git/` or `.claude-plugin/`.

- [ ] **Step 2: Write `VENDORED_COMMIT`.**

Write `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` followed by a newline.

- [ ] **Step 3: Write `README.vendor.md`.**

Document source URL, license, commit SHA, how to update, and the fact that the
copy is read-only (do not edit in place; apply patches in the adapter).

- [ ] **Step 4: Verify.**

Run: `py -3.12 -m pytest vendor/day_trader_skill/tests -q 2>&1 | Select-Object -Last 5`
Expected: tests pass (offline fixtures).

---

### Task 2: Create the adapter package skeleton and config

**Files:**
- Create: `investment_engine/day_trader/__init__.py`
- Create: `investment_engine/day_trader/config.py`
- Create: `tests/test_day_trader_config.py`

**Interfaces:**
- Produces: `DayTraderConfig` dataclass with `enabled`, `state_dir`, `timezone`,
  `universe_limit`, `watchlist_limit`, `scan`, `budget`, `report`, `execution`
  fields; `DayTraderConfig.from_mapping(mapping)`; `DayTraderConfig.validate()`.

- [ ] **Step 1: Write the failing test.**

`tests/test_day_trader_config.py`:
```python
def test_config_defaults_are_safe():
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    assert cfg.enabled is False
    assert cfg.execution.enabled is False
    assert cfg.execution.environment == "demo"

def test_config_from_mapping_overrides():
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig.from_mapping({"enabled": True, "universe_limit": 50})
    assert cfg.enabled is True
    assert cfg.universe_limit == 50

def test_config_rejects_live_environment():
    from investment_engine.day_trader.config import DayTraderConfig
    import pytest
    with pytest.raises(ValueError):
        DayTraderConfig(execution={"environment": "live"})
```

- [ ] **Step 2: Run test to verify it fails.**

Run: `python -m pytest tests/test_day_trader_config.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `config.py`.**

Dataclass with nested dataclasses `ScanConfig`, `BudgetConfig`, `ExecutionConfig`,
`ReportConfig`. `from_mapping` reads nested dicts safely; `validate` raises
`ValueError` for invalid values (e.g. live environment without ack).

- [ ] **Step 4: Run test to verify it passes.**

Run: `python -m pytest tests/test_day_trader_config.py -q`
Expected: PASS.

---

### Task 3: Runner with JSON parsing

**Files:**
- Create: `investment_engine/day_trader/runner.py`
- Create: `tests/test_day_trader_runner.py`

**Interfaces:**
- Produces: `ToolResult` (dataclass: `ok`, `exit_code`, `payload`, `stdout`,
  `stderr`, `duration_s`); `run_tool(script_path, args, timeout_s, json_mode,
  cwd, env)`.

- [ ] **Step 1: Write the failing test.**

`tests/test_day_trader_runner.py`:
```python
def test_runner_parses_json(tmp_path):
    import sys
    script = tmp_path / "tool.py"
    script.write_text("import json, sys; print(json.dumps({'a': 42}))", encoding="utf-8")
    from investment_engine.day_trader.runner import run_tool
    res = run_tool(script, [], 30, True, cwd=tmp_path)
    assert res.ok and res.payload == {"a": 42}

def test_runner_missing_script(tmp_path):
    from investment_engine.day_trader.runner import run_tool
    res = run_tool(tmp_path / "missing.py", [], 30, True, cwd=tmp_path)
    assert not res.ok and "not found" in res.stderr.lower()

def test_runner_offline_degraded(tmp_path):
    script = tmp_path / "tool.py"
    script.write_text("import sys; sys.exit(1)", encoding="utf-8")
    from investment_engine.day_trader.runner import run_tool
    res = run_tool(script, [], 30, True, cwd=tmp_path)
    assert not res.ok and res.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails.**

Run: `python -m pytest tests/test_day_trader_runner.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `runner.py`.**

Use `subprocess.run` with `shell=False`, list args, timeout, capture_output.
Parse JSON from stdout when `json_mode`. Missing script → ToolResult with
`stderr="script not found: ..."`. Timeout → `stderr="timeout after Xs"`.

- [ ] **Step 4: Run test to verify it passes.**

Run: `python -m pytest tests/test_day_trader_runner.py -q`
Expected: PASS.

---

### Task 4: State manager with corruption recovery

**Files:**
- Create: `investment_engine/day_trader/state.py`
- Create: `tests/test_day_trader_state.py`

**Interfaces:**
- Produces: `ensure_state_root(root)`, `read_json(path, default)`,
  `write_json(path, payload)`, `archive_session(root, run_id)`.

- [ ] **Step 1: Write the failing test.**

`tests/test_day_trader_state.py`:
```python
import json
from pathlib import Path

def test_state_recovers_corrupt(tmp_path):
    from investment_engine.day_trader.state import read_json
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert read_json(p, {"x": 1}) == {"x": 1}

def test_state_roundtrip(tmp_path):
    from investment_engine.day_trader.state import read_json, write_json
    p = tmp_path / "a.json"
    write_json(p, {"y": 2})
    assert read_json(p, None) == {"y": 2}
```

- [ ] **Step 2: Run test to verify it fails.**

Run: `python -m pytest tests/test_day_trader_state.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `state.py`.**

`read_json` returns `default` on missing/invalid file and moves corrupt files to
`*.corrupt-<timestamp>`. `write_json` creates parent dirs and writes with
`json.dump(..., indent=2)`.

- [ ] **Step 4: Run test to verify it passes.**

Run: `python -m pytest tests/test_day_trader_state.py -q`
Expected: PASS.

---

### Task 5: Read-only premarket pack

**Files:**
- Create: `investment_engine/day_trader/premarket.py`
- Create: `tests/test_day_trader_premarket.py`

**Interfaces:**
- Produces: `run_premarket(config, runner, state_root) -> dict` with keys
  `watchlist`, `news`, `analyst`, `pelosi`, `errors`, `status`.

- [ ] **Step 1: Write the failing test.**

`tests/test_day_trader_premarket.py`:
```python
def test_premarket_empty_watchlist(tmp_path):
    from investment_engine.day_trader.premarket import run_premarket
    from investment_engine.day_trader.config import DayTraderConfig
    # fake runner always returns ok with empty hits
    def fake_runner(script, args, timeout, json_mode, cwd, env):
        class R: 
            ok=True; payload={"hits":[]}; exit_code=0; stdout=""; stderr=""; duration_s=0.0
        return R()
    cfg = DayTraderConfig()
    out = run_premarket(cfg, fake_runner, tmp_path)
    assert out["status"] in ("OK", "DEGRADED")
    assert out["watchlist"].get("hits") == []
```

- [ ] **Step 2: Run test to verify it fails.**

Run: `python -m pytest tests/test_day_trader_premarket.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `premarket.py`.**

Run scanner `daily --limit config.universe_limit --json`, then news on up to
`watchlist_limit` symbols, analyst on the same, pelosi index. Each step is
independent; failures recorded in `errors` and the stage is `DEGRADED` but the
run continues. Never raises.

- [ ] **Step 4: Run test to verify it passes.**

Run: `python -m pytest tests/test_day_trader_premarket.py -q`
Expected: PASS.

---

### Task 6: Report writer

**Files:**
- Create: `investment_engine/day_trader/reporting.py`
- Create: `tests/test_day_trader_reporting.py`

**Interfaces:**
- Produces: `write_day_trader_report(state_root, payload, reports_dir) -> Path`
  writing `day_trader_brief.md` and `day_trader.json`.

- [ ] **Step 1: Write the failing test.**

`tests/test_day_trader_reporting.py`:
```python
def test_report_renders_empty_watchlist(tmp_path):
    from investment_engine.day_trader.reporting import write_day_trader_report
    payload = {"status": "OK", "watchlist": {"hits": []}, "errors": []}
    out = write_day_trader_report(tmp_path, payload, tmp_path / "reports")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "no hits" in text.lower() or "0 hits" in text
```

- [ ] **Step 2: Run test to verify it fails.**

Run: `python -m pytest tests/test_day_trader_reporting.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `reporting.py`.**

Render a markdown brief with header, watchlist table, catalysts, plans,
tickets, and a "No orders were sent (execution disabled)" banner. Write JSON
with the same payload. Create `reports/current` if needed.

- [ ] **Step 4: Run test to verify it passes.**

Run: `python -m pytest tests/test_day_trader_reporting.py -q`
Expected: PASS.

---

### Task 7: CLI integration

**Files:**
- Modify: `portfolio_ai_assistant.py`

- [ ] **Step 1: Add the flag.**

Add `--day-trader` (store_true) to argparse. When set, after settings load,
run the premarket pack with `runner.run_tool` pointed at the vendored scripts,
write the report, print the path, and return 0. Use `ROOT` for all paths.

- [ ] **Step 2: Smoke test from the parent directory.**

Run from the parent directory of the project:
`py -3.12 .\PortfolioAI_Assistant\portfolio_ai_assistant.py --day-trader --day-trader-offline <fixture path>`
Expected: report written under `PortfolioAI_Assistant\reports\current\`, no
`reports` created in the parent.

- [ ] **Step 3: Verify no regressions.**

Run: `python -m pytest tests/test_phase0_foundation.py::test_entrypoint_pins_cwd_to_project_root -q`
Expected: PASS.

---

### Task 8: Documentation and bookkeeping

**Files:**
- Modify: `docs/PORTFOLIO_AI_UPGRADE_PLAN.md`
- Create: `vendor/day_trader_skill/README.vendor.md`

- [ ] **Step 1: Update the upgrade plan.**

Mark Phase 1 items complete; add a "Day Trader — Phase 1" section with the
new modules, flags, and tests.

- [ ] **Step 2: Write the vendor README.**

Source URL, license, commit SHA, update procedure, and the note that the copy
is read-only.

---

### Task 9: Verification

- [ ] **Step 1: Compile.**

Run: `py -3.12 -m py_compile portfolio_ai_assistant.py investment_engine/day_trader/*.py`
Expected: no errors.

- [ ] **Step 2: Targeted tests.**

Run: `python -m pytest tests/test_day_trader_config.py tests/test_day_trader_runner.py tests/test_day_trader_state.py tests/test_day_trader_premarket.py tests/test_day_trader_reporting.py -q`
Expected: all pass.

- [ ] **Step 3: Full suite.**

Run: `python -m pytest tests/ -q`
Expected: 874+ passed, same 5 pre-existing failures.

- [ ] **Step 4: Tool help smoke.**

Run each vendored script with `--help` from the project root; expect exit 0.

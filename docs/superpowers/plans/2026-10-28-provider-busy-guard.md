# Provider Busy-Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip local LLM providers (LM Studio, llama.cpp, Ollama) for ~120 s when their host is busy or the model is not resident, so the chain falls back to cloud APIs instead of stalling on big local loads.

**Architecture:** New pure-probe module `providers/health.py` returns a `Verdict`; existing preflight in `main.py` calls it once per local link and reuses `skip_for_run(cooldown)`; revive re-probe keeps busy links skipped; `fallback.py` adds a model-scoped cooldown after local generation timeouts. No cloud-provider changes.

**Tech Stack:** Python 3.12, requests (existing), psutil (new, guarded import), nvidia-smi subprocess (optional), pytest.

**Spec:** `docs/specs/2026-10-28-provider-busy-guard-design.md`

## Global Constraints

- Python 3.12; requests only for HTTP (no new HTTP deps). `psutil>=5.9,<7` is the single new dependency.
- Probe functions must never raise; every failure path ⇒ `Verdict(busy=False, ...)` with a DEBUG degradation log.
- `LOAD_GUARD=0` ⇒ no probe calls at all; behaviour byte-identical to today.
- No silent local→cloud switching: every skip logs INFO with reason; failure kinds `host_busy`, `model_cold`, `local_timeout` must reach attribution/`_FALLBACK_EVENTS`.
- Default knobs (spec §5): cooldown 120 s, latency 2500 ms, CPU 85 %, RAM 90 %, GPU 85 %, VRAM free 1500 MiB, local timeout cooldown 300 s.
- Consent-gated git: commit steps below run only after user authorization; suggested messages are placeholders.

## Review Focus

1. Transient Tailscale latency spike must NOT skip LM Studio (both-attempts rule) → pinned by `test_lmstudio_latency_requires_both_attempts_slow` (Task 3).
2. Unknown LM Studio API variant must NOT skip (feature-detect direction: unknown ⇒ not busy) → `test_lmstudio_unknown_api_not_busy` (Task 3).
3. Ollama `/api/ps` absent/malformed must NOT skip → `test_ollama_ps_absent_not_busy` (Task 4).
4. Missing psutil/nvidia-smi degrades to HTTP-only, other signals still decide → `test_metrics_missing_degrades` (Task 3).
5. Cloud provider timeouts must NOT gain a cooldown (local-only rule) → `test_cloud_timeout_no_cooldown` (Task 6).

---

### Task 1: Settings knobs

**Files:**
- Modify: `investment_engine/config/settings.py` (insert after the Ollama block, current line ~263)
- Test: `tests/test_load_guard.py`

**Interfaces:**
- Produces: `EngineSettings` fields (read via `getattr` everywhere later):
  `load_guard_enabled: bool` (LOAD_GUARD, True), `load_guard_cooldown_s: int` (120),
  `load_guard_latency_ms: int` (2500), `load_guard_cpu_pct: int` (85),
  `load_guard_ram_pct: int` (90), `load_guard_gpu_max_util_pct: int` (85),
  `load_guard_vram_min_free_mib: int` (1500), `load_guard_use_nvidia_smi: bool` (True),
  `local_timeout_cooldown_s: int` (300),
  `load_guard_ollama_require_loaded: bool` (LOAD_GUARD_OLLAMA_REQUIRE_LOADED, True).

- [ ] **Step 1: Write the failing test**

```python
def test_load_guard_settings_defaults():
    s = EngineSettings.from_defaults()
    assert s.load_guard_enabled is True
    assert s.load_guard_cooldown_s == 120
    assert s.load_guard_latency_ms == 2500
    assert s.local_timeout_cooldown_s == 300

def test_load_guard_kill_switch(monkeypatch):
    monkeypatch.setenv("LOAD_GUARD", "0")
    s = EngineSettings.from_defaults()
    assert s.load_guard_enabled is False
```

(Third-party imports as in sibling tests; extend, don't duplicate, the file's existing fixture pattern.)

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_load_guard.py -v -k settings`
Expected: FAIL (attribute missing).

- [ ] **Step 3: Implement the fields** in the EngineSettings dataclass exactly as in Interfaces, using existing helpers `_env_bool` / `_env_int`, one env var name each per the list.

- [ ] **Step 4: Run test to verify it passes** — same command, expected PASS.

- [ ] **Step 5: Commit (only with user authorization)** — `feat: load-guard settings knobs`

### Task 2: `health.py` — Verdict, latency rule, localhost detection

**Files:**
- Create: `investment_engine/providers/health.py`
- Test: `tests/test_load_guard.py`

**Interfaces:**
- Consumes: settings fields from Task 1 (via `getattr(settings, name, default)` so tests can pass a `SimpleNamespace`).
- Produces:
  - `@dataclass(frozen=True) Verdict: busy: bool; reason: str; evidence: dict[str, str]`
  - `probe_provider_busy(name: str, base_url: str, settings) -> Verdict`
  - `is_localhost(base_url: str) -> bool` — host part of URL equals `127.0.0.1`, `localhost`, `::1`, `::1]`, or `socket.gethostname()` (case-insensitive).

- [ ] **Step 1: Write the failing tests**

```python
def test_verdict_default_not_busy(): assert Verdict(busy=False, reason="", evidence={}).busy is False
def test_is_localhost_matches():
    for u in ("http://127.0.0.1:1234/v1", "http://localhost:1234", "http://::1:1234"):
        assert is_localhost(u) is True
def test_is_localhost_remote():
    assert is_localhost("http://192.0.2.10:1234") is False
```

- [ ] **Step 2: Run tests** — `py -3.12 -m pytest tests/test_load_guard.py -v -k localhost or verdict` — expected FAIL.

- [ ] **Step 3: Implement** `Verdict`, `is_localhost`, and a `probe_provider_busy` skeleton that returns not-busy for an unknown provider name (dispatch to provider-specific helpers comes in Tasks 3–4).

- [ ] **Step 4: Run tests** — expected PASS.

- [ ] **Step 5: Commit (gate)** — `feat: health verdict + localhost detect`

### Task 3: LM Studio guard — latency, loading-state, localhost metrics

**Files:**
- Modify: `investment_engine/providers/health.py`
- Test: `tests/test_load_guard.py`

**Interfaces:**
- Consumes: `v1_models(base_url) -> dict[str, dict] | None` from `investment_engine.providers.lmstudio` (reset its cache via `reset_v1_models_cache()` in tests); settings from Task 1.
- Produces: internal helpers `_lmstudio_probe(...)`, `_local_metrics() -> dict[str, str] | None` (empty dict when nothing measurable; keys `cpu_pct`, `ram_pct`, `gpu_util_pct`, `vram_free_mib`).

Decision matrix (probe = one `GET {base}/models` measured with `time.monotonic`):
- Not localhost ⇒ OS-metric signals skipped (never cross-host).
- Busy when: (a) **both** measured attempts exceed `load_guard_latency_ms` (preflight calls probe with `latencies: list[float]` — worst case list; empty list ⇒ no latency verdict), OR (b) any v1 entry `state == "loading"`, OR (c) localhost metrics breach any threshold.
- Reason string: `host busy: <signals joined by "; ">` (e.g. `host busy: model state=loading; GPU 92%>85%`).
- Unknown/absent state data, missing psutil/nvidia-smi ⇒ that signal reports not busy + DEBUG line (graceful degradation).

- [ ] **Step 1: Write the failing tests** — the four Review Focus cases 1–2, 4 plus positive cases:

```python
def test_lmstudio_latency_requires_both_attempts_slow(...):  # 1 fast, 1 slow -> not busy
def test_lmstudio_both_attempts_slow_is_busy(...)
def test_lmstudio_loading_state_is_busy(...)                # v1_models entry state="loading"
def test_lmstudio_unknown_api_not_busy(...)                 # v1_models -> None, v0 -> 404 payload
def test_metrics_missing_degrades(...)                      # no psutil, no nvidia-smi -> still verdict, HTTP result decides
def test_localhost_metrics_breach_busy(...)                 # psutil cpu 95 -> busy
def test_kill_switch_no_probe(monkeypatch)                   # LOAD_GUARD=0 -> probe req never called (spy)
```

- [ ] **Step 2: Run** `-k lmstudio or kill` — expected FAIL.
- [ ] **Step 3: Implement** matrix per above (signature pinned by tests; `probe_provider_busy("LM Studio", url, settings)` takes an optional keyword `latencies: list[float] | None = None`).
- [ ] **Step 4: Run** — expected PASS.
- [ ] **Step 5: Commit (gate)** — `feat: LM Studio busy signals`

### Task 4: Pi guards — llama.cpp latency, Ollama resident-model check

**Files:**
- Modify: `investment_engine/providers/health.py`
- Test: `tests/test_load_guard.py`

**Interfaces:**
- Produces: `_ollama_model_resident(base_url: str, model: str) -> bool | None` (None = unknown/absent endpoint). Uses `GET {base}/api/ps`, timeout 3 s; JSON list under `models`; matches `name` key case-insensitively against `model` (with and without `:latest` suffix).

Decision matrix:
- llama.cpp: single attempt; slow reply ⇒ busy (`host busy: probe latency ...ms > 2500ms`).
- Ollama: slow reply ⇒ busy; **model not resident ⇒ busy with reason `model_cold: <model> not in /api/ps`** — only when `load_guard_ollama_require_loaded` is True; when False the resident check is skipped entirely; resident ⇒ latency signals only.

- [ ] **Step 1: Write failing tests** — Review Focus case 3 + positives:

```python
def test_ollama_model_cold_is_busy(...)      # /api/ps returns [] -> busy "model_cold"
def test_ollama_resident_not_busy(...)       # /api/ps lists model -> not busy (fast)
def test_ollama_ps_absent_not_busy(...)      # 404/None -> not busy
def test_ollama_require_loaded_off(...)      # toggle False -> cold model does NOT busy-skip
def test_ollama_latest_suffix_matches(...)   # "ministral-3b-top" vs "ministral-3b-top:latest"
def test_llamacpp_slow_busy(...)
```

- [ ] **Step 2: Run** `-k ollama or llamacpp` — expected FAIL.
- [ ] **Step 3: Implement** matrix.
- [ ] **Step 4: Run** — expected PASS.
- [ ] **Step 5: Commit (gate)** — `feat: Ollama resident + Pi latency signals`

### Task 5: Preflight integration + revive re-probe

**Files:**
- Modify: `investment_engine/main.py` — `_note_unreachable_local_providers` (lines ~159–214) and `_revive_locals_if_due` (lines ~2905–2949)
- Test: `tests/test_load_guard.py`

**Interfaces:**
- Consumes: `probe_provider_busy` (Task 2–4), `skip_for_run`, `PREFLIGHT_COOLDOWN_S`, fallback events (`_record_fallback`), settings fields from Task 1.
- Produces: preflight behaviour — after HTTP 200, busy verdict ⇒ `_record_fallback("provider-chain", f"{label} host busy: …")` + `skip_for_run(label, reason, settings.load_guard_cooldown_s)`; revive path runs the same probe after its 200 OK and re-skips (120 s) instead of reviving when busy.

Implementation notes:
- In `_note_unreachable_local_providers`, collect per-attempt elapsed seconds (`time.monotonic()` around the GET) into a list; pass to `probe_provider_busy(label, {base_url}, settings, latencies=[...])`.
- Guard entirely behind `settings.load_guard_enabled`; kill-switch ⇒ zero new HTTP calls (preflight probes are skipped; `skip` only via the existing down-path).
- Existing tests must keep passing: `tests/test_preflight.py::test_revive_locals_if_due_revives_on_200` (monkeypatched request) — the new probe dependency must be monkeypatch-friendly (module-level import inside function or patch point `investment_engine.main.probe_provider_busy`).

- [ ] **Step 1: Write failing tests**

```python
def test_preflight_busy_skips_with_cooldown(monkeypatch)   # 200 OK + probe busy -> is_skipped true, reason has "host busy"
def test_revive_blocked_by_busy(monkeypatch)               # due_for_reprobe + 200 + busy -> skip extended, not revived
```

- [ ] **Step 2: Run** — `py -3.12 -m pytest tests/test_load_guard.py tests/test_preflight.py -v` — new tests FAIL before implementation; preflight suite green after.
- [ ] **Step 3: Implement** both integration points.
- [ ] **Step 4: Run full relevant suites** — expected: new suite PASS, `test_preflight.py`, `test_provenance_truth.py`, `test_provider_model_scoping.py` PASS unchanged.
- [ ] **Step 5: Commit (gate)** — `feat: preflight + revive busy-guard integration`

### Task 6: Local generation-timeout cooldown in `fallback.py`

**Files:**
- Modify: `investment_engine/providers/fallback.py` — `ChainedFallbackProvider.generate`, `res.timed_out` branch (lines ~371–384)
- Test: `tests/test_load_guard.py`

**Interfaces:**
- Consumes: `local_timeout_cooldown_s` (Task 1); existing `_run_cooldowns` registry on `ChainedFallbackProvider`.
- Produces: behaviour — when `res.timed_out` and provider name is in `("LM Studio", "llama.cpp", "Ollama")` and cooldown > 0: `ChainedFallbackProvider._run_cooldowns[pkey] = _t.monotonic() + cooldown`, `_run_cooldown_kind[pkey] = "local_timeout"`, `_lv.emit_event({"event": "fallback_transition", "reason": "local_timeout_warning_no_retry", "failure_kind": "local_timeout", ...})`. Cloud providers keep today's no-cooldown timeout behaviour.

- [ ] **Step 1: Write failing tests** — Review Focus case 5 + positive:

```python
def test_local_timeout_sets_model_cooldown(...)  # fake provider in chain times out -> _run_cooldowns has pkey
def test_local_timeout_cleared_on_run_start(...)  # ChainedFallbackProvider.reset_run_cooldowns() empties it
def test_cloud_timeout_no_cooldown(...)          # Gemini-named fake provider times out -> no cooldown entry
```

(Fake provider pattern from `tests/test_providers_modes.py`.)

- [ ] **Step 2: Run** — expected FAIL.
- [ ] **Step 3: Implement** exact branch logic (reuse `pkey`/`provider_key(pname, pmodel)` already computed in scope).
- [ ] **Step 4: Run** — expected PASS; also `py -3.12 -m pytest tests/test_providers_modes.py tests/test_lmstudio_reasoning_off.py -v` green.
- [ ] **Step 5: Commit (gate)** — `feat: local timeout cooldown`

### Task 7: Dependency + env documentation wiring

**Files:**
- Modify: `requirements.txt` (append after the Core block, before the Browser block)
- Modify: `api.env` (append commented knob block at end; no uncommented values)
- Test: none beyond Task 1 defaults (this task is wiring/docs).

**Interfaces:** none.

- [ ] **Step 1: Append to requirements.txt**

```
# Load-guard (provider busy detection), localhost-only metrics engine side:
psutil>=5.9,<7
```

- [ ] **Step 2: Append to api.env** (comments documenting defaults; values stay code-defaults so kill-switch lives in code defaults):

```
# ---- Provider load guard (busy host -> cloud fallback) ----
# LOAD_GUARD=1|0 (default 1). Cooldown 120s, latency 2500ms, CPU 85%, RAM 90%,
# GPU 85%, VRAM free 1500 MiB, local timeout cooldown 300s — see settings.py
# (LOAD_GUARD_* , LOCAL_TIMEOUT_COOLDOWN_S). LOAD_GUARD_OLLAMA_REQUIRE_LOADED=1
# uses the Pi only with an already resident model (set 0 to allow cold loads).
```

- [ ] **Step 3: Verify installability + suite** — `py -3.12 -m pip install "psutil>=5.9,<7"` then `py -3.12 -m pytest tests/test_load_guard.py -v` — expected PASS with metrics signals functioning on this machine.
- [ ] **Step 4: Commit (gate)** — `docs/deps: load guard psutil + env docs`

### Task 8: Full-branch verification (no code)

- [ ] **Step 1: Run the whole provider-affected test surface**

```
py -3.12 -m pytest tests/test_load_guard.py tests/test_preflight.py tests/test_providers_modes.py tests/test_provider_model_scoping.py tests/test_provenance_truth.py tests/test_lmstudio_reasoning_off.py tests/test_ollama_provider.py -v
```
Expected: all PASS, 0 failures.

- [ ] **Step 2: Dry evidence run (optional, with user's go-ahead)** — the busy-guard cannot be observed end-to-end until either LM Studio is back online or the Pi serves a resident model; if neither, verify the kill-switch path and preflight equivalence instead:

```
$env:LOAD_GUARD='0'; py -3.12 portfolio_ai_assistant.py --config portfolio_config.json --investment-engine --generate-full-report
```
Expected: log identical in shape to run `a13f2a48` (LM Studio/llama.cpp preflight skips unchanged, no `host busy` lines).

- [ ] **Step 3: Diff review** — `git diff` inspected: no accidental edits, no debug prints left, requirements/api.env contain only the appended blocks.

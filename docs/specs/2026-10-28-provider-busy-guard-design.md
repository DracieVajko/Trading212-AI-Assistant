# Design: Provider Busy-Guard (skip local LLM when host is busy / model cold)

Date: 2026-10-28
Status: Approved (user), amendments approved — see Decision Log.
Scope: `investment_engine` provider chain — no changes to cloud providers.

## 1. Problem

The engine prefers local inference (LM Studio on a GPU PC, llama.cpp + Ollama on a
Raspberry Pi) and falls back to cloud APIs when locals are unavailable. Two failure
modes waste minutes per run and mark runs PARTIAL:

1. **Host busy**: the GPU PC is occupied by other computations. The engine still
   tries warm-up loads of large models (read budget up to 120 s per attempt,
   `lmstudio.py`), burns chain budget, then degrades to cloud anyway.
2. **Cold model / slow host**: a local endpoint answers fast on health checks but
   generation needs a cold model load that exceeds the 90 s attempt cap. Evidence
   (run `a13f2a48`, 2026-10-28 10:47): Ollama `ministral-3b-top` timed out after 90 s
   at **all 5 stages** (no cooldown on simple timeout), run degraded on every stage,
   duration 1055 s vs 465 s baseline, exit code 1 (PARTIAL).

Current preflight (`main.py:_note_unreachable_local_providers`) only distinguishes
"down" (connect failed → 300 s cooldown). There is no notion of "busy".

## 2. Goals / Non-goals

**Goals**
- Before asking a local provider for a big generation, decide quickly whether the
  host can oblige now; if not, skip straight to the cloud chain.
- Keep the local-when-possible behaviour: when the host is idle and the model is
  already resident, local inference still wins and nothing changes.
- Make every local→cloud hand-off loud (per rule: no silent switching).

**Non-goals (deferred)**
- Canary completion probes (`max_tokens=1`) — optional follow-up.
- Host telemetry sidecar on the GPU PC — rejected for now (new service to maintain).
- Changes to Gemini/OpenRouter/Mistral behaviour or chain order.

## 3. Approved design decisions

| Decision | Choice |
|---|---|
| Busy definition | HTTP signals + local OS metrics (no sidecar, no canary in v1) |
| Scope | LM Studio: full guard. llama.cpp / Ollama (Pi): latency + (`Ollama` only) resident-model check |
| Busy skip duration | short cooldown **120 s**, then one cheap re-probe (existing revive path) |
| Down (connect refused) | unchanged: 300 s cooldown |
| Ollama generation timeout | NEW cooldown after timeout (kill "retry every stage" waste) |
| Default state | **ON**, kill-switch `LOAD_GUARD=0` restores today's behaviour |
| New dependency | `psutil` (optional-import; guard degrades without it) |

## 4. Architecture

### 4.1 New module `investment_engine/providers/health.py`

Pure probe functions; **never raise**; every probe returns a verdict, not an error:

```python
@dataclass(frozen=True)
class Verdict:
    busy: bool
    reason: str            # "host busy: LM Studio model state=loading; GPU 92%>85%"
    evidence: dict[str, str]   # signal_name -> observed value (for run events)

def probe_provider_busy(name: str, base_url: str, settings) -> Verdict: ...
```

Signals evaluated per provider, first positive wins (order = cheapest first):

| Provider | Signal | Busy condition (default) |
|---|---|---|
| LM Studio | probe latency (existing preflight GET, min of 2 attempts) | latency > `LOAD_GUARD_LATENCY_MS` (2500 ms) |
| LM Studio | model state via existing `v1_models()` / v0 fallback | any model `state == "loading"` **and** exclusive_load=true (a load is already queued; we must not queue behind it) |
| LM Studio (localhost only*) | `psutil` CPU/RAM + `nvidia-smi` (GPU util, VRAM free) | CPU% > 85, RAM% > 90, GPU% > 85, VRAM free < 1500 MiB (any of) |
| llama.cpp | probe latency | latency > `LOAD_GUARD_LATENCY_MS` |
| Ollama | probe latency | latency > `LOAD_GUARD_LATENCY_MS` |
| Ollama | `GET /api/ps` (published Ollama API) | configured model **not resident** (cold) → busy (`model_cold`) |

`*` localhost = endpoint host is `127.0.0.1`, `localhost`, `::1` or the machine's own
hostname. Remote hosts never get OS-metric probes (metrics are meaningless cross-host).

**Graceful degradation (all signals):** endpoint variant unknown / `api/ps` absent /
`psutil` or `nvidia-smi` missing → that signal scores **not busy** and a `debug` line
records the degradation. The guard must never make decisions worse than today's.
Note: the exact LM Studio state-field semantics (`v0.model.state` vs `v1` key) get
verified live against the real server during implementation ("evidence first");
unit tests assert only the mapping of known candidate field names, not a guessed
schema.

**Anti-flap:** a single Tailscale latency spike must not exile the primary for 2 min.
Latency rules per provider, stated explicitly:
- **LM Studio** (2 preflight attempts, 10 s timeout each): busy only when **both**
  attempts exceed `LOAD_GUARD_LATENCY_MS`.
- **llama.cpp / Ollama** (1 preflight attempt, 2 s timeout): the endpoint must reply
  at all to be measured; any successful reply slower than the 2000 ms probe timeout
  window is already pathological → single measurement above `LOAD_GUARD_LATENCY_MS`
  counts as busy immediately.
Threshold is an env knob; defaults recorded above.

### 4.2 Integration points (existing machinery, no new subsystem)

1. `main.py:_note_unreachable_local_providers` — after the current 200-OK connect
   check, call `probe_provider_busy(...)`. Busy →
   `_record_fallback("provider-chain", f"{label} host busy …")` +
   `skip_for_run(label, reason, cooldown_s=120)`.
2. `main.py:_revive_locals_if_due` — when a cooldown expires and a re-probe gets
   HTTP 200, run the same busy probe before reviving (busy keeps it skipped for
   another 120 s).
3. `fallback.py` `ChainedFallbackProvider.generate()` — in the `res.timed_out`
   branch, add a model-scoped cooldown for local providers (LM Studio / llama.cpp /
   Ollama), default `LOCAL_TIMEOUT_COOLDOWN_S=300`, reason `local timeout`. Removes
   the "retry every stage after 90 s timeout" waste. No change for cloud providers'
   timeout behaviour.

### 4.3 Attribution & user-visible outputs

- Failure kinds: `host_busy` (probe verdict), `model_cold` (Ollama not resident),
  `local_timeout` (new). They flow through the existing `last_failure` →
  `model_substitution_reason` attribution without new plumbing.
- Log lines (LEVEL=INFO): `Preflight: LM Studio host busy (model state=loading) -> cloud API ~120s`
- Report provider note: reused `_provider_fallback_note()`; no report template change.

## 5. Configuration (settings.py + api.env)

```
LOAD_GUARD=1                       # 0 = feature off, behaviour identical to today
LOAD_GUARD_COOLDOWN_S=120          # busy skip duration
LOAD_GUARD_LATENCY_MS=2500         # probe latency threshold
LOAD_GUARD_LOCAL_CPU_PCT=85        # localhost-only metrics below
LOAD_GUARD_LOCAL_RAM_PCT=90
LOAD_GUARD_GPU_MAX_UTIL_PCT=85
LOAD_GUARD_VRAM_MIN_FREE_MIB=1500
LOAD_GUARD_NVIDIA_SMI=1            # micro-toggle for the GPU signal
LOCAL_TIMEOUT_COOLDOWN_S=300       # local provider timeout cooldown (4.2/3)
```

## 6. Testing

New `tests/test_load_guard.py` — no real network, all I/O monkeypatched:

1. Each signal positive → busy verdict with correct reason & evidence.
2. Each signal negative/absent → not busy (degradation paths: no psutil, no
   nvidia-smi, unknown LM Studio API, `/api/ps` missing).
3. Kill-switch: `LOAD_GUARD=0` → probe not called at all (mock spy).
4. Integration: preflight busy → `is_skipped("LM Studio")` true, cooldown `120`.
5. Revive re-probe busy → skip extended, not revived.
6. Ollama timeout → model-scoped cooldown set; second stage skips Ollama.
7. `reset_circuit_breaker()` clears all new state (no cross-test leakage).

Existing suites implicated: `test_preflight.py`, `test_provenance_truth.py`,
`test_providers_modes.py`, `test_provider_model_scoping.py` — must stay green.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| False positive on transient latency spike | two-attempt rule + threshold knob + short 120 s cooldown |
| LM Studio API variant drift (v0/v1/state field) | feature-detect; unknown = not busy; degrade loudly in debug |
| Pi keeps models warm only transiently (keep_alive) — model_cold could skip a Pi that *would* have loaded quickly | separate default `OLLAMA_REQUIRE_LOADED`-style toggle ships as config knob; false-negative direction is safe (falls back to cloud, never blocks locals) |
| Extra probe cost per run | 1–3 short HTTP requests inside the existing preflight pass; cached via existing model-state TTL caches |
| Silent local→cloud drift | loud INFO logs + report provider note + failure kinds in attribution |

## 8. Rollback

`LOAD_GUARD=0` (and `LOCAL_TIMEOUT_COOLDOWN_S=0` to restore no-cooldown timeouts)
returns the chain to current behaviour without a code revert.

## 9. Decision log (during design Q&A with user)

1. Busy detection: HTTP signals + local metrics (not canary, not sidecar) — approved.
2. Scope: LM Studio full, Pi latency-only → amended with `/api/ps` resident-model
   check after run `a13f2a48` evidence — approved.
3. Cooldown: 120 s for busy; NEW 300 s cooldown on local generation timeout — approved.
4. Default ON with kill-switch; psutil added as new dependency — approved.

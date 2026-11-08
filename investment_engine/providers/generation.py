"""LLM generation, routing, and provider fallback.

Extracted from ``main.py``. This module owns stage-to-model routing, local
provider pre-flight/revival, the chained generation path, and the deterministic
fallback used when every provider fails.
"""

from __future__ import annotations

import logging
import time

from investment_engine.providers.telemetry import (
    track_local_ai_attempt as _track_local_ai_attempt,
)
from investment_engine.run_state import FALLBACK_EVENTS as _FALLBACK_EVENTS
from investment_engine.run_state import STAGE_ATTRIBUTION as _STAGE_ATTRIBUTION

logger = logging.getLogger(__name__)

def _annotate_skill_output(output: dict, skill_name: str = "") -> dict:
    """Add execution_type and fallback_reason to a skill output.

    Truthful completion (WP1): when important analysis is replaced by a
    deterministic fallback, the status must NOT read as plain "OK"
    (no false "AI processing OK"). Fallback-shaped outputs are marked
    COMPLETED_WITH_FALLBACK. Validated LLM runs keep OK. Never raises.
    """
    if not isinstance(output, dict):
        return output
    if output.get("execution_type") and output.get("execution_reason"):
        return output
    status = str(output.get("status", "")).upper()
    enriched = bool((output.get("data", {}) or {}).get("enriched"))
    if status == "INSUFFICIENT_EVIDENCE":
        output.setdefault("execution_type", "FALLBACK")
        output.setdefault("execution_reason", "SKIPPED_INSUFFICIENT_EVIDENCE")
        output.setdefault("fallback_reason", output.get("reason", "insufficient evidence"))
        output["status"] = "INSUFFICIENT_EVIDENCE"
    elif enriched:
        output.setdefault("execution_type", "LLM")
        output.setdefault("execution_reason", "LLM_EXECUTED")
        output.setdefault("fallback_reason", "")
        output.setdefault("status", "OK")
    else:
        output.setdefault("execution_type", "DETERMINISTIC")
        output.setdefault("execution_reason", "DETERMINISTIC_BY_DESIGN")
        output.setdefault("fallback_reason", "")
        output["status"] = "DETERMINISTIC"
    if output.get("fallback_reason") and output.get("execution_type") in ("FALLBACK", "DETERMINISTIC"):
        output["status"] = "COMPLETED_WITH_FALLBACK"
    return output


def _note_deterministic_skill(stage: str, reason: str = "deterministic_by_design") -> None:
    """Record deterministic skill execution with human-readable reason."""
    try:
        from investment_engine.providers import attribution as _attr
        _rec = _attr.note_deterministic(_attr.new_stage_record(stage), "skills")
        _rec["execution_type"] = "DETERMINISTIC"
        _rec["reason"] = reason
        _STAGE_ATTRIBUTION[stage] = _rec
    except Exception:
        pass


def _record_fallback(stage: str, detail: str) -> None:
    label = f"{stage}: {detail}".strip()
    if label not in _FALLBACK_EVENTS:
        _FALLBACK_EVENTS.append(label)


def _note_unreachable_local_providers(settings) -> None:
    """Probe local LLM endpoints once; record a compact fallback event.

    Non-fatal by design: unreachable LM Studio/Ollama is reported in the
    report's provider note, never as a stack trace.
    """
    try:
        import requests as _rq
    except ImportError:
        return
    # Public/API-only mode: disabled local providers are never probed (no HTTP
    # calls, no timeout waits); the exclusion itself is recorded once.
    try:
        from investment_engine.config.settings import resolve_execution_mode as _em0
        _public = _em0(settings) == "public"
    except Exception:
        _public = bool(getattr(settings, "api_only", False))
    if _public:
        _record_fallback("provider-chain", "API-only mode: LM Studio, Ollama disabled, never probed")
        _track_local_ai_attempt(blocked=True)
        return
    lm_enabled = bool(getattr(settings, "lmstudio_enabled", True))
    try:
        from investment_engine.providers.fallback import PREFLIGHT_COOLDOWN_S as _CD
        from investment_engine.providers.fallback import skip_for_run as _skip
    except Exception:
        _skip, _CD = None, 300.0
    try:
        from investment_engine.providers import health as _health
        _guard_cooldown = int(getattr(settings, "load_guard_cooldown_s", 120) or 120)
    except Exception:
        _health = None
        _guard_cooldown = 120
    base_url_by_label = {
        "LM Studio": str(getattr(settings, "lm_studio_base_url", "") or ""),
        "Ollama": str(getattr(settings, "ollama_base_url", "") or ""),
    }
    for label, url in (
        ("LM Studio", f"{str(getattr(settings, 'lm_studio_base_url', '')).rstrip('/')}/models"),
        ("Ollama", f"{str(getattr(settings, 'ollama_base_url', '')).rstrip('/')}/api/tags"),
    ):
        if label == "LM Studio" and not lm_enabled:
            _record_fallback("provider-chain", "LM Studio disabled by policy")
            continue
        if not url or "://" not in url:
            continue
        # LM Studio is the primary provider: patient probe (slow Tailscale or
        # a model-load start must not exile it for the whole run on a hiccup).
        attempts = 2 if label == "LM Studio" else 1
        timeout = 10 if label == "LM Studio" else 2
        _ok, _detail = False, "pre-flight connect failed"
        _latencies: list[float] = []
        for _a in range(attempts):
            try:
                _t0 = time.monotonic()
                _r = _rq.get(url, timeout=timeout)
                _latencies.append(time.monotonic() - _t0)
                if _r.status_code == 200:
                    _ok = True
                    break
                _detail = f"pre-flight HTTP {_r.status_code}"
            except Exception:
                _detail = "pre-flight connect failed"
        if not _ok:
            _record_fallback("provider-chain", f"{label} unreachable")
            if _skip is not None:
                _skip(label, _detail, _CD)
            continue
        # Load guard: endpoint reachable but its host busy / model cold ->
        # skip to the cloud chain loudly for a short cooldown (never silently).
        if _health is not None and bool(_cfg_get(settings, "load_guard_enabled", True)):
            _verdict = _health.probe_provider_busy(
                label, base_url_by_label.get(label, ""), settings,
                latencies=_latencies if label == "LM Studio" else None,
            )
            if _verdict.busy:
                _record_fallback("provider-chain", f"{label} {_verdict.reason}")
                if _skip is not None:
                    _skip(label, _verdict.reason, _guard_cooldown)


def _execution_mode_lines(settings) -> list[str]:
    """Execution-mode report lines. Rendered in the decision brief when active."""
    try:
        from investment_engine.config.settings import resolve_execution_mode as _mode
        mode = _mode(settings)
    except Exception:
        mode = "auto"
    if mode == "public":
        return [
            "AI execution mode: API_ONLY",
            "Disabled providers: LM Studio, llama.cpp, Ollama",
        ]
    if mode == "locals":
        return [
            "AI execution mode: LOCALS_ONLY",
            "Cloud providers disabled: Gemini, Mistral, OpenRouter, OpenCode Zen",
        ]
    return []


def _model_for_stage(settings, stage: str) -> str:
    """Route stages to models: writer (fast) for summaries, reasoning otherwise.

    Stage map (LM Studio server ids, LM_Studio_Optimiser "best" 2026-10-01):
      summary            -> writer_model   (gemma-4-12b)
      discovery          -> thinking_model (gpt-oss-20b, 32k ctx)
      decision/ai_recs   -> finance_model  (qwen3.8-9b-distill, fast reasoning)
      everything else    -> decision_model (qwen3.8-9b-distill, chain default)
    The name is intent + attribution label; the chain serves its own fixed
    models except the direct LM Studio attempt below, which honors it.
    """
    try:
        from investment_engine.providers.presets import (
            FINANCE_STAGES,
            THINKING_STAGES,
            WRITER_STAGES,
        )
    except Exception:
        FINANCE_STAGES, THINKING_STAGES, WRITER_STAGES = frozenset(), frozenset(), frozenset({"summary"})
    get = (lambda k, d=None: settings.get(k, d)) if isinstance(settings, dict) else (lambda k, d=None: getattr(settings, k, d))
    try:
        if stage in WRITER_STAGES:
            return get("writer_model", None) or get("decision_model")
        if stage in THINKING_STAGES:
            return get("thinking_model", None) or get("decision_model")
        if stage in FINANCE_STAGES:
            return get("finance_model", None) or get("decision_model")
    except Exception:
        pass
    try:
        return get("decision_model")
    except Exception:
        return "qwen3.8-9b-distill"


def _cfg_get(settings, key, default=None):
    """Read a setting from an EngineSettings object or a plain dict."""
    try:
        if isinstance(settings, dict):
            return settings.get(key, default)
        return getattr(settings, key, default)
    except Exception:
        return default


def _revive_locals_if_due(provider, settings=None) -> None:
    """Re-probe pre-flight-skipped locals whose cooldown expired.

    Keeps LM Studio priority across long runs: a server that comes back
    mid-run is revived for all later stages. Cheap (one <=3s GET per due
    link); never raises.
    """
    try:
        import requests as _rq

        from investment_engine.providers.fallback import (
            PREFLIGHT_COOLDOWN_S as _CD,
        )
        from investment_engine.providers.fallback import (
            ChainedFallbackProvider as _Chain,
        )
        from investment_engine.providers.fallback import (
            due_for_reprobe as _due,
        )
        from investment_engine.providers.fallback import (
            revive as _revive,
        )
        from investment_engine.providers.fallback import (
            skip_for_run as _skip,
        )
        from investment_engine.providers.llamacpp import LlamaCppProvider as _LC
        from investment_engine.providers.lmstudio import LMStudioProvider as _LM
        from investment_engine.providers.ollama import OllamaProvider as _OL
    except Exception:
        return
    try:
        if isinstance(provider, _Chain):
            links = list(getattr(provider, "providers", []) or [])
        else:
            links = [provider]
    except Exception:
        return
    for link in links:
        try:
            name = getattr(link, "name", "")
            if not isinstance(link, (_LM, _LC, _OL)) or not _due(name):
                continue
            base = str(getattr(link, "base_url", "") or "").rstrip("/")
            url = (base + "/api/tags") if name == "Ollama" else (base + "/models")
            if "://" not in url:
                continue
            _r = _rq.get(url, timeout=3)
            if _r.status_code == 200:
                # Load-guard: endpoint reachable, but host may still be busy or
                # model not resident. Only revive when the busy-guard probe
                # reports the host is idle (not busy, not model-cold).
                try:
                    from investment_engine.providers import health as _health_check
                    _revive_probe = _health_check.probe_provider_busy(
                        name, base, settings)
                    if _revive_probe.busy:
                        # Host still busy / model cold: skip revival, apply cooldown.
                        from investment_engine.providers.fallback import (
                            skip_for_run as _skip_revive,
                        )
                        _skip_revive(name, _revive_probe.reason, 120)
                        logger.info("Preflight: %s is back (HTTP 200) but host busy (%s) — kept skipped ~120s", name, _revive_probe.reason)
                        continue
                except Exception as exc:
                    logger.debug("Preflight revive busy-check unavailable: %s", exc)
                # Host idle -> revive.
                _revive(name)
                logger.info("Preflight: %s is back, revived for later stages", name)
            else:
                _skip(name, f"re-probe HTTP {_r.status_code}", _CD)
        except Exception:
            try:
                _skip(name, "re-probe connect failed", _CD)
            except Exception:
                pass


def _try_lmstudio_stage(provider, prompt, *, settings, stage, tokens):
    """Direct per-stage LM Studio attempt. Returns (served_model, result).

    The chain strips per-call models (each link serves its fixed model), so
    stages with a designated LM Studio model (finance/thinking/writer) call
    the LM Studio link directly FIRST. (served_model, result) on success,
    (None, None) when LM Studio is disabled/absent/failed — the caller then
    uses the normal chain. Attribution stays truthful: served_model is the
    model id actually sent to the server.
    """
    try:
        if not bool(_cfg_get(settings, "lmstudio_enabled", False)):
            return None, None
        from investment_engine.providers.presets import (
            FINANCE_STAGES,
            THINKING_STAGES,
            WRITER_STAGES,
        )
        if stage not in (FINANCE_STAGES | THINKING_STAGES | WRITER_STAGES):
            return None, None
        stage_model = _model_for_stage(settings, stage)
        if not stage_model:
            return None, None
        try:
            from investment_engine.providers.fallback import is_skipped as _is_skipped
            if _is_skipped("LM Studio", stage_model):
                # This exact model was proven unavailable (the endpoint may
                # still serve other models), so skip only this stage's attempt.
                return None, None
        except Exception:
            pass
        from investment_engine.providers.fallback import ChainedFallbackProvider
        from investment_engine.providers.lmstudio import LMStudioProvider
        link = None
        if isinstance(provider, LMStudioProvider):
            link = provider
        elif isinstance(provider, ChainedFallbackProvider):
            for p in getattr(provider, "providers", []) or []:
                if isinstance(p, LMStudioProvider):
                    link = p
                    break
        if link is None:
            return None, None
        ctx = {"model": stage_model, "max_output_tokens": tokens}
        if stage in THINKING_STAGES:
            ctx["read_timeout_s"] = 1200  # gpt-oss-20b ~12 tok/s needs room past the 5min default
        elif stage in FINANCE_STAGES:
            # qwen3.8-9b-distill ~30 tok/s: 3072-token finance outputs need
            # ~2 min; 1200s keeps headroom (run 59adee12 showed the 300s
            # default killing healthy generations mid-stream).
            ctx["read_timeout_s"] = 1200
        result = link.generate(prompt, stage=stage, context=ctx)
        if result and not result.startswith(f"[{stage}]") and "error" not in result.lower():
            return stage_model, result
        return None, None
    except Exception:
        return None, None


def _generate_with_fallback(provider, prompt, settings, tokens=800, stage="decision") -> str:
    """Generate with fallback - let the provider handle fallback internally."""
    import time as _time
    start = _time.time()
    model = _model_for_stage(settings, stage)

    def _log_attempt(stage_name, model_name, success, duration, content_len, error=None):
        if success:
            logger.info("LLM stage=%s model=%s duration=%.1fs content_len=%d OK", stage_name, model_name, duration, content_len)
        else:
            logger.warning("LLM stage=%s model=%s duration=%.1fs FAILED: %s", stage_name, model_name, duration, error)

    # Single call - let the provider (FallbackProvider) handle fallback internally.
    # Phase 4: record the actual winner (or deterministic fallback) per stage.
    from investment_engine.providers import attribution as _attr

    record = _attr.new_stage_record(stage, model_requested=model)
    # Revive pre-flight-skipped locals whose cooldown expired (LM Studio
    # priority across long runs) before the direct attempt and the chain.
    try:
        _revive_locals_if_due(provider, settings)
    except Exception:
        pass
    # Direct per-stage LM Studio attempt first (designated finance/thinking/
    # writer model). The chain would strip the per-call model, so this is the
    # only path where the routed model is actually served.
    try:
        _served, _direct = _try_lmstudio_stage(provider, prompt, settings=settings,
                                               stage=stage, tokens=tokens)
        if _served and _direct:
            duration = _time.time() - start
            _log_attempt(stage, _served, True, duration, len(_direct))
            _STAGE_ATTRIBUTION[stage] = _attr.note_chain_winner(record, "LM Studio", _served, 0)
            try:
                _STAGE_ATTRIBUTION[stage]["duration_s"] = round(duration, 1)
            except Exception:
                pass
            return _direct
    except Exception:
        pass
    try:
        logger.debug(
            "LLM stage=%s prompt_chars=%d est_tokens~%d output_tokens=%d",
            stage, len(prompt), len(prompt) // 4, tokens,
        )
        result = provider.generate(prompt, stage=stage, context={"model": model, "max_output_tokens": tokens})
        duration = _time.time() - start
        if result and not result.startswith(f"[{stage}]") and "error" not in result.lower():
            # Telemetry must name the model that actually served the stage.
            # ``model`` is the requested id; the chain reports the served one.
            _hint = getattr(provider, "last_attribution", None)
            _served = _hint.get("model") if isinstance(_hint, dict) else None
            _log_attempt(stage, str(_served or model), True, duration, len(result))
            _STAGE_ATTRIBUTION[stage] = _attr.apply_chain_hint(record, provider)
            try:
                _STAGE_ATTRIBUTION[stage]["duration_s"] = round(duration, 1)
            except Exception:
                pass
            return result
        else:
            _log_attempt(stage, model, False, duration, len(result) if result else 0, result)
            _record_fallback(stage, getattr(provider, "name", "provider") + " returned no usable content")
            _attr.note_error(record, "no usable content")
    except Exception as exc:
        duration = _time.time() - start
        _log_attempt(stage, model, False, duration, 0, str(exc))
        _record_fallback(stage, "local endpoints unavailable")
        _attr.note_error(record, exc)

    # Deterministic fallback - configurable based on AI aggressiveness
    _STAGE_ATTRIBUTION[stage] = _attr.note_deterministic(
        record, str((settings.__dict__ if hasattr(settings, '__dict__') else {}).get("ai_aggressiveness", "balanced")))
    try:
        _STAGE_ATTRIBUTION[stage]["duration_s"] = round(_time.time() - start, 1)
    except Exception:
        pass
    return _deterministic_fallback(stage, language=str((settings.__dict__ if hasattr(settings, '__dict__') else {}).get("language", "English")), aggressiveness=str((settings.__dict__ if hasattr(settings, '__dict__') else {}).get("ai_aggressiveness", "balanced")))


def _deterministic_fallback(stage: str, language: str = "English", aggressiveness: str = "balanced") -> str:
    """Return a deterministic fallback response for a given stage.
    
    aggressiveness: "conservative" | "balanced" | "aggressive" | "very_aggressive"
    """
    # Base conservative fallbacks
    conservative = {
        "decision": "HOLD — insufficient data for actionable decision",
        "discovery": "None supported by current evidence.",
        "summary": "## Summary\n- Unable to generate AI summary due to model unavailability.\n- Regime-based DCA schedule continues per configuration.\n- Reconciliation status determines data reliability.\n\n_Deterministic fallback in use — Priority Actions are generated from canonical portfolio rows below._",
        "ai_recommendations": '{"portfolio_actions": [], "trades": [], "position_updates": [], "cash_deployment": {"free_cash": 0, "deploy_amount": 0, "deploy_pct": 0, "reserve": 0, "targets": []}}',
    }
    
    # Aggressive fallbacks - more willing to act on limited data
    aggressive = {
        "decision": "HOLD — limited data; regime suggests cautious accumulation on dips",
        "discovery": "Scan watchlist for oversold quality names; prioritize high-conviction sectors.",
        "summary": "## Summary\n- AI model unavailable; using regime-based heuristic.\n- Regime signals primary driver; DCA continues per config.\n- Monitor watchlist for entry signals on volatility spikes.\n\n_Deterministic fallback (aggressive) — Priority Actions from canonical rows._",
        "ai_recommendations": '{"portfolio_actions": [{"action": "hold", "asset": "WATCHLIST", "reason": "monitor for entry signals"}], "trades": [], "position_updates": [], "cash_deployment": {"free_cash": 0, "deploy_amount": 0, "deploy_pct": 0, "reserve": 0, "targets": []}}',
    }
    
    # Very aggressive - willing to act on regime signals alone
    very_aggressive = {
        "decision": "BUY on dips / SELL on rips per regime — limited data but regime is clear",
        "discovery": "Aggressive scan: high-momentum watchlist names + oversold quality.",
        "summary": "## Summary\n- AI offline; aggressive regime-based heuristic active.\n- Deploying cash per regime signals; tight stops on all entries.\n- Watchlist prioritized for gap-up/breakout entries.\n\n_Deterministic fallback (very_aggressive) — Regime-driven actions._",
        "ai_recommendations": '{"portfolio_actions": [{"action": "buy", "asset": "WATCHLIST", "reason": "regime-driven accumulation"}], "trades": [], "position_updates": [], "cash_deployment": {"free_cash": 0, "deploy_amount": 0, "deploy_pct": 0, "reserve": 0, "targets": []}}',
    }
    
    profiles = {
        "conservative": conservative,
        "balanced": conservative,  # default safe
        "aggressive": aggressive,
        "very_aggressive": very_aggressive,
    }
    
    profile = profiles.get(aggressiveness.lower(), conservative)
    return profile.get(stage, "Data unavailable - model error")

# Public aliases for cross-module use (private names remain the
# implementation detail and stay available for in-module calls).
annotate_skill_output = _annotate_skill_output
note_deterministic_skill = _note_deterministic_skill
record_fallback = _record_fallback
note_unreachable_local_providers = _note_unreachable_local_providers
execution_mode_lines = _execution_mode_lines
model_for_stage = _model_for_stage
cfg_get = _cfg_get
revive_locals_if_due = _revive_locals_if_due
try_lmstudio_stage = _try_lmstudio_stage
generate_with_fallback = _generate_with_fallback
deterministic_fallback = _deterministic_fallback

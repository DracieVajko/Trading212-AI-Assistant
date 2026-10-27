from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from .base import BaseLLMProvider

from investment_engine import liveness as _lv
from investment_engine.reporting.run_history import record_run_event

logger = logging.getLogger(__name__)


def _record_event(event: dict) -> None:
    """Append a run event. Never raises; uses run_history with sanitization."""
    try:
        path = os.getenv("RUN_EVENTS_PATH", "reports/run_events.jsonl")
        record_run_event(path, event)
    except Exception:
        pass


# Per-run circuit breaker: unavailable providers are skipped for the rest of
# the run instead of retried at every stage (LM Studio/Ollama down, Gemini
# 429 rate-limit). No stack traces; one concise log line per trip.
_SKIP_REST_OF_RUN: set[str] = set()
_SKIP_UNTIL: dict[str, float] = {}
_SKIP_REASON: dict[str, str] = {}
_GEMINI_SKIP_UNTIL: float = 0.0

#: Pre-flight skips are cooldown-based (not permanent): a local server that
#: comes back mid-run is revived by _revive_locals_if_due (LM Studio priority).
PREFLIGHT_COOLDOWN_S = 300.0

#: One local server can serve several models (LM Studio: gpt-oss for finance,
#: gemma for summaries). Breaker state is therefore model-scoped: a missing
#: model must not exile the sibling models that are actually served. A bare
#: provider name stays provider-level (endpoint unreachable -> all models).
_MODEL_KEY_SEP = "\x1f"


def provider_key(name: str, model: str | None = None) -> str:
    """Breaker key. Bare name = provider-wide, name+model = one served model."""
    key = str(name or "")
    mdl = str(model or "")
    return f"{key}{_MODEL_KEY_SEP}{mdl}" if key and mdl else key


def _provider_model(provider: BaseLLMProvider) -> str:
    return str(getattr(provider, "model", "") or "")


def _is_rate_limited(result: str) -> bool:
    low = (result or "").lower()
    return "429" in low or "resource_exhausted" in low or "quota exceeded" in low


def _retry_after_seconds(result: str) -> float:
    m = re.search(r"retry in ([\d.]+)s", result or "")
    try:
        return float(m.group(1)) if m else float("inf")
    except (TypeError, ValueError):
        return float("inf")


def reset_circuit_breaker() -> None:
    """Clear per-run skip state (called at engine start)."""
    _SKIP_REST_OF_RUN.clear()
    _SKIP_UNTIL.clear()
    _SKIP_REASON.clear()
    global _GEMINI_SKIP_UNTIL
    _GEMINI_SKIP_UNTIL = 0.0


def _skip_reason(name: str, model: str | None = None) -> str:
    """Human-readable reason recorded when the provider was skipped."""
    for key in (provider_key(str(name or ""), model), str(name or "")):
        if key and key in _SKIP_REASON:
            return _SKIP_REASON[key]
    return ""


def is_skipped(name: str, model: str | None = None) -> bool:
    """True when a provider (or one of its models) is currently skipped.

    ``model`` omitted: provider-wide state only. ``model`` given: provider-wide
    state OR state recorded for that exact model. Permanent run-skips and
    unexpired pre-flight cooldowns both count. Never mutates, never raises.
    """
    try:
        key = str(name or "")
        if not key:
            return False
        keys = [key]
        if model:
            keys.append(provider_key(key, model))
        now = time.time()
        for k in keys:
            if k in _SKIP_REST_OF_RUN:
                return True
            until = _SKIP_UNTIL.get(k)
            if until is not None and now < float(until):
                return True
        return False
    except Exception:
        return False


def due_for_reprobe(name: str, model: str | None = None) -> bool:
    """True when a pre-flight cooldown expired and the link deserves one cheap re-probe."""
    try:
        key = provider_key(str(name or ""), model)
        until = _SKIP_UNTIL.get(key) if key else None
        if until is None:
            return False
        return time.time() >= float(until)
    except Exception:
        return False


def revive(name: str, model: str | None = None) -> None:
    """Clear skip state. ``model`` omitted clears the provider and every model
    of it (endpoint is back); ``model`` given clears only that model."""
    try:
        key = str(name or "")
        if not key:
            return
        if model:
            mk = provider_key(key, model)
            _SKIP_REST_OF_RUN.discard(mk)
            _SKIP_UNTIL.pop(mk, None)
            _SKIP_REASON.pop(mk, None)
            return
        _SKIP_REST_OF_RUN.discard(key)
        _SKIP_UNTIL.pop(key, None)
        _SKIP_REASON.pop(key, None)
        prefix = key + _MODEL_KEY_SEP
        for k in list(_SKIP_REST_OF_RUN):
            if k.startswith(prefix):
                _SKIP_REST_OF_RUN.discard(k)
        for k in list(_SKIP_UNTIL):
            if k.startswith(prefix):
                _SKIP_UNTIL.pop(k, None)
        for k in list(_SKIP_REASON):
            if k.startswith(prefix):
                _SKIP_REASON.pop(k, None)
    except Exception:
        pass


def skip_for_run(
    name: str,
    reason: str = "",
    cooldown_s: float = 0.0,
    model: str | None = None,
) -> None:
    """Mark a provider (or one of its models) skipped.

    cooldown_s > 0: pre-flight path — skipped until now+cooldown, then one
    cheap re-probe may revive it (LM Studio priority across long runs).
    cooldown_s <= 0: permanent run-skip (mid-run failure after burnt retries).
    ``model`` scopes the skip to one served model.
    One concise log line on first trip; never raises.
    """
    try:
        key = provider_key(name, model)
        if not key:
            return
        label = f"{name} [{model}]" if model else str(name or "")
        try:
            cooldown = float(cooldown_s or 0.0)
        except (TypeError, ValueError):
            cooldown = 0.0
        if cooldown > 0:
            if key in _SKIP_REST_OF_RUN:
                return
            first = key not in _SKIP_UNTIL
            _SKIP_UNTIL[key] = time.time() + cooldown
            _SKIP_REASON[key] = str(reason or "unavailable")
            if first:
                logger.info("Preflight: skipping %s for ~%.0fs%s",
                            label, cooldown, f" ({reason})" if reason else "")
            return
        if key not in _SKIP_REST_OF_RUN:
            _SKIP_REST_OF_RUN.add(key)
            _SKIP_REASON[key] = str(reason or "unavailable")
            logger.info("Preflight: skipping %s for the rest of the run%s",
                        label, f" ({reason})" if reason else "")
    except Exception:
        pass


def _is_error_result(result: str, stage: str) -> bool:
    """Detect provider error strings that should trigger fallback."""
    if not isinstance(result, str):
        return True
    r = result.strip()
    if not r:
        return True
    # Common error markers returned by providers (not exceptions)
    markers = [
        f"[{stage}]",
        "not configured",
        "returned no choices",
        "returned an empty response",
        "returned no content",
        "returned no candidates",
        "timeout after",
        "rate limited",
    ]
    # If starts with [stage] it's an error string
    if r.startswith(f"[{stage}]"):
        return True
    # Fallback on generic markers
    low = r.lower()
    for m in markers:
        if m.lower() in low and r.startswith("["):
            return True
    return False


class FallbackProvider(BaseLLMProvider):
    """Wrap a primary provider with a fallback provider."""

    def __init__(self, primary: BaseLLMProvider, fallback: BaseLLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def name(self) -> str:
        return f"Fallback({self.primary.name}/{self.fallback.name})"

    def generate(self, prompt: str, *, stage: str, context: dict | None = None) -> str:
        # Use each provider's own default model - don't pass model from context to primary
        primary_context = {k: v for k, v in (context or {}).items() if k != "model"}
        fallback_context = {k: v for k, v in (context or {}).items() if k != "model"}
        
        try:
            primary_result = self.primary.generate(prompt, stage=stage, context=primary_context)
            if _is_error_result(primary_result, stage):
                logger.warning("FallbackProvider: primary (%s) returned error: %s. Trying fallback (%s)",
                               self.primary.name, primary_result[:200], self.fallback.name)
                raise RuntimeError(primary_result)
            _m = _provider_model(self.primary)
            logger.info("FallbackProvider: provider %s%s succeeded at stage %s",
                        self.primary.name, f" model={_m}" if _m else "", stage)
            return primary_result
        except Exception as exc:
            # Primary provider raised an exception - fall back
            logger.warning("FallbackProvider: primary (%s) failed: %s. Trying fallback (%s)", 
                          self.primary.name, exc, self.fallback.name)
            try:
                result = self.fallback.generate(prompt, stage=stage, context=fallback_context)
                if _is_error_result(result, stage):
                    # If fallback chain handles it, let it bubble; otherwise raise
                    # Check if fallback is also a chain – if it returns error, we still want to raise to trigger outer fallback
                    # For single fallback, return error string as final fallback
                    # Detect if fallback is chain by checking name
                    if "Fallback" in self.fallback.name and _is_error_result(result, stage):
                        raise RuntimeError(result)
                return result
            except Exception as fallback_exc:
                logger.error("FallbackProvider: fallback (%s) also failed: %s", 
                            self.fallback.name, fallback_exc)
                raise


class ChainedFallbackProvider(BaseLLMProvider):
    """Chain of providers – tries each in order until one succeeds (no error string)."""

    def __init__(self, providers: list[BaseLLMProvider]) -> None:
        if not providers:
            raise ValueError("ChainedFallbackProvider requires at least one provider")
        self.providers = providers
        # Phase 4 attribution hint (read by providers.attribution.apply_chain_hint).
        self.last_attribution: dict = {}

    @property
    def name(self) -> str:
        return "Chain(" + "->".join(p.name for p in self.providers) + ")"

    def _eligible(self) -> list[BaseLLMProvider]:
        now = time.time()
        out = []
        for p in self.providers:
            if is_skipped(p.name, _provider_model(p)):
                continue
            if p.name == "Gemini" and now < _GEMINI_SKIP_UNTIL:
                continue
            out.append(p)
        return out or list(self.providers)

    def generate(self, prompt: str, *, stage: str, context: dict | None = None) -> str:
        import time as _t
        clean_context = {k: v for k, v in (context or {}).items() if k != "model"} if context else {}
        last_exc: Exception | None = None
        last_result: str | None = None
        last_failure: dict[str, str] = {}
        self.last_attribution = {}
        # If the configured primary was pre-flight-skipped it never enters
        # _eligible(), yet it is still the reason the caller got a fallback.
        try:
            _first = self.providers[0] if self.providers else None
            if _first is not None and is_skipped(_first.name, _provider_model(_first)):
                last_failure = {
                    "provider": _first.name,
                    "kind": _skip_reason(_first.name, _provider_model(_first)) or "unavailable",
                }
        except Exception:
            pass
        import os as _os
        chain_budget_s = float(_os.getenv("CHAIN_BUDGET_SECONDS", "180"))
        attempt_max_s = float(_os.getenv("PROVIDER_ATTEMPT_MAX_S", "90"))
        started = _t.monotonic()

        # cooldown registry per run (process-global)
        if not hasattr(ChainedFallbackProvider, "_run_cooldowns"):
            ChainedFallbackProvider._run_cooldowns = {}  # provider_name -> expiry_ts
        if not hasattr(ChainedFallbackProvider, "_run_cooldown_kind"):
            ChainedFallbackProvider._run_cooldown_kind = {}  # provider_name -> kind

        for depth, provider in enumerate(self._eligible()):
            # Check chain budget first (including zero/negative budget = no attempts allowed)
            elapsed = _t.monotonic() - started
            if elapsed > chain_budget_s or chain_budget_s <= 0:
                logger.warning("ChainedFallback: chain budget exhausted (%.0fs), skipping remaining providers", chain_budget_s)
                _lv.emit_event({"event": "budget_exhausted", "stage": stage, "scope": "chain",
                                "remaining_s": max(0.0, chain_budget_s - elapsed), "budget_s": chain_budget_s})
                raise _lv.ChainBudgetExceeded(f"provider chain budget exhausted after {chain_budget_s}s")

            # Per-run cooldown check (model-scoped: another model on the same
            # server may still be servable)
            pname = provider.name
            pmodel = _provider_model(provider)
            pkey = provider_key(pname, pmodel)
            now_ts = _t.monotonic()
            cool_until = ChainedFallbackProvider._run_cooldowns.get(pkey)
            if cool_until and now_ts < cool_until:
                if not last_failure:
                    last_failure = {
                        "provider": pname,
                        "kind": (ChainedFallbackProvider._run_cooldown_kind.get(pkey)
                                 or "cooldown"),
                    }
                _lv.emit_event({"event": "provider_skipped", "stage": stage, "provider": pname,
                                "model": pmodel,
                                "reason": "cooldown",
                                "kind": ChainedFallbackProvider._run_cooldown_kind.get(pkey, "unknown")})
                continue

            # Bounded attempt with its own budget (min of remaining chain + attempt max)
            remaining = chain_budget_s - (_t.monotonic() - started)
            attempt_timeout = min(attempt_max_s, max(1.0, remaining))
            inv_id = _lv.new_invocation_id()
            _lv.emit_event({"event": "provider_attempt_start", "stage": stage, "provider": pname,
                            "invocation_id": inv_id, "attempt_deadline_s": round(attempt_timeout, 1),
                            "chain_budget_remaining_s": round(remaining, 1),
                            "fallback_depth": depth})

            def _call_provider():
                return provider.generate(prompt, stage=stage, context=clean_context)

            res = _lv.run_bounded(_call_provider, attempt_timeout, stage=stage,
                                  event_name="provider_attempt",
                                  detail=f"provider={pname} depth={depth}")

            dur = res.duration_s
            if res.timed_out:
                # Worker abandoned - terminal event synthesized by run_bounded
                _lv.note_degraded(stage, f"provider {pname} timed out after {attempt_timeout:.0f}s")
                last_failure = {"provider": pname, "kind": "timeout"}
                _lv.emit_event({"event": "fallback_transition", "stage": stage,
                                "from_provider": pname, "to_provider": "next",
                                "reason": "attempt_timeout", "failure_kind": "timeout",
                                "invocation_id": inv_id})
                _lv.emit_event({"event": "provider_attempt", "stage": stage, "provider": pname,
                                "outcome": "timed_out", "duration_s": dur,
                                "invocation_id": inv_id, "terminal_synthesized": True,
                                "note": "worker abandoned; no terminal event from worker"})
                # No cooldown on simple timeout (transient network) - but budget consumed
                continue

            # Even if bounded call succeeded, check if provider returned an error string
            value = res.value
            if isinstance(value, str) and _is_error_result(value, stage):
                logger.warning("ChainedFallback: provider %s returned error, trying next: %s", pname, value[:200])
                _lv.emit_event({"event": "provider_attempt", "stage": stage, "provider": pname,
                                "outcome": "error_result", "duration_s": dur, "error": str(value)[:200],
                                "invocation_id": inv_id})
                last_result = value
                last_exc = RuntimeError(value)
                # Apply cooldown based on classified error
                fi = _lv.classify_failure(text=value)
                last_failure = {"provider": pname, "kind": fi.kind}
                cool = _lv.cooldown_for_failure(fi)
                if cool:
                    kind, val = cool
                    if kind == "run":
                        ChainedFallbackProvider._run_cooldowns[pkey] = float("inf")
                    else:
                        ChainedFallbackProvider._run_cooldowns[pkey] = _t.monotonic() + val
                    ChainedFallbackProvider._run_cooldown_kind[pkey] = fi.kind
                # Legacy circuit breaker for local providers (backward compat).
                # Model-scoped: a missing model must not exile the models the
                # same server does serve.
                if pname in ("LM Studio", "Ollama", "llama.cpp"):
                    skip_for_run(pname, model=pmodel)
                # Gemini quota (rate_limited with RESOURCE_EXHAUSTED) -> skip for rest of run
                if pname == "Gemini" and fi.kind == "rate_limited":
                    _SKIP_REST_OF_RUN.add(pname)
                    logger.info("Gemini quota exhausted (rate_limited), skipping for rest of run")
                _lv.emit_event({"event": "fallback_transition", "stage": stage,
                                "from_provider": pname, "to_provider": "next",
                                "reason": fi.kind, "failure_kind": fi.kind,
                                "http_status": fi.http_status, "retry_after_s": fi.retry_after_s,
                                "invocation_id": inv_id})
                continue

            if not res.ok:
                exc = res.error
                fi = _lv.classify_failure(exc=exc)
                last_failure = {"provider": pname, "kind": fi.kind}
                logger.warning("ChainedFallback: provider %s failed: %s (kind=%s)", pname, exc, fi.kind)
                last_exc = exc if exc else RuntimeError(str(res.error))
                last_result = str(exc) if exc else ""
                # Apply cooldown based on classified kind
                cool = _lv.cooldown_for_failure(fi)
                if cool:
                    kind, val = cool
                    if kind == "run":
                        ChainedFallbackProvider._run_cooldowns[pkey] = float("inf")
                    else:
                        ChainedFallbackProvider._run_cooldowns[pkey] = _t.monotonic() + val
                    ChainedFallbackProvider._run_cooldown_kind[pkey] = fi.kind
                # Legacy circuit breaker for local providers (backward compat).
                # Model-scoped: a missing model must not exile the models the
                # same server does serve.
                if pname in ("LM Studio", "Ollama", "llama.cpp"):
                    skip_for_run(pname, model=pmodel)
                # Gemini quota (rate_limited with RESOURCE_EXHAUSTED) -> skip for rest of run
                if pname == "Gemini" and fi.kind == "rate_limited":
                    _SKIP_REST_OF_RUN.add(pname)
                    logger.info("Gemini quota exhausted (rate_limited), skipping for rest of run")
                _lv.emit_event({"event": "fallback_transition", "stage": stage,
                                "from_provider": pname, "to_provider": "next",
                                "reason": fi.kind, "failure_kind": fi.kind,
                                "http_status": fi.http_status, "retry_after_s": fi.retry_after_s,
                                "invocation_id": inv_id})
                continue

            # Success
            model = _provider_model(provider)
            logger.info("ChainedFallback: provider %s%s succeeded at stage %s (served_model=%s fallback_depth=%d)",
                        provider.name, f" model={model}" if model else "", stage,
                        model or provider.name, depth)
            _lv.emit_event({"event": "provider_attempt", "stage": stage, "provider": provider.name,
                            "outcome": "success", "duration_s": dur, "model": model or provider.name,
                            "fallback_depth": depth, "invocation_id": inv_id})
            attribution = {"provider": provider.name,
                           "model": model or provider.name,
                           "depth": depth}
            if last_failure:
                # Carry the immediate cause so the manifest can say WHY the
                # requested model was replaced instead of a bare "unknown".
                attribution["from_provider"] = last_failure.get("provider", "")
                attribution["failure_kind"] = last_failure.get("kind", "")
            self.last_attribution = attribution
            return res.value

        # All providers exhausted/failed
        _lv.emit_event({"event": "budget_exhausted", "stage": stage, "scope": "providers",
                        "remaining_s": 0.0, "budget_s": chain_budget_s})
        if last_exc:
            raise last_exc
        raise RuntimeError(last_result or "All providers in chain failed")

    @staticmethod
    def reset_run_cooldowns() -> None:
        """Clear per-run cooldowns (called at engine start)."""
        ChainedFallbackProvider._run_cooldowns = {}
        ChainedFallbackProvider._run_cooldown_kind = {}

from __future__ import annotations

import logging
import threading
import time

import requests

from .base import BaseLLMProvider
from .context_budget import (
    context_is_sufficient as _context_is_sufficient,
    context_target as _context_target,
)
from investment_engine.providers.presets import merge_sampling, preset_for

logger = logging.getLogger(__name__)

# Global lock for model warm-up
_warmup_lock = threading.Lock()
_model_warmed = set()
_model_failed = set()  # Cache models that failed to load

# Pre-flight cache: base_url -> (timestamp, frozenset(ids) | None).
# None means "unknown" (endpoint unreachable) — never a reason to skip.
_server_models_cache: dict[str, tuple[float, frozenset | None]] = {}
_SERVER_MODELS_TTL_S = 120.0

# Model loads on LM Studio take 6-60s (large models). The warmup read budget
# must cover the load, otherwise our own disconnect aborts the server-side
# startup ("Client disconnected. Stopping generation...") and every retry
# fails the same way. Seen live 2026-09-28: qwen (~6s load) passed with a
# 10s budget while slow loaders never finished in time.
_WARMUP_CONNECT_S = 15
_WARMUP_READ_S = 120


def server_model_ids(base_url: str) -> frozenset | None:
    """Best-effort ids from GET /v1/models. None = unknown, proceed as before.

    Never raises. Cached briefly so per-stage pre-flights cost one request.
    """
    base = (base_url or "").rstrip("/")
    now = time.time()
    hit = _server_models_cache.get(base)
    if hit is not None and (now - hit[0]) < _SERVER_MODELS_TTL_S:
        return hit[1]
    try:
        r = requests.get(f"{base}/models", timeout=(_WARMUP_CONNECT_S, 15))
        if r.status_code == 200:
            data = r.json().get("data") or []
            ids = frozenset(str(d.get("id", "")) for d in data
                             if isinstance(d, dict) and d.get("id"))
            _server_models_cache[base] = (now, ids)
            return ids
    except Exception as exc:
        logger.debug("LM Studio /v1/models unreachable on %s: %s", base, exc)
    _server_models_cache[base] = (now, None)
    return None


def reset_server_models_cache() -> None:
    """Clear the pre-flight cache (tests, server model changes)."""
    _server_models_cache.clear()


# ---------------------------------------------------------------------------
# LM Studio v1 REST API: model management with an explicit context length.
# v0 only lists models; load/unload live under /api/v1 (LM Studio 0.4+).
# ---------------------------------------------------------------------------
_v1_models_cache: dict[str, tuple[float, dict | None]] = {}
_V1_MODELS_TTL_S = 15.0


def reset_v1_models_cache() -> None:
    """Clear the v1 model-state cache (tests, after load/unload)."""
    _v1_models_cache.clear()


def _root_url(base_url: str) -> str:
    """Server root without the /v1 suffix."""
    base = (base_url or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base.rstrip("/")


def v1_models(base_url: str) -> dict | None:
    """Map model key -> v1 entry. None = v1 API unavailable (older server)."""
    base = _root_url(base_url)
    now = time.time()
    hit = _v1_models_cache.get(base)
    if hit is not None and (now - hit[0]) < _V1_MODELS_TTL_S:
        return hit[1]
    try:
        r = requests.get(f"{base}/api/v1/models", timeout=(3, 8))
        if r.status_code == 200:
            models = r.json().get("models") or []
            out = {
                str(m.get("key")): m
                for m in models
                if isinstance(m, dict) and m.get("key")
            }
            _v1_models_cache[base] = (now, out)
            return out
        logger.debug("LM Studio v1 /models returned %s", r.status_code)
    except Exception as exc:
        logger.debug("LM Studio v1 /models unreachable on %s: %s", base, exc)
    _v1_models_cache[base] = (now, None)
    return None


def _unsupported_endpoint(text: str) -> bool:
    """LM Studio answers unknown routes with HTTP 200 + an error payload."""
    return "unexpected endpoint" in str(text or "").lower()


def load_model_v1(
    base_url: str,
    model: str,
    context_length: int,
    *,
    timeout: tuple[int, int] = (5, 600),
) -> dict | None:
    """POST /api/v1/models/load with an explicit context. Never raises."""
    base = _root_url(base_url)
    try:
        r = requests.post(
            f"{base}/api/v1/models/load",
            json={
                "model": model,
                "context_length": int(context_length),
                "echo_load_config": True,
            },
            timeout=timeout,
        )
        if r.status_code == 200 and not _unsupported_endpoint(r.text):
            data = r.json()
            if data.get("instance_id") or data.get("status") == "loaded":
                _v1_models_cache.pop(base, None)
                cfg = data.get("load_config") or {}
                logger.info(
                    "LM Studio loaded %s (context=%s, %.1fs)",
                    model, cfg.get("context_length", context_length),
                    float(data.get("load_time_seconds") or 0.0),
                )
                return data
        logger.warning("LM Studio load %s -> HTTP %s: %s",
                       model, r.status_code, (r.text or "")[:200])
    except Exception as exc:
        logger.warning("LM Studio load %s failed: %s", model, exc)
    return None


def unload_model_v1(
    base_url: str,
    instance_id: str,
    *,
    timeout: tuple[int, int] = (5, 120),
) -> bool:
    """POST /api/v1/models/unload. Never raises."""
    base = _root_url(base_url)
    try:
        r = requests.post(
            f"{base}/api/v1/models/unload",
            json={"instance_id": instance_id},
            timeout=timeout,
        )
        if r.status_code == 200 and not _unsupported_endpoint(r.text):
            _v1_models_cache.pop(base, None)
            logger.info("LM Studio unloaded %s", instance_id)
            return True
        if r.status_code == 404 and "not loaded" in (r.text or "").lower():
            # Idempotent: the exit sweep must not warn about a model that was
            # already evicted (or unloaded when switching models).
            _v1_models_cache.pop(base, None)
            logger.debug("LM Studio unload %s: already unloaded", instance_id)
            return True
        logger.warning("LM Studio unload %s -> HTTP %s: %s",
                       instance_id, r.status_code, (r.text or "")[:200])
    except Exception as exc:
        logger.warning("LM Studio unload %s failed: %s", instance_id, exc)
    return False


def _other_loaded_instances(entries: dict, keep: str) -> list[str]:
    """Instance ids of LLMs loaded besides ``keep`` (embeddings left alone)."""
    out: list[str] = []
    for key, entry in (entries or {}).items():
        if key == keep or not isinstance(entry, dict):
            continue
        if str(entry.get("type") or "llm") != "llm":
            continue
        for inst in entry.get("loaded_instances") or []:
            if isinstance(inst, dict):
                out.append(str(inst.get("id") or key))
    return out


def ensure_model_context(
    base_url: str,
    model: str,
    context_length: int,
    *,
    exclusive: bool = False,
) -> dict:
    """Ensure ``model`` is loaded at (approximately) ``context_length``.

    Reloads when the loaded context is too small or grossly oversized
    (e.g. the server's 262144 default). ``exclusive=True`` unloads other LLM
    instances first, so a 9B and a 26B never occupy VRAM together (the
    Ollama-style single-model policy). Never raises.
    """
    target = int(context_length)
    entries = v1_models(base_url)
    if entries is None:
        return {"status": "v1_unavailable", "context_length": target}
    entry = entries.get(model)
    if entry is None:
        return {"status": "not_served", "context_length": target}
    max_ctx = int(entry.get("max_context_length") or 0)
    if max_ctx > 0:
        target = min(target, max_ctx)
    instances = entry.get("loaded_instances") or []
    if instances:
        inst = instances[0] if isinstance(instances[0], dict) else {}
        current = int((inst.get("config") or {}).get("context_length") or 0)
        if _context_is_sufficient(current, target):
            return {"status": "already_loaded", "context_length": current}
        unload_model_v1(base_url, str(inst.get("id") or model))
    if exclusive:
        for instance_id in _other_loaded_instances(entries, keep=model):
            unload_model_v1(base_url, instance_id)
    loaded = load_model_v1(base_url, model, target)
    if loaded:
        return {"status": "loaded", "context_length": target}
    return {"status": "load_failed", "context_length": target}


class LMStudioProvider(BaseLLMProvider):
    """LM Studio provider using the configured local endpoint (OpenAI-compatible)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1234/v1",
        model: str = "oda-fin-rl-8b",
        max_context_tokens: int = 32000,
        max_output_tokens: int = 8192,
        timeout_seconds: int = 7200,  # 2 hours for long model loading/generation
        reasoning_effort: str = "",
        auto_load: bool = True,
        exclusive_load: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        # Opt-in: Qwen3.5-family models default to thinking mode on LM Studio
        # (all tokens in reasoning_content, empty content -> rejected). Sending
        # reasoning_effort="none" makes them answer directly. "" = don't send,
        # so non-thinking models keep the previous payload.
        self.reasoning_effort = str(reasoning_effort or "")
        # Load the model ourselves with a minimal context (LM Studio otherwise
        # keeps it at the model maximum, e.g. 262144 -> KV cache spill).
        self.auto_load = bool(auto_load)
        # Single-model policy: unload the previous LLM before loading this one
        # (same behaviour Ollama gives for free).
        self.exclusive_load = bool(exclusive_load)
        self._connect_timeout = 60  # seconds to establish connection
        self._read_timeout = 7200    # seconds to read response (model generation) - 2 hours

    @property
    def name(self) -> str:
        return "LM Studio"

    def _ensure_context(self, model: str, prompt_tokens: int, output_tokens: int) -> None:
        """Load the model at a context sized for this call. Never raises."""
        if not self.auto_load:
            return
        try:
            target = _context_target(prompt_tokens, output_tokens, self.max_context_tokens)
            ensure_model_context(self.base_url, model, target, exclusive=self.exclusive_load)
        except Exception as exc:
            logger.debug("LM Studio context ensure skipped for %s: %s", model, exc)

    def _warmup_model(self, model: str, prompt_tokens: int = 0, output_tokens: int = 0) -> None:
        """Ensure the model is loaded at a sane context, then warm it up."""
        key = (self.base_url, model)
        if key in _model_failed:
            raise RuntimeError(f"Model '{model}' previously failed to load")
        # Context check runs on every call: a later stage may need more room.
        # v1 model state is cached briefly, so this is one cheap GET per TTL.
        self._ensure_context(model, prompt_tokens, output_tokens)
        if key in _model_warmed:
            return
        with _warmup_lock:
            if key in _model_warmed:
                return
            if key in _model_failed:
                raise RuntimeError(f"Model '{model}' previously failed to load")
            # Pre-flight: skip models the server does not serve instead of
            # burning a warmup + 30s retry + failed generation on each stage.
            # Transient (NOT cached in _model_failed): the user may load the
            # model into LM Studio mid-run and the next stage retries.
            known = server_model_ids(self.base_url)
            if known is not None and model not in known:
                raise RuntimeError(
                    f"Model '{model}' not served by LM Studio "
                    f"(server has: {sorted(known) or 'none'})")
            logger.info("Warming up model %s on %s...", model, self.base_url)
            _BUSY_MARKERS = (
                "already loaded",
                "already loaded",
                "model is currently loaded",
                "model is currently in use",
                "currently in use",
                "currently in use",
                "is busy",
                "model is busy",
                "server is busy",
            )
            _MAX_WARMUP_RETRIES = 3
            _WARMUP_RETRY_DELAY_S = 5.0

            for attempt in range(_MAX_WARMUP_RETRIES):
                try:
                    payload = {
                        "model": model,
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 5,
                        "temperature": 0.1,
                        "stream": False,
                    }
                    r = requests.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        timeout=(_WARMUP_CONNECT_S, _WARMUP_READ_S),
                    )
                    if r.status_code == 200:
                        _model_warmed.add(key)
                        logger.info("Model %s warmed up successfully", model)
                        return
                    elif r.status_code == 400 and "Failed to load model" in r.text:
                        # Model cannot be loaded - fail fast so fallback can trigger
                        _model_failed.add(key)
                        error_msg = f"Model '{model}' failed to load: {r.text[:500]}"
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)
                    elif r.status_code in (400, 503) and any(m in (r.text or "").lower() for m in _BUSY_MARKERS):
                        # Model busy / already loaded / server busy — wait and retry
                        if attempt < _MAX_WARMUP_RETRIES - 1:
                            logger.warning(
                                "Model %s busy (%s), waiting %.1fs before retry (%d/%d)",
                                model, r.text[:200], _WARMUP_RETRY_DELAY_S, attempt + 1, _MAX_WARMUP_RETRIES
                            )
                            time.sleep(_WARMUP_RETRY_DELAY_S)
                            continue
                        # Last attempt exhausted — treat as transient, don't cache
                        logger.warning(
                            "Model %s busy after %d retries, treating as transient",
                            model, _MAX_WARMUP_RETRIES
                        )
                    else:
                        # Transient (cold load, 5xx, ...): do NOT cache — the model
                        # may become ready by the next stage. Only the definitive
                        # 400 "Failed to load model" above is cached permanently.
                        logger.warning("Model warmup returned %s: %s", r.status_code, r.text[:200])
                    return
                except RuntimeError:
                    raise
                except Exception as e:
                    # Timeouts / connection errors while the model is (cold) loading
                    # must not poison the model for the whole run — next stage
                    # retries the warmup instead of falling back immediately.
                    logger.warning("Model warmup failed (transient, will retry): %s", e)

    def _server_root(self) -> str:
        """Server root without the /v1 suffix (for management endpoints)."""
        root = self.base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        return root.rstrip("/")

    def unload_model(self, model: str) -> bool:
        """Best-effort unload of one model to free VRAM. Never raises.

        Tries known LM Studio management endpoint variants; servers without
        unload support just log a warning (use the app's auto-evict setting
        as the reliable path there). Also clears local warmup caches.
        """
        key = (self.base_url, model)
        _model_warmed.discard(key)
        _model_failed.discard(key)
        return _unload_via_api(self.base_url, model)

    def generate(self, prompt: str, *, stage: str, context: dict | None = None) -> str:
        # Track this as a local AI attempt (parity with Ollama/llama.cpp, so
        # LOCALS runs do not report local_ai_requests_sent=0 in the manifest).
        try:
            import investment_engine.main as _main
            _main._track_local_ai_attempt(blocked=False)
        except Exception:
            pass
        requested_output_tokens = (context or {}).get("max_output_tokens", self.max_output_tokens)
        requested_model = str((context or {}).get("model", self.model))
        # Thinking models (30B) need room past the 5min default read budget.
        try:
            read_timeout = int((context or {}).get("read_timeout_s", 300) or 300)
        except (TypeError, ValueError):
            read_timeout = 300
        
        # Completion budget (max_tokens) covers thinking/reasoning tokens too,
        # so it doubles as the context reserve. Computed before warmup because
        # the load context must include it.
        preset = preset_for(stage)
        sampling = merge_sampling(preset, context)
        max_tokens = min(int(requested_output_tokens), self.max_output_tokens)
        floor = int(preset.get("min_tokens_floor", 0) or 0)
        if floor > max_tokens:
            # Reasoning trace needs budget or the answer comes back empty.
            max_tokens = min(floor, self.max_output_tokens)

        # Warm up the model on first use. A pre-flight/warmup RuntimeError
        # becomes a chain-visible error string (not an exception) so the
        # caller falls through to the next link instead of failing the stage.
        try:
            self._warmup_model(
                requested_model,
                prompt_tokens=max(1, len(prompt or "") // 4),
                output_tokens=max_tokens,
            )
        except RuntimeError as exc:
            return f"[{stage}] LM Studio model '{requested_model}' unavailable: {exc}."

        payload = {
            "model": requested_model,
            "messages": [
                {"role": "system", "content": f"You are the {stage} stage of the investment engine."},
                {"role": "user", "content": prompt},
            ],
            "temperature": sampling["temperature"],
            "top_p": sampling["top_p"],
            "top_k": sampling["top_k"],
            "repeat_penalty": sampling["repeat_penalty"],
            "max_tokens": max_tokens,
            "stream": False,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        try:
            logger.info("LM Studio request: stage=%s model=%s", stage, requested_model)
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=(30, read_timeout),  # 30s connect, stage read budget
            )
            if response.status_code == 400:
                # Model is likely (cold) loading after a switch — the server
                # answers 400 instead of queueing. Wait, re-warmup, retry once.
                logger.warning(
                    "LM Studio 400 at stage=%s (likely model loading), "
                    "waiting 30s and retrying once: %s",
                    stage, (response.text or "")[:200])
                time.sleep(30)
                try:
                    self._warmup_model(requested_model)
                except Exception:
                    pass
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    timeout=(30, read_timeout),
                )
            logger.info("LM Studio response: stage=%s status=%s", stage, response.status_code)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                return f"[{stage}] LM Studio returned no choices."
            message = choices[0].get("message", {})
            # NOTE: reasoning_content is chain-of-thought, NEVER report content.
            # Observed 2026-09-28: qwen fills the whole budget with reasoning
            # and returns content="" — dumping that into reports produced
            # thinking-process briefs. Empty content is an error so the chain
            # falls back instead of publishing the model's inner monologue.
            content = message.get("content") or ""
            content = str(content or "").strip()
            # Strip <answer> tags if present (some models wrap JSON in <answer> tags)
            if content.startswith("<answer>") and content.endswith("</answer>"):
                content = content[8:-9].strip()
            # Strip markdown code fences if present (some models wrap JSON in ```json ... ```)
            if content.startswith("```"):
                lines = content.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = '\n'.join(lines).strip()
            return content.strip() or f"[{stage}] LM Studio returned an empty response."
        except requests.exceptions.HTTPError as exc:
            logger.exception("LM Studio generation failed at stage=%s", stage)
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.exception("LM Studio generation failed at stage=%s", stage)
            raise


def _unload_via_api(base_url: str, model: str) -> bool:
    """Try known unload endpoint variants. Never raises. Returns True on success."""
    base = (base_url or "").rstrip("/")
    root = _root_url(base)
    # v1 is the supported route (LM Studio 0.4+); the rest are legacy fallbacks
    # for older servers that may still expose one of them.
    if unload_model_v1(base_url, model):
        return True
    candidates = [
        ("POST", f"{root}/api/v0/models/unload", {"model": model}),
        ("POST", f"{base}/models/unload", {"model": model}),
        ("DELETE", f"{base}/models/{model}", None),
    ]
    for method, url, payload in candidates:
        try:
            if method == "DELETE":
                r = requests.delete(url, timeout=(5, 15))
            else:
                r = requests.post(url, json=payload, timeout=(5, 15))
            body = (r.text or "")[:200]
            if r.status_code == 200 and not _unsupported_endpoint(body):
                logger.info("Unloaded model %s via %s %s", model, method, url)
                return True
            logger.debug("Unload variant %s %s unsupported: %s %s",
                         method, url, r.status_code, body)
        except Exception as e:
            logger.debug("Unload variant %s %s failed: %s", method, url, e)
    logger.warning(
        "Model %s NOT unloaded: server has no unload API. "
        "Enable auto-evict in LM Studio app settings to free VRAM.", model)
    return False


def unload_lmstudio_models(base_url: str, models: list[str]) -> dict[str, bool]:
    """Best-effort unload of several models. Never raises. Returns {model: ok}."""
    # Track unload attempts as local AI activity
    try:
        import investment_engine.main as _main
        for _ in dict.fromkeys(models):
            _main._track_local_ai_attempt(blocked=False)
    except Exception:
        pass
    out: dict[str, bool] = {}
    for model in dict.fromkeys(models):  # dedupe, keep order
        try:
            out[model] = _unload_via_api(base_url, model)
        except Exception:
            out[model] = False
    return out
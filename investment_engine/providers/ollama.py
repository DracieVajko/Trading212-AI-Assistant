from __future__ import annotations

import logging
import time

import requests

from .base import BaseLLMProvider
from .context_budget import context_target

logger = logging.getLogger(__name__)

#: base_url -> (timestamp, frozenset(names) | None). None = unreachable.
_tags_cache: dict[str, tuple[float, frozenset | None]] = {}
_TAGS_TTL_S = 120.0


def reset_tags_cache() -> None:
    """Clear the /api/tags cache (tests, model pulled/removed)."""
    _tags_cache.clear()


def ollama_model_ids(base_url: str) -> frozenset | None:
    """Model names served by Ollama, with and without the ``:latest`` suffix.

    None means "unknown" (endpoint unreachable) so callers never block on a
    transient probe failure. Never raises.
    """
    base = (base_url or "").rstrip("/")
    now = time.time()
    hit = _tags_cache.get(base)
    if hit is not None and (now - hit[0]) < _TAGS_TTL_S:
        return hit[1]
    try:
        r = requests.get(f"{base}/api/tags", timeout=(3, 8))
        if r.status_code == 200:
            ids: set[str] = set()
            for m in (r.json().get("models") or []):
                if not isinstance(m, dict):
                    continue
                for field in ("name", "model"):
                    name = str(m.get(field) or "").strip()
                    if not name:
                        continue
                    ids.add(name)
                    if name.endswith(":latest"):
                        ids.add(name[: -len(":latest")])
            out = frozenset(ids)
            _tags_cache[base] = (now, out)
            return out
        logger.debug("Ollama /api/tags returned %s on %s", r.status_code, base)
    except Exception as exc:
        logger.debug("Ollama /api/tags unreachable on %s: %s", base, exc)
    _tags_cache[base] = (now, None)
    return None


class OllamaProvider(BaseLLMProvider):
    """Ollama-compatible provider for the modular investment engine.

    Ollama loads models on demand and evicts the previous one by default, so
    there is no separate load API. Context and output budget are sent per
    request (``num_ctx`` / ``num_predict``); ``keep_alive`` controls how long
    the model stays resident.
    """

    @property
    def name(self) -> str:
        return "Ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "gemma4:12b",
        max_context_tokens: int = 128000,
        max_output_tokens: int = 4096,
        *,
        think: bool | None = None,
        keep_alive: str = "5m",
        auto_context: bool = True,
        timeout_seconds: int = 1800,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens
        # None = don't send the field (older Ollama builds reject it);
        # False = disable thinking for Qwen3/GPT-OSS style models.
        self.think = think
        self.keep_alive = str(keep_alive or "")
        self.auto_context = bool(auto_context)
        self.timeout_seconds = int(timeout_seconds or 1800)
        self._connect_timeout = 10

    def generate(self, prompt: str, *, stage: str, context: dict | None = None) -> str:
        # Track this as a local AI attempt (direct call to Ollama provider)
        try:
            import investment_engine.main as _main
            _main._track_local_ai_attempt(blocked=False)
        except Exception:
            pass

        ctx = context or {}
        try:
            requested = int(ctx.get("max_output_tokens", self.max_output_tokens) or self.max_output_tokens)
        except (TypeError, ValueError):
            requested = self.max_output_tokens
        num_predict = max(1, min(requested, self.max_output_tokens))

        known = ollama_model_ids(self.base_url)
        if known is not None and self.model not in known:
            available = ", ".join(sorted(known)) or "none"
            return (f"[{stage}] Ollama model '{self.model}' not found on "
                    f"{self.base_url} (available: {available}).")

        options: dict[str, object] = {
            "temperature": 0.15,
            "num_predict": num_predict,
        }
        if self.auto_context:
            # num_ctx covers the prompt plus the completion budget, which
            # includes thinking tokens. Cap comes from OLLAMA_CONTEXT_TOKENS.
            options["num_ctx"] = context_target(
                max(1, len(prompt or "") // 4), num_predict, self.max_context_tokens)

        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"You are the {stage} stage of the investment engine."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": options,
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        if self.think is not None:
            payload["think"] = self.think

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=(self._connect_timeout, self.timeout_seconds),
            )
            try:
                response.raise_for_status()
            except Exception as exc:
                # Include the server body: Ollama 404s on unknown MODELS
                # (e.g. model id exists elsewhere but not on this server),
                # which is otherwise indistinguishable from a dead endpoint.
                body = (response.text or "")[:200]
                return f"[{stage}] Ollama error: {exc} | model={self.model} | body={body}"
            data = response.json()
            if isinstance(data, dict):
                message = data.get("message") or {}
                content = str(message.get("content") or "").strip()
                if content:
                    return content
                # Thinking-only output must never reach the report (same rule
                # as the LM Studio provider).
                thinking = str(message.get("thinking") or "")
                if thinking:
                    return (f"[{stage}] Ollama returned thinking only "
                            f"({len(thinking)} chars); set OLLAMA_THINK=false "
                            f"or use a non-thinking model.")
                if output := data.get("output"):
                    if isinstance(output, list) and output:
                        first = output[0]
                        if isinstance(first, dict) and first.get("content"):
                            return str(first.get("content") or "").strip()
                        if isinstance(first, str):
                            return first.strip()
            return f"[{stage}] Ollama returned no content."
        except Exception as exc:  # pragma: no cover - defensive fallback
            return f"[{stage}] Ollama error: {exc}"

    def is_available(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

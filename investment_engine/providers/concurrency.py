"""Model concurrency manager for local LLM providers.

Ensures that no more than ``max_concurrent`` models are loaded at any time
across LM Studio, Ollama, and other local backends. When at capacity, the
manager waits (polling every ``poll_interval`` seconds) for up to
``acquire_timeout`` seconds before giving up and returning False.

Default: ``max_concurrent=1`` (single-model policy).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Global instance shared across all providers in a single process.
_instance: Optional["ModelConcurrencyManager"] = None
_instance_lock = threading.Lock()


def get_manager(max_concurrent: int = 1, poll_interval: int = 120, acquire_timeout: int = 3600) -> "ModelConcurrencyManager":
    """Return the process-wide concurrency manager (created once)."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ModelConcurrencyManager(
                max_concurrent=max_concurrent,
                poll_interval=poll_interval,
                acquire_timeout=acquire_timeout,
            )
        return _instance


class ModelConcurrencyManager:
    """Manages how many local LLM models are loaded at once.

    Backends provide a ``count_loaded`` callable that returns the current
    number of loaded models. The manager uses this to decide whether to
    load a new model or wait.
    """

    def __init__(self, max_concurrent: int = 1, poll_interval: int = 120, acquire_timeout: int = 3600):
        self.max_concurrent = max(1, max_concurrent)
        self.poll_interval = max(10, poll_interval)
        self.acquire_timeout = max(60, acquire_timeout)
        self._slots: dict[str, int] = {}  # backend_name -> count of our loaded models
        self._lock = threading.Lock()

    def count_loaded(self, backend_name: str, count_fn: Callable[[], int]) -> int:
        """Return total loaded models on the backend (ours + others)."""
        try:
            return max(0, int(count_fn()))
        except Exception:
            return 0

    def acquire(self, model: str, backend_name: str, count_fn: Callable[[], int], load_fn: Callable[[], bool]) -> bool:
        """Wait for capacity, then load the model. Returns True on success."""
        deadline = time.monotonic() + self.acquire_timeout
        while True:
            with self._lock:
                our_count = self._slots.get(backend_name, 0)
                total = self.count_loaded(backend_name, count_fn)
                # Available slots = max_concurrent - (total - our_count)
                # We can load if we haven't exceeded our allocation.
                if our_count < self.max_concurrent and total - our_count < self.max_concurrent:
                    # We have capacity — load now
                    self._slots[backend_name] = our_count + 1
                    break
            if time.monotonic() >= deadline:
                logger.warning(
                    "Model concurrency: timed out after %ds waiting to load %s on %s "
                    "(loaded=%d, max=%d). Falling back.",
                    self.acquire_timeout, model, backend_name, total, self.max_concurrent,
                )
                return False
            logger.info(
                "Model concurrency: %s on %s waiting (loaded=%d, max=%d). "
                "Retrying in %ds.",
                model, backend_name, total, self.max_concurrent, self.poll_interval,
            )
            time.sleep(self.poll_interval)

        # Try to load
        try:
            ok = load_fn()
            if not ok:
                with self._lock:
                    self._slots[backend_name] = max(0, self._slots.get(backend_name, 0) - 1)
                return False
            return True
        except Exception as exc:
            logger.warning("Model load failed for %s on %s: %s", model, backend_name, exc)
            with self._lock:
                self._slots[backend_name] = max(0, self._slots.get(backend_name, 0) - 1)
            return False

    def release(self, backend_name: str) -> None:
        """Release a slot (call after unloading)."""
        with self._lock:
            if self._slots.get(backend_name, 0) > 0:
                self._slots[backend_name] -= 1

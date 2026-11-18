"""Configurable watchdog for LM Studio model contention.

Automated tasks (this engine) and interactive users share one LM Studio
instance. This module decides how a run reacts when a *foreign* LLM is loaded
while the run wants the server:

* ``priority=True``  (default, matches the historical exclusive-load policy):
  evict every loaded LLM except the run's own model — the run keeps working.
* ``priority=False`` (cooperative mode): the run pauses, unloads its own
  model to free VRAM, and waits for the foreign model to disappear (the user
  finished generating). It then reloads and resumes. If nothing clears within
  ``timeout_s`` (default 1 hour) it raises so the caller falls back to the
  cloud API instead of hanging forever.

The watchdog never raises on transport errors; it only raises
``RuntimeError("watchdog timeout ...")`` on a genuine timeout so the provider
chain can fall through to the API.
"""

from __future__ import annotations

import logging
import time
from typing import Any

def _v1_models(base_url):
    from .lmstudio import v1_models as _v1
    return _v1(base_url)


def _evict(base_url, allowed, *, banned=None, timeout_s=120.0):
    from .lmstudio import evict_disallowed_models as _evict_fn
    return _evict_fn(base_url, allowed, banned=banned, timeout_s=timeout_s)

logger = logging.getLogger(__name__)


class LMStudioWatchdog:
    def __init__(
        self,
        base_url: str,
        watched_model: str,
        *,
        priority: bool = True,
        timeout_s: float = 3600.0,
        poll_s: float = 15.0,
        banned: list[str] | None = None,
        evict_timeout_s: float = 120.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.watched_model = str(watched_model or "").strip()
        self.priority = bool(priority)
        self.timeout_s = max(60.0, float(timeout_s or 3600.0))
        self.poll_s = max(2.0, float(poll_s or 15.0))
        self.banned = list(banned or [])
        self.evict_timeout_s = max(0.0, float(evict_timeout_s or 120.0))
        self._watched_norm = self.watched_model.lower()

    def foreign_loaded(self) -> list[str]:
        """LLM model keys currently loaded besides our own. Never raises."""
        try:
            entries = _v1_models(self.base_url)
        except Exception:
            return []
        if not entries:
            return []
        out: list[str] = []
        for key, entry in (entries or {}).items():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("type") or "llm") != "llm":
                continue
            if not (entry.get("loaded_instances") or []):
                continue
            if str(key).strip().lower() == self._watched_norm:
                continue
            out.append(str(key))
        return out

    def evict_foreign(self) -> dict[str, Any]:
        """Priority mode: unload everything except our model. Never raises."""
        try:
            return _evict(
                self.base_url,
                allowed={self.watched_model},
                banned=self.banned,
                timeout_s=self.evict_timeout_s,
            )
        except Exception as exc:
            logger.debug("watchdog evict failed: %s", exc)
            return {"status": "error", "evicted": [], "remaining": self.foreign_loaded()}

    def wait_for_foreign_clear(self, timeout_s: float | None = None) -> bool:
        """Non-priority mode: block until foreign models unload or timeout.

        Returns True if cleared, False on timeout. Never raises.
        """
        deadline = time.monotonic() + (timeout_s if timeout_s is not None else self.timeout_s)
        foreign = self.foreign_loaded()
        if not foreign:
            return True
        logger.info(
            "watchdog (non-priority): foreign model(s) %s loaded; pausing run and "
            "waiting up to %.0fs for them to finish",
            foreign, deadline - time.monotonic(),
        )
        while time.monotonic() < deadline:
            foreign = self.foreign_loaded()
            if not foreign:
                logger.info("watchdog: foreign model cleared; resuming run")
                return True
            remaining = max(0.0, deadline - time.monotonic())
            time.sleep(min(self.poll_s, max(1.0, remaining)))
        logger.warning(
            "watchdog: foreign model still loaded after %.0fs; giving up",
            self.timeout_s,
        )
        return False

    def acquire(self) -> str:
        """Prepare the server for our model. Returns a status string.

        * ``"ok"``          - ready (no foreign model, or evicted)
        * ``"waited"``      - non-priority: waited for a foreign model to clear
        * ``"timeout"``     - non-priority: foreign model did not clear in time
        """
        foreign = self.foreign_loaded()
        if not foreign:
            return "ok"
        if self.priority:
            result = self.evict_foreign()
            if result.get("status") == "timeout":
                logger.warning("watchdog (priority): eviction timed out: %s", result.get("remaining"))
            return "evicted"
        # non-priority: release our model so the third party has full VRAM,
        # then wait for it to finish.
        waited = self.wait_for_foreign_clear()
        return "waited" if waited else "timeout"

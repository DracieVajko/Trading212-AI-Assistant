from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProviderChain(Protocol):
    """Query surface exposed by chain-shaped providers.

    Construction (``ProviderFactory.create``) is synchronous; generation
    (``BaseLLMProvider.generate``) is synchronous too. A chain adds state that
    callers may inspect without reaching into ``fallback.py`` internals:
    number of links, whether a link is currently skipped, and remaining
    budget seconds when a chain budget is configured.
    """

    @property
    def depth(self) -> int:
        """Number of provider links in the chain."""

    def is_skipped(self, name: str, model: str | None = None) -> bool:
        """Return True when the named provider/model is on cooldown."""

    def budget_remaining_s(self) -> float | None:
        """Remaining chain-budget seconds, or None when unbounded."""


class BaseLLMProvider(ABC):
    """Abstract interface for all LLM providers.

    Contract
    --------
    - ``generate`` is synchronous. Async callers must wrap it in a worker
      thread; the provider layer does not expose a separate async API.
    - ``context`` is a free-form dict for stage-specific hints. The reserved
      key ``"model"`` is ignored and stripped by fallback/chain wrappers:
      each provider uses its own configured model so failover cannot silently
      switch models mid-stage.
    - Implementations must return a string. A failure is signalled by raising
      a provider-specific exception; chain wrappers translate exceptions and
      error-string results into the next link. Callers should treat a returned
      ``"[stage] ..."`` error string as a degraded result, not as content.
    - ``stage`` is a stable routing label (for example ``summary`` or
      ``decision``) used for model selection, attribution, and telemetry.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name used for routing and tracing."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt: str, *, stage: str, context: dict | None = None) -> str:
        """Generate a response for the supplied stage and prompt.

        See the class contract for context semantics and error handling.
        """
        raise NotImplementedError

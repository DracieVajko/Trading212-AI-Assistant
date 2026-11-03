"""Explicit provider authorization boundaries.

The execution mode is derived from settings, but these constants make the
allowed provider sets auditable instead of implicit in ``if`` branches.
"""

from __future__ import annotations

LOCAL_PROVIDERS: tuple[str, ...] = ("LM Studio", "llama.cpp", "Ollama")
CLOUD_PROVIDERS: tuple[str, ...] = ("Gemini", "OpenRouter", "Mistral", "OpenCode Zen")
API_ONLY_DISABLED: tuple[str, ...] = LOCAL_PROVIDERS
"""Providers that must never be constructed in API-only/public mode."""

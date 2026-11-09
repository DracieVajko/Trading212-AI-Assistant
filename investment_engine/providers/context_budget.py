"""Context sizing shared by local LLM providers.

The loaded/generated window must cover the prompt estimate plus the completion
budget. The completion budget (``max_tokens`` / ``num_predict``) already
includes thinking/reasoning tokens, so it doubles as the thinking reserve.

Dynamic sizing: local LLM speed rises sharply as the context window shrinks,
so each call asks for only what its prompt needs. Sizes are rounded up to a
step (default 2048) and clamped to the configured cap. The floor is 2048 by
default (override with ``LOCAL_CONTEXT_MIN_TOKENS``); the step can be changed
with ``LOCAL_CONTEXT_STEP_TOKENS``.
"""
from __future__ import annotations

import os

#: Slack before a loaded context is considered "grossly oversized" and worth
#: reloading. Avoids reload thrash when prompt sizes vary between stages.
#: A loaded window up to ``target * factor + tokens`` is reused as-is.
CONTEXT_SLACK_FACTOR = 1.5
CONTEXT_SLACK_TOKENS = 2048

#: Floor for a dynamically sized local context. Short prompts (a few hundred
#: tokens) must not force an 8k load.
DEFAULT_CONTEXT_MINIMUM = 2048
DEFAULT_CONTEXT_STEP = 2048


def _env_int(name: str, default: int) -> int:
    """Read a positive integer from the environment, falling back to default."""
    try:
        value = int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def local_context_minimum() -> int:
    return _env_int("LOCAL_CONTEXT_MIN_TOKENS", DEFAULT_CONTEXT_MINIMUM)


def local_context_step() -> int:
    return _env_int("LOCAL_CONTEXT_STEP_TOKENS", DEFAULT_CONTEXT_STEP)


def estimate_tokens(text: str) -> int:
    """Cheap chars/4 token estimate (ceil), never below 1 for non-empty text."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def context_target(
    prompt_tokens: int,
    output_tokens: int,
    cap: int,
    *,
    minimum: int | None = None,
    step: int | None = None,
    margin: float = 1.15,
    system_tokens: int = 0,
) -> int:
    """Context to allocate: prompt estimate + completion budget, rounded up.

    ``margin`` covers the error of the chars/4 prompt estimate; ``system_tokens``
    accounts for the provider's system message and chat wrapper; ``cap`` is the
    configured upper bound (e.g. LM_STUDIO_CONTEXT_TOKENS).
    """
    floor = local_context_minimum() if minimum is None else int(minimum)
    step_i = local_context_step() if step is None else int(step)
    try:
        prompt_i = max(0, int(prompt_tokens))
        system_i = max(0, int(system_tokens))
        output_i = max(0, int(output_tokens))
        required = int((prompt_i + system_i) * margin) + output_i
    except (TypeError, ValueError):
        required = floor
    target = max(int(floor), required)
    target = ((target + step_i - 1) // step_i) * step_i
    try:
        cap_i = int(cap or 0)
    except (TypeError, ValueError):
        cap_i = 0
    if cap_i > 0:
        target = min(target, cap_i)
    return int(target)


def context_is_sufficient(loaded: int, target: int) -> bool:
    """True when the loaded context covers the target without huge waste."""
    try:
        loaded_i = int(loaded)
    except (TypeError, ValueError):
        return False
    if loaded_i < int(target):
        return False
    return loaded_i <= int(int(target) * CONTEXT_SLACK_FACTOR) + CONTEXT_SLACK_TOKENS

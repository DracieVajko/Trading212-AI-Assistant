"""Context sizing shared by local LLM providers.

The loaded/generated window must cover the prompt estimate plus the completion
budget. The completion budget (``max_tokens`` / ``num_predict``) already
includes thinking/reasoning tokens, so it doubles as the thinking reserve.
"""
from __future__ import annotations

#: Slack before a loaded context is considered "grossly oversized" and worth
#: reloading. Avoids reload thrash when prompt sizes vary between stages.
CONTEXT_SLACK_FACTOR = 1.5
CONTEXT_SLACK_TOKENS = 2048


def context_target(
    prompt_tokens: int,
    output_tokens: int,
    cap: int,
    *,
    minimum: int = 8192,
    step: int = 2048,
    margin: float = 1.15,
) -> int:
    """Context to allocate: prompt estimate + completion budget, rounded up.

    ``margin`` covers the error of the chars/4 prompt estimate; ``cap`` is the
    configured upper bound (e.g. LM_STUDIO_CONTEXT_TOKENS).
    """
    try:
        required = int(max(0, int(prompt_tokens)) * margin) + int(max(0, int(output_tokens)))
    except (TypeError, ValueError):
        required = minimum
    target = max(int(minimum), required)
    target = ((target + step - 1) // step) * step
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

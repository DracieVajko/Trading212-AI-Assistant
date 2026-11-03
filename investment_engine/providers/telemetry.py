"""Provider-layer telemetry shared by main and provider implementations.

Keeping the tracker here avoids providers importing ``investment_engine.main``
at runtime, which would create a circular initialization path.
"""

from __future__ import annotations

LOCAL_AI_TRACKER: dict[str, int] = {
    "attempts": 0,
    "requests_sent": 0,
    "blocked": 0,
}


def track_local_ai_attempt(blocked: bool = False) -> None:
    """Track a local AI attempt. blocked=True if prevented before sending."""
    LOCAL_AI_TRACKER["attempts"] += 1
    if blocked:
        LOCAL_AI_TRACKER["blocked"] += 1
    else:
        LOCAL_AI_TRACKER["requests_sent"] += 1


def reset_local_ai_tracker() -> None:
    """Reset the local AI attempt tracker for a new run."""
    LOCAL_AI_TRACKER["attempts"] = 0
    LOCAL_AI_TRACKER["requests_sent"] = 0
    LOCAL_AI_TRACKER["blocked"] = 0


def local_ai_snapshot() -> dict[str, int]:
    """Return a copy of the tracker for manifest/report writing."""
    return dict(LOCAL_AI_TRACKER)

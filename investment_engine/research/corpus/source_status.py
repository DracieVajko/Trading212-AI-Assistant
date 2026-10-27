"""Per-adapter collection status ledger (Phase 3).

Every research adapter reports one status per run so the report can
distinguish: collected-with-items / empty / filtered-all / failed /
rate-limited / not-attempted / disabled / not-configured / not-implemented /
auth-required / access-restricted. An adapter failure never empties other
adapters' data; the ledger records the failure instead of hiding it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VALID_STATUSES = frozenset({
    "SUCCESS_WITH_ITEMS",
    "SUCCESS_EMPTY",
    "FILTERED_ALL",
    "PARTIAL",
    "FAILED",
    "RATE_LIMITED",
    "TIMEOUT",
    "AUTH_REQUIRED",
    "ACCESS_RESTRICTED",
    "NOT_ATTEMPTED",
    "DISABLED",
    "NOT_CONFIGURED",
    "NOT_IMPLEMENTED",
})


def new_ledger() -> list[dict[str, Any]]:
    """Empty per-run ledger."""
    return []


def record(ledger: list[dict[str, Any]], *, adapter: str, domain: str,
           status: str, raw_count: int = 0, normalized_count: int = 0,
           selected_count: int = 0, error: str = "") -> dict[str, Any]:
    """Append one adapter outcome. Unknown statuses degrade to FAILED, never raise."""
    entry = {
        "adapter": str(adapter or "unknown"),
        "domain": str(domain or "general"),
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "status": status if status in VALID_STATUSES else "FAILED",
        "raw_count": max(0, int(raw_count or 0)),
        "normalized_count": max(0, int(normalized_count or 0)),
        "selected_count": max(0, int(selected_count or 0)),
        "error": str(error or "")[:200],
    }
    try:
        ledger.append(entry)
    except Exception:
        pass
    return entry


def summarize(ledger: list[dict[str, Any]] | None) -> dict[str, int]:
    """Compact counts by status for manifest/result embedding."""
    out: dict[str, int] = {}
    for entry in (ledger or []):
        if isinstance(entry, dict):
            status = str(entry.get("status", "FAILED"))
            out[status] = out.get(status, 0) + 1
    return out

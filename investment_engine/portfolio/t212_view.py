"""Canonical accessors for the T212 snapshot dict.

The snapshot historically carried overlapping shapes: some producers put cash
under ``account_summary`` (``cash_free``/``total_equity``), others under
``cash`` (``free``/``invested``), and positions under ``all_positions``,
``positions``, or ``account_summary["all_positions"]``. Every consumer probing
its own combination makes the contract impossible to reason about.

These accessors encode the precedence once:

- ``account_summary`` -> ``cash`` / ``cash_free`` -> ``free``
- ``all_positions`` -> ``account_summary["all_positions"]`` -> ``positions``

Consumers should prefer these helpers over ad-hoc ``.get`` chains.
"""

from __future__ import annotations

from typing import Any


def account_summary(t212_data: dict[str, Any] | None) -> dict[str, Any]:
    """Return the account summary block (never None)."""
    if not isinstance(t212_data, dict):
        return {}
    return t212_data.get("account_summary") or {}


def cash(t212_data: dict[str, Any] | None) -> dict[str, Any]:
    """Return the cash block (never None)."""
    if not isinstance(t212_data, dict):
        return {}
    return t212_data.get("cash") or {}


def optional_free_cash(t212_data: dict[str, Any] | None) -> float | None:
    """Free cash in EUR, or ``None`` when neither shape carries a value."""
    value = cash(t212_data).get("free")
    if value is None:
        value = account_summary(t212_data).get("cash_free")
    if value is None:
        return None
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return None


def free_cash(t212_data: dict[str, Any] | None) -> float:
    """Free cash in EUR: ``cash.free`` first, then ``account_summary.cash_free``."""
    value = optional_free_cash(t212_data)
    return value if value is not None else 0.0


def total_equity(t212_data: dict[str, Any] | None) -> float:
    """Total account equity in EUR."""
    try:
        return float(account_summary(t212_data).get("total_equity", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def authoritative_positions(t212_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Broker positions using the documented precedence.

    ``all_positions`` at the top level wins, then the summary copy, then the
    legacy ``positions`` list. Only real dict rows are returned.
    """
    if not isinstance(t212_data, dict):
        return []
    summary = account_summary(t212_data)
    raw = (
        t212_data.get("all_positions")
        or summary.get("all_positions")
        or t212_data.get("positions")
        or []
    )
    return [item for item in raw if isinstance(item, dict)]


def reconciliation_ok(t212_data: dict[str, Any] | None) -> bool:
    """Canonical reconciliation flag (defaults to False)."""
    if not isinstance(t212_data, dict):
        return False
    return bool(t212_data.get("reconciliation_ok", False))


def status(t212_data: dict[str, Any] | None) -> str:
    """Snapshot fetch status (``ok``/``failed``/...)."""
    if not isinstance(t212_data, dict):
        return "failed"
    return str(t212_data.get("status", "") or "")

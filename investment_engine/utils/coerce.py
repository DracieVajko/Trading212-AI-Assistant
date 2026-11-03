"""Shared numeric coercion helpers with explicit failure semantics.

All numeric parsing in the engine should go through these helpers so that
None, empty strings, invalid strings, and NaN behave the same way everywhere.
"""

from __future__ import annotations

import math
from typing import Any


def coerce_float(value: Any, default: float = 0.0) -> float:
    """Return ``value`` as float, or ``default`` for None/empty/invalid/NaN."""
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(result) else result


def optional_float(value: Any) -> float | None:
    """Return ``value`` as float, or None for None/empty/invalid/NaN."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) else result


def coerce_int(value: Any, default: int = 0) -> int:
    """Return ``value`` as int, or ``default`` for None/empty/invalid/NaN."""
    parsed = optional_float(value)
    if parsed is None:
        return default
    try:
        return int(parsed)
    except (OverflowError, ValueError):
        return default

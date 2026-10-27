"""Phase 7 investment-policy loading and validation.

Template: investment_policy.example.json (committed). Real file:
investment_policy.json (gitignored, user-local). Missing file →
POLICY NOT SET (order-plan section renders the notice and nothing else).
Deferred REQUIRES_USER_VALUE entries block the dependent plan type.

``policy_profile`` selects a preset overlay (passive, long_term, medium_term,
short_term, aggressive). Missing or ``custom`` keeps the raw file values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from investment_engine.risk.profiles import (
    UnknownProfile,
    apply_profile,
    available_profiles,
    custom_profile_block,
    describe_line,
)

REQUIRES_USER_VALUE = "REQUIRES_USER_VALUE"
TEMPLATE_NAME = "investment_policy.example.json"
LOCAL_NAME = "investment_policy.json"


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    """Load, validate and apply the selected profile.

    Returns {status, policy, version, problems, profile}. ``policy`` is the
    effective policy after the profile overlay; ``profile`` documents the
    preset and every field it overrode.
    """
    target = Path(path) if path else Path(LOCAL_NAME)
    if not target.is_file():
        return {"status": "NOT SET", "policy": {}, "version": "",
                "problems": [f"{target} not found — order plans disabled"],
                "profile": custom_profile_block()}
    try:
        policy = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "INVALID", "policy": {}, "version": "",
                "problems": [f"unreadable policy file: {type(exc).__name__}"],
                "profile": custom_profile_block()}
    if not isinstance(policy, dict):
        return {"status": "INVALID", "policy": {}, "version": "",
                "problems": ["policy root must be an object"],
                "profile": custom_profile_block()}
    problems = []
    for key in ("risk_per_trade_pct", "cash", "earnings_blackout", "discovery"):
        if key not in policy:
            problems.append(f"missing required section: {key}")
    try:
        effective, profile = apply_profile(policy, policy.get("policy_profile"))
    except UnknownProfile as exc:
        problems.append(str(exc))
        effective, profile = policy, custom_profile_block()
    return {"status": "OK" if not problems else "INVALID",
            "policy": effective,
            "version": str(policy.get("policy_version", "")),
            "problems": problems,
            "profile": profile}


def is_deferred(value: Any) -> bool:
    return value == REQUIRES_USER_VALUE or (
        isinstance(value, dict) and value.get("REQUIRES_USER_VALUE") is not None)


__all__ = [
    "LOCAL_NAME",
    "REQUIRES_USER_VALUE",
    "TEMPLATE_NAME",
    "available_profiles",
    "describe_line",
    "is_deferred",
    "load_policy",
]

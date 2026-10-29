"""custom_rules.py — load and apply user-customizable investment rules.

Reads custom_rules.json (if present) and overrides:
- investment_rules → investment_policy.json fields
- strategy_aggression → portfolio_config.json settings fields
- script_behavior → EngineSettings fields
- rotation → rotation CLI/config defaults
- per_ticker_overrides → per-ticker max position / preferred action
- notifications → notification config

Precedence (highest to lowest):
  custom_rules.json > investment_policy.json > portfolio_config.json > defaults

If custom_rules.json is missing, all defaults apply (no error).
If a key is missing, the default from the lower-precedence source applies.
If a key is invalid (wrong type), it is skipped with a WARNING (never crashes).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = "custom_rules.json"


def _load_json(path: str | Path) -> dict:
    """Load JSON file; return empty dict on any error (never raises)."""
    try:
        p = Path(path)
        if not p.exists():
            return {}
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logger.warning("custom_rules: %s is not a dict; ignored", path)
            return {}
        return data
    except Exception as exc:
        logger.warning("custom_rules: could not load %s: %s", path, type(exc).__name__)
        return {}


def _safe_get(d: dict, key: str, default: Any = None) -> Any:
    """Get a value from a nested dict; return default if missing or wrong type."""
    try:
        val = d.get(key, default)
        return val if val is not None else default
    except Exception:
        return default


def load_custom_rules(path: str | Path = _DEFAULT_RULES_PATH) -> dict:
    """Load custom rules from JSON. Returns empty dict if file missing/invalid."""
    return _load_json(path)


def apply_custom_rules_to_settings(settings, rules: dict) -> None:
    """Override EngineSettings fields from custom_rules.script_behavior.

    Only overrides fields that exist in EngineSettings. Never raises.
    """
    behavior = rules.get("script_behavior", {})
    if not isinstance(behavior, dict):
        return
    for key, val in behavior.items():
        if hasattr(settings, key):
            try:
                setattr(settings, key, val)
                logger.debug("custom_rules: settings.%s = %r", key, val)
            except Exception as exc:
                logger.warning("custom_rules: could not set settings.%s: %s", key, type(exc).__name__)


def apply_custom_rules_to_policy(policy: dict, rules: dict) -> dict:
    """Merge investment_rules from custom_rules into policy dict.

    custom_rules.investment_rules overrides matching keys in policy.
    Returns the merged policy dict.
    """
    inv_rules = rules.get("investment_rules", {})
    if not isinstance(inv_rules, dict):
        return policy
    merged = dict(policy) if isinstance(policy, dict) else {}
    for key, val in inv_rules.items():
        if isinstance(val, dict):
            # Nested (e.g., sector_limits) — merge recursively
            existing = merged.get(key, {})
            if isinstance(existing, dict):
                merged[key] = {**existing, **val}
            else:
                merged[key] = val
        else:
            merged[key] = val
    return merged


def get_strategy_aggression(rules: dict) -> dict:
    """Return strategy_aggression block with defaults."""
    agg = rules.get("strategy_aggression", {})
    if not isinstance(agg, dict):
        return {}
    return agg


def get_per_ticker_overrides(rules: dict) -> dict:
    """Return per_ticker_overrides block."""
    overrides = rules.get("per_ticker_overrides", {})
    if not isinstance(overrides, dict):
        return {}
    return overrides


def get_rotation_config(rules: dict) -> dict:
    """Return rotation config block with defaults."""
    rot = rules.get("rotation", {})
    if not isinstance(rot, dict):
        return {}
    return rot


def get_notification_config(rules: dict) -> dict:
    """Return notification config block."""
    notif = rules.get("notifications", {})
    if not isinstance(notif, dict):
        return {}
    return notif


def get_custom_rules_summary(rules: dict) -> str:
    """Human-readable summary of active custom rules."""
    if not rules:
        return "No custom rules loaded (using defaults)."
    lines = ["Custom rules active:"]
    inv = rules.get("investment_rules", {})
    if isinstance(inv, dict) and inv:
        lines.append(f"  Investment: max_position={inv.get('max_position_pct', '?')}%, cash_floor={inv.get('cash_floor_pct', '?')}%, stop_loss={inv.get('stop_loss_pct', '?')}%")
    agg = rules.get("strategy_aggression", {})
    if isinstance(agg, dict) and agg:
        lines.append(f"  Aggression: buy_threshold={agg.get('buy_threshold', '?')}, sell_threshold={agg.get('sell_threshold', '?')}, news_trust={agg.get('news_trust_level', '?')}")
    rot = rules.get("rotation", {})
    if isinstance(rot, dict) and rot:
        lines.append(f"  Rotation: plan={rot.get('rotation_plan', 'none')}, trim={rot.get('rotation_trim_pct', 30)}%")
    return "\n".join(lines)

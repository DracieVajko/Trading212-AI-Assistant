"""Investment-policy profiles: user-selectable horizon/risk presets.

A profile is a named overlay on top of ``investment_policy.json``. It changes
what the engine is *allowed to propose* — eligible sleeves, sells on/off,
position cap, cash floor, per-trade risk, trim fraction — and never invents
signals. A profile can block or resize a candidate; it can never create one
without a committee decision and the full eligibility gates.

Presets: ``passive``, ``long_term``, ``medium_term``, ``short_term``,
``aggressive``. ``custom`` (the default) applies no overlay at all, so a
policy file without ``policy_profile`` behaves exactly as before.

Override precedence: the selected profile wins over the corresponding fields
in the policy file, and every override is listed in ``applied_overrides`` so
the report never hides a changed value.
"""

from __future__ import annotations

import copy
from typing import Any

CUSTOM = "custom"
_CUSTOM_ALIASES = {"", "custom", "none", "default", "off"}

#: Preset table. Keys are the accepted ``policy_profile`` values.
_PROFILE_SPECS: dict[str, dict[str, Any]] = {
    "passive": {
        "label": "Passive",
        "horizon": "10+ years",
        "description": "Buy-and-hold core exposure; exits are manual only.",
        "allowed_buy_sleeves": ["core", "long_term"],
        "allowed_sell_sleeves": [],
        "allow_sells": False,
        "overrides": {
            "risk_per_trade_pct": 1.0,
            "adverse_move_assumption": 0.30,
            "concentration": {"default_max_position_pct": 25.0},
            "cash": {"mandatory_floor_pct": 5.0,
                     "fund_buys_from_planned_trims": False},
            "trims": {"trim_fraction_pct": 0.0},
            "averaging_down": {"allowed_sleeves": ["core", "long_term"]},
            "stops": {"scope": "none"},
            "core_trims": False,
        },
    },
    "long_term": {
        "label": "Long-term",
        "horizon": "3-10 years",
        "description": "Core and long-term sleeves; trims only, never full exits.",
        "allowed_buy_sleeves": ["core", "long_term"],
        "allowed_sell_sleeves": ["core", "long_term", "thematic"],
        "allow_sells": True,
        "overrides": {
            "risk_per_trade_pct": 1.5,
            "adverse_move_assumption": 0.30,
            "concentration": {"default_max_position_pct": 20.0},
            "cash": {"mandatory_floor_pct": 5.0,
                     "fund_buys_from_planned_trims": False},
            "trims": {"trim_fraction_pct": 50.0},
            "averaging_down": {"allowed_sleeves": ["core", "long_term"]},
            "stops": {"scope": "none"},
            "core_trims": True,
        },
    },
    "medium_term": {
        "label": "Medium-term",
        "horizon": "1-3 years",
        "description": "Core, long-term and thematic sleeves; rebalancing allowed.",
        "allowed_buy_sleeves": ["core", "long_term", "thematic"],
        "allowed_sell_sleeves": ["core", "long_term", "thematic", "crypto"],
        "allow_sells": True,
        "overrides": {
            "risk_per_trade_pct": 2.0,
            "adverse_move_assumption": 0.25,
            "concentration": {"default_max_position_pct": 15.0},
            "cash": {"mandatory_floor_pct": 3.0,
                     "fund_buys_from_planned_trims": True},
            "trims": {"trim_fraction_pct": 50.0},
            "averaging_down": {"allowed_sleeves":
                               ["core", "long_term", "thematic"]},
            "stops": {"scope": "tactical-only"},
            "core_trims": True,
        },
    },
    "short_term": {
        "label": "Short-term",
        "horizon": "days-months",
        "description": "Tactical and thematic only; long-term core is never sold.",
        "allowed_buy_sleeves": ["thematic", "tactical"],
        "allowed_sell_sleeves": ["thematic", "tactical"],
        "allow_sells": True,
        "overrides": {
            "risk_per_trade_pct": 1.0,
            "adverse_move_assumption": 0.15,
            "concentration": {"default_max_position_pct": 8.0},
            "cash": {"mandatory_floor_pct": 2.0,
                     "fund_buys_from_planned_trims": True},
            "trims": {"trim_fraction_pct": 100.0},
            "averaging_down": {"allowed_sleeves": ["thematic", "tactical"]},
            "stops": {"scope": "tactical-only"},
            "core_trims": True,
        },
    },
    "aggressive": {
        "label": "Aggressive",
        "horizon": "any",
        "description": "All sleeves, full deployment, no cash floor.",
        "allowed_buy_sleeves": ["core", "long_term", "thematic", "tactical", "crypto"],
        "allowed_sell_sleeves": ["core", "long_term", "thematic", "tactical", "crypto"],
        "allow_sells": True,
        "overrides": {
            "risk_per_trade_pct": 3.0,
            "adverse_move_assumption": 0.25,
            "concentration": {"default_max_position_pct": 30.0},
            "cash": {"mandatory_floor_pct": 0.0,
                     "fund_buys_from_planned_trims": True},
            "trims": {"trim_fraction_pct": 100.0},
            "averaging_down": {"allowed_sleeves":
                               ["core", "long_term", "thematic", "tactical", "crypto"]},
            "stops": {"scope": "tactical-only"},
            "core_trims": True,
        },
    },
}


class UnknownProfile(ValueError):
    """Raised when ``policy_profile`` names a preset that does not exist."""


def available_profiles() -> tuple[str, ...]:
    """Preset names in documentation order (``custom`` excluded)."""
    return tuple(_PROFILE_SPECS)


def normalize_name(name: Any) -> str:
    """Lower-case, hyphen/space tolerant name used for lookup."""
    text = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text


def custom_profile_block() -> dict[str, Any]:
    """Neutral block: no overlay, no sleeve restriction."""
    return {
        "name": CUSTOM,
        "label": "Custom",
        "horizon": "as configured",
        "description": "Raw policy values, no preset overlay.",
        "allowed_buy_sleeves": [],
        "allowed_sell_sleeves": [],
        "allow_sells": True,
        "applied_overrides": [],
        "effective": {},
    }


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _flatten(patch: dict[str, Any], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, value in patch.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            keys.extend(_flatten(value, f"{path}."))
        else:
            keys.append(path)
    return keys


def apply_profile(policy: dict[str, Any], name: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(merged_policy, profile_block)`` for the selected preset.

    ``custom`` (or a missing name) returns an unmodified copy plus the neutral
    block. An unknown name raises :class:`UnknownProfile` so the caller can
    fail loudly instead of silently running the wrong strategy.
    """
    key = normalize_name(name)
    merged = copy.deepcopy(policy) if isinstance(policy, dict) else {}
    if key in _CUSTOM_ALIASES:
        block = custom_profile_block()
        merged["profile"] = copy.deepcopy(block)
        return merged, block
    spec = _PROFILE_SPECS.get(key)
    if spec is None:
        raise UnknownProfile(
            f"unknown policy_profile '{name}' — choose one of: "
            f"{', '.join(available_profiles())} or '{CUSTOM}'")
    _deep_merge(merged, spec["overrides"])
    effective = {
        "risk_per_trade_pct": spec["overrides"]["risk_per_trade_pct"],
        "adverse_move_assumption": spec["overrides"]["adverse_move_assumption"],
        "max_position_pct": spec["overrides"]["concentration"]["default_max_position_pct"],
        "cash_floor_pct": spec["overrides"]["cash"]["mandatory_floor_pct"],
        "trim_fraction_pct": spec["overrides"]["trims"]["trim_fraction_pct"],
        "trim_funding": spec["overrides"]["cash"]["fund_buys_from_planned_trims"],
    }
    block = {
        "name": key,
        "label": spec["label"],
        "horizon": spec["horizon"],
        "description": spec["description"],
        "allowed_buy_sleeves": list(spec["allowed_buy_sleeves"]),
        "allowed_sell_sleeves": list(spec["allowed_sell_sleeves"]),
        "allow_sells": bool(spec["allow_sells"]),
        "applied_overrides": sorted(_flatten(spec["overrides"])),
        "effective": effective,
    }
    merged["profile"] = copy.deepcopy(block)
    return merged, block


def describe_line(block: dict[str, Any] | None) -> str:
    """One deterministic English line for the brief, snapshot and JSON."""
    info = block if isinstance(block, dict) else {}
    name = normalize_name(info.get("name")) or CUSTOM
    if name == CUSTOM:
        return "Policy profile: custom — raw policy values, no preset overlay."
    label = str(info.get("label") or name)
    horizon = str(info.get("horizon") or "")
    buys = ", ".join(info.get("allowed_buy_sleeves") or []) or "none"
    if info.get("allow_sells"):
        sells = ", ".join(info.get("allowed_sell_sleeves") or []) or "none"
    else:
        sells = "manual only"
    eff = info.get("effective") or {}
    bits = [f"adds: {buys}", f"exits: {sells}"]
    if eff.get("max_position_pct") is not None:
        bits.append(f"cap {float(eff['max_position_pct']):.1f}%")
    if eff.get("cash_floor_pct") is not None:
        bits.append(f"cash floor {float(eff['cash_floor_pct']):.1f}%")
    if eff.get("risk_per_trade_pct") is not None:
        bits.append(f"risk {float(eff['risk_per_trade_pct']):.1f}%/trade")
    suffix = f" ({horizon})" if horizon else ""
    return f"Policy profile: {label}{suffix} — " + "; ".join(bits) + "."


def profile_for_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Profile block embedded in a policy dict, or the neutral custom block."""
    if isinstance(policy, dict) and isinstance(policy.get("profile"), dict):
        return policy["profile"]
    return custom_profile_block()


__all__ = [
    "CUSTOM",
    "UnknownProfile",
    "apply_profile",
    "available_profiles",
    "custom_profile_block",
    "describe_line",
    "normalize_name",
    "profile_for_policy",
]

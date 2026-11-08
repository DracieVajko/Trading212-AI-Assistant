from __future__ import annotations

import pytest

from investment_engine.day_trader.config import DayTraderConfig


def test_config_defaults_are_safe():
    cfg = DayTraderConfig()
    assert cfg.enabled is False
    assert cfg.execution.enabled is False
    assert cfg.execution.environment == "demo"


def test_config_from_mapping_overrides():
    cfg = DayTraderConfig.from_mapping({"enabled": True, "universe_limit": 50})
    assert cfg.enabled is True
    assert cfg.universe_limit == 50


def test_config_rejects_live_environment():
    with pytest.raises(ValueError):
        DayTraderConfig(execution={"environment": "live"})

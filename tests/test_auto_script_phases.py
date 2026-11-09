import pytest


def test_auto_script_config_enables_demo_not_live():
    import json
    from pathlib import Path
    from investment_engine.day_trader.config import DayTraderConfig

    path = Path("portfolio_config.json")
    if not path.is_file():
        pytest.skip("portfolio_config.json is local-only (copy the example)")

    raw = json.loads(path.read_text(encoding="utf-8"))
    dt = raw["settings"]["day_trader"]
    assert dt["auto_run"] is True
    assert dt["execution"]["environment"] == "demo"
    assert dt["execution"]["allowed_sides"] == ["BUY", "SELL"]

    cfg = DayTraderConfig.from_mapping(dt)
    assert cfg.execution.environment == "demo"
    assert cfg.auto_run is True


def test_day_trader_early_return_respects_full_report_flag():
    from pathlib import Path
    src = Path("portfolio_ai_assistant.py").read_text(encoding="utf-8")
    assert "if _did_day_trader and not args.generate_full_report:" in src

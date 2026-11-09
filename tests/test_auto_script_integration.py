def test_auto_script_demo_then_live_flow():
    import json
    import os
    from pathlib import Path
    import pytest
    from investment_engine.day_trader.config import DayTraderConfig
    from investment_engine.day_trader.broker.guard import evaluate

    path = Path("portfolio_config.json")
    if not path.is_file():
        pytest.skip("portfolio_config.json is local-only (copy the example)")

    raw = json.loads(path.read_text(encoding="utf-8"))
    dt_raw = raw["settings"]["day_trader"]
    cfg = DayTraderConfig.from_mapping(dt_raw)

    # Demo phase: allowed
    demo_env = dict(os.environ)
    demo_env["T212_DEMO_ORDER_ENABLED"] = "1"
    demo_env["T212_ORDER_ENV"] = "demo"
    demo_intent = {"symbol": "AAPL", "side": "BUY", "notional": 50, "manual_approval": True}
    demo_decision = evaluate(demo_intent, cfg, demo_env, recon_status="PASS", account_currency="EUR")
    assert demo_decision.allowed is True

    # Live phase: blocked
    live_env = dict(os.environ)
    live_env["T212_LIVE_ORDER_ENABLED"] = "0"
    live_env["T212_ORDER_ENV"] = "live"
    live_env["T212_LIVE_ACK"] = ""
    live_cfg = DayTraderConfig.from_mapping(dt_raw)
    live_cfg.execution.environment = "live"
    live_cfg.execution.auto_approve = False
    live_decision = evaluate(demo_intent, live_cfg, live_env, recon_status="PASS", account_currency="EUR")
    assert live_decision.allowed is False
    assert any("T212_LIVE_ORDER_ENABLED" in r for r in live_decision.reasons)

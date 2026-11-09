def test_guard_blocks_live_orders():
    import os
    from investment_engine.day_trader.broker.guard import evaluate
    from investment_engine.day_trader.config import DayTraderConfig, ExecutionConfig

    env = dict(os.environ)
    env["T212_LIVE_ORDER_ENABLED"] = "0"
    env["T212_ORDER_ENV"] = "live"
    env["T212_LIVE_ACK"] = ""

    cfg = DayTraderConfig()
    cfg.execution = ExecutionConfig(
        enabled=True,
        environment="live",
        auto_approve=False,
        live_ack="",
        allowed_sides=["BUY", "SELL"],
        unlimited=False,
    )
    intent = {"symbol": "AAPL", "side": "BUY", "notional": 100, "manual_approval": True}
    decision = evaluate(intent, cfg, env, recon_status="PASS", account_currency="EUR")
    assert decision.allowed is False
    assert decision.reasons


def test_guard_allows_demo_orders():
    import os
    from investment_engine.day_trader.broker.guard import evaluate
    from investment_engine.day_trader.config import DayTraderConfig, ExecutionConfig

    env = dict(os.environ)
    env["T212_DEMO_ORDER_ENABLED"] = "1"
    env["T212_ORDER_ENV"] = "demo"

    cfg = DayTraderConfig()
    cfg.execution = ExecutionConfig(
        enabled=True,
        environment="demo",
        auto_approve=True,
        live_ack="",
        allowed_sides=["BUY", "SELL"],
        unlimited=True,
    )
    intent = {"symbol": "AAPL", "side": "BUY", "notional": 100, "manual_approval": True}
    decision = evaluate(intent, cfg, env, recon_status="PASS", account_currency="EUR")
    assert decision.allowed is True
    assert decision.reasons == []

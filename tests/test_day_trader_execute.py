from __future__ import annotations


def test_execute_demo_plan_blocks_when_guard_fails():
    from investment_engine.day_trader.execute import execute_demo_plan
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True

    class FailingClient:
        environment = "demo"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place when guard fails")

    env = {"T212_DEMO_ORDER_ENABLED": "0", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FailingClient(), env=env)
    assert res["status"] == "BLOCKED"


def test_execute_demo_plan_places_when_demo_and_guard_pass(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True
    cfg.execution.unlimited = True

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            return {"id": 123, "status": "submitted"}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "PLACED"
    assert res["order"]["id"] == 123


def test_execute_demo_plan_rejects_non_demo_client():
    from investment_engine.day_trader.execute import execute_demo_plan
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True

    class LiveClient:
        environment = "live"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place on non-demo client")

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, LiveClient(), env=env)
    assert res["status"] == "BLOCKED"


def test_execute_demo_plan_sells_with_negative_quantity():
    from investment_engine.day_trader.execute import execute_demo_plan
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True
    cfg.execution.unlimited = True
    seen = {}

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            seen["qty"] = qty
            return {"id": 9}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    execute_demo_plan(cfg, {"ticker": "AAPL_US_EQ", "side": "SELL", "quantity": 2}, FakeClient(), env=env)
    assert seen["qty"] == -2


def test_execute_demo_plan_allows_sell_when_only_buys_are_allowed():
    from investment_engine.day_trader.broker.guard import evaluate
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True
    assert cfg.execution.allowed_sides == ["BUY"]

    decision = evaluate(
        {"symbol": "AAPL_US_EQ", "side": "SELL", "notional": 0, "manual_approval": True},
        cfg,
        {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"},
        recon_status="PASS",
        account_currency="EUR",
    )
    assert decision.allowed, decision.reasons

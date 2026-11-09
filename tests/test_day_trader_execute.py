from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_history_sink(monkeypatch):
    """No test may write to the permanent history/ log or SQLite store."""
    monkeypatch.setattr("investment_engine.history.record_trade", lambda *a, **k: None)


def _demo_config():
    from investment_engine.day_trader.config import DayTraderConfig
    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True
    return cfg


def test_execute_demo_plan_blocks_when_guard_fails(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()

    class FailingClient:
        environment = "demo"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place when guard fails")

    env = {"T212_DEMO_ORDER_ENABLED": "0", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FailingClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "BLOCKED"


def test_execute_demo_plan_places_when_demo_and_guard_pass(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()
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


def test_execute_demo_plan_rejects_non_demo_client(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()

    class LiveClient:
        environment = "live"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place on non-demo client")

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, LiveClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "BLOCKED"


def test_execute_demo_plan_sells_with_negative_quantity(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()
    cfg.execution.unlimited = True
    cfg.execution.allowed_sides = ["BUY", "SELL"]
    seen = {}

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            seen["qty"] = qty
            return {"id": 9}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "SELL", "quantity": 2}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert seen["qty"] == -2


def test_execute_demo_plan_records_trade_once_in_demo_mode(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()
    cfg.execution.unlimited = True
    calls = []
    monkeypatch.setattr(
        "investment_engine.history.record_trade",
        lambda *a, **k: calls.append((a, k)),
    )

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            return {"id": 77}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "PLACED"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "AAPL_US_EQ" and args[2] == 1
    assert kwargs["mode"] == "demo"
    assert kwargs["order_id"] == "77"
    assert kwargs["db_path"] == str(tmp_path / "audit.db")


def test_execute_demo_plan_fails_on_invalid_quantity(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()

    class FakeClient:
        environment = "demo"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place with an invalid quantity")

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": "1.5x"}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "FAILED"
    assert res["error"] == "invalid quantity/notional"


def test_execute_demo_plan_fails_on_invalid_notional(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()

    class FakeClient:
        environment = "demo"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place with an invalid notional")

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "notional": "n/a"}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "FAILED"
    assert res["error"] == "invalid quantity/notional"


def test_execute_demo_plan_fails_on_invalid_side(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()

    class FakeClient:
        environment = "demo"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place an invalid side")

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "HOLD", "quantity": 1}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "FAILED"
    assert res["error"] == "invalid side: HOLD"


def test_execute_demo_plan_forces_demo_history_mode(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()
    cfg.execution.unlimited = True
    calls = []
    monkeypatch.setattr(
        "investment_engine.history.record_trade",
        lambda *a, **k: calls.append((a, k)),
    )

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            return {"id": 5}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"), history_mode="paper",
    )
    # An unsupported history_mode must never reach the permanent live log.
    assert [k["mode"] for _a, k in calls] == ["demo"]

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


def _allow_unverified_recon(monkeypatch):
    monkeypatch.setenv("T212_DEMO_ALLOW_UNVERIFIED_RECON", "1")


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


def test_execute_demo_plan_places_when_demo_and_guard_pass(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
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


def test_execute_demo_plan_blocks_on_unverified_recon_by_default(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    monkeypatch.delenv("T212_DEMO_ALLOW_UNVERIFIED_RECON", raising=False)
    cfg = _demo_config()
    cfg.execution.unlimited = True

    class FakeClient:
        environment = "demo"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place without verified reconciliation")

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "BLOCKED"
    assert any("reconciliation" in r for r in res["reasons"])


def test_execute_demo_plan_allows_unverified_recon_opt_in(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
    cfg = _demo_config()
    cfg.execution.unlimited = True

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            return {"id": 124}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "PLACED"


def test_execute_demo_plan_rejects_non_demo_client(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
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


def test_execute_demo_plan_sells_with_negative_quantity(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
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
    _allow_unverified_recon(monkeypatch)
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
    # Canonical history DB only: the audit DB path must never leak into history.
    assert "db_path" not in kwargs


def test_execute_demo_plan_keeps_placed_on_history_failure(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
    cfg = _demo_config()
    cfg.execution.unlimited = True
    monkeypatch.setattr(
        "investment_engine.history.record_trade",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("history locked")),
    )

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            return {"id": 78}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "PLACED"
    assert res["history_error"] == "RuntimeError: history locked"


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


def test_execute_demo_plan_fails_on_invalid_daily_loss(tmp_path):
    from investment_engine.day_trader.execute import execute_demo_plan
    cfg = _demo_config()

    class FakeClient:
        environment = "demo"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place with an invalid daily loss")

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "daily_loss": "n/a"}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "FAILED"


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
    _allow_unverified_recon(monkeypatch)
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


def test_execute_demo_plan_places_bracket_exits(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
    cfg = _demo_config()
    cfg.execution.unlimited = True

    class BracketClient:
        environment = "demo"
        def __init__(self):
            self.calls = []
        def place_market_order(self, ticker, qty, **k):
            self.calls.append(("market", ticker, qty))
            return {"id": 301}
        def place_stop_order(self, ticker, qty, price):
            self.calls.append(("stop", ticker, qty, price))
            return {"id": 302}
        def place_limit_order(self, ticker, qty, price):
            self.calls.append(("limit", ticker, qty, price))
            return {"id": 303}

    client = BracketClient()
    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg,
        {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "stop_price": 90.0, "target_price": 110.0},
        client, env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "PLACED"
    assert client.calls == [
        ("market", "AAPL_US_EQ", 1.0),
        ("stop", "AAPL_US_EQ", -1.0, 90.0),
        ("limit", "AAPL_US_EQ", -1.0, 110.0),
    ]
    assert res["exits"]["stop"]["id"] == 302
    assert res["exits"]["target"]["id"] == 303


def test_execute_demo_plan_skips_bracket_exits_for_sell_entry(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
    cfg = _demo_config()
    cfg.execution.unlimited = True
    cfg.execution.allowed_sides = ["BUY", "SELL"]

    class BracketClient:
        environment = "demo"
        def __init__(self):
            self.calls = []
        def place_market_order(self, ticker, qty, **k):
            self.calls.append(("market", ticker, qty))
            return {"id": 401}
        def place_stop_order(self, ticker, qty, price):
            self.calls.append(("stop", ticker, qty, price))
            return {"id": 402}
        def place_limit_order(self, ticker, qty, price):
            self.calls.append(("limit", ticker, qty, price))
            return {"id": 403}

    client = BracketClient()
    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg,
        {"ticker": "AAPL_US_EQ", "side": "SELL", "quantity": 1, "stop_price": 90.0, "target_price": 110.0},
        client, env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "PLACED"
    assert client.calls == [("market", "AAPL_US_EQ", -1.0)]
    assert not res.get("exits")


def test_execute_demo_plan_blocks_duplicate(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
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
            return {"id": 101}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    ticket = {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "reason": "dup test"}
    db = str(tmp_path / "audit.db")

    first = execute_demo_plan(cfg, ticket, FakeClient(), env=env, db_path=db)
    assert first["status"] == "PLACED"

    second = execute_demo_plan(cfg, ticket, FakeClient(), env=env, db_path=db)
    assert second["status"] == "BLOCKED"
    assert "duplicate intent" in second["reasons"]
    assert len(calls) == 1


def test_execute_demo_plan_retries_same_day_after_failed_placement(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
    cfg = _demo_config()
    cfg.execution.unlimited = True
    calls = []
    monkeypatch.setattr(
        "investment_engine.history.record_trade",
        lambda *a, **k: calls.append((a, k)),
    )

    class FailingClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            raise RuntimeError("broker unavailable")

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            return {"id": 202}

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    ticket = {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "reason": "retry test"}
    db = str(tmp_path / "audit.db")

    first = execute_demo_plan(cfg, ticket, FailingClient(), env=env, db_path=db)
    assert first["status"] == "FAILED"

    second = execute_demo_plan(cfg, ticket, FakeClient(), env=env, db_path=db)
    assert second["status"] == "PLACED"
    assert second["order"]["id"] == 202
    assert len(calls) == 1


def test_execute_demo_plan_retries_same_day_after_guard_block(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
    cfg = _demo_config()
    cfg.execution.unlimited = True

    class FakeClient:
        environment = "demo"
        def place_market_order(self, ticker, qty, **k):
            return {"id": 203}

    blocker_env = {"T212_DEMO_ORDER_ENABLED": "0", "T212_ORDER_ENV": "demo"}
    good_env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    ticket = {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "reason": "guard retry test"}
    db = str(tmp_path / "audit.db")

    first = execute_demo_plan(cfg, ticket, FakeClient(), env=blocker_env, db_path=db)
    assert first["status"] == "BLOCKED"

    second = execute_demo_plan(cfg, ticket, FakeClient(), env=good_env, db_path=db)
    assert second["status"] == "PLACED"


def test_execute_demo_plan_blocks_when_audit_db_unavailable(tmp_path, monkeypatch):
    import investment_engine.day_trader.execute as execute_mod
    from investment_engine.day_trader.execute import execute_demo_plan
    _allow_unverified_recon(monkeypatch)
    cfg = _demo_config()
    cfg.execution.unlimited = True
    monkeypatch.setattr(execute_mod, "_count_placed_today", lambda *a, **k: -1)

    class FakeClient:
        environment = "demo"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place when the audit DB is unavailable")

    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(
        cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1}, FakeClient(),
        env=env, db_path=str(tmp_path / "audit.db"),
    )
    assert res["status"] == "BLOCKED"
    assert res["reasons"] == ["audit db unavailable"]


def test_count_placed_today_returns_minus_one_on_error(tmp_path):
    from investment_engine.day_trader.execute import _count_placed_today

    assert _count_placed_today(tmp_path / "missing" / "audit.db", "2026-01-01") == -1

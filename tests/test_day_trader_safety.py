"""Safety boundaries for the day-trader execution chain (offline, mocked)."""
from __future__ import annotations

import os

from investment_engine.day_trader.broker.guard import evaluate
from investment_engine.day_trader.config import ExecutionConfig, DayTraderConfig
from investment_engine.day_trader.broker.t212_orders import T212OrderClient


def test_default_config_cannot_execute():
    cfg = DayTraderConfig()
    decision = evaluate(
        {"symbol": "AAPL_US_EQ", "side": "BUY", "notional": 10.0, "manual_approval": True},
        cfg, os.environ, recon_status="PASS", account_currency="EUR",
    )
    assert decision.allowed is False
    assert any("execution disabled" in r for r in decision.reasons)


def test_demo_client_targets_demo_host():
    c = T212OrderClient("demo", "key", "secret")
    assert c.base_url == "https://demo.trading212.com"
    assert "demo.trading212.com" in c.api_base


def test_live_client_targets_live_host():
    c = T212OrderClient("live", "key", "secret")
    assert c.base_url == "https://live.trading212.com"


def test_live_order_blocked_by_default_env(monkeypatch):
    monkeypatch.delenv("T212_LIVE_ORDER_ENABLED", raising=False)
    monkeypatch.delenv("T212_LIVE_ACK", raising=False)
    c = T212OrderClient("live", "key", "secret")
    class _FakeSession:
        def post(self, *a, **k):
            raise AssertionError("no network call may occur for blocked live order")
        def get(self, *a, **k):
            raise AssertionError("no network call may occur for blocked live order")
        def delete(self, *a, **k):
            raise AssertionError("no network call may occur for blocked live order")
    c.session = _FakeSession()
    res = c.place_market_order("AAPL_US_EQ", 1)
    assert res.get("status") == "blocked"


def test_execute_demo_plan_rejects_non_demo_client():
    from investment_engine.day_trader.execute import execute_demo_plan
    class _LiveClient:
        environment = "live"
        def place_market_order(self, *a, **k):
            raise AssertionError("must not place order on non-demo client")
    cfg = DayTraderConfig()
    cfg.execution.enabled = True
    cfg.execution.environment = "demo"
    cfg.execution.auto_approve = True
    env = {"T212_DEMO_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}
    res = execute_demo_plan(cfg, {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "recon_status": "PASS"}, _LiveClient(), env=env)
    assert res["status"] == "BLOCKED"
    assert "client is not demo" in (res.get("reasons") or [])


def test_mirror_dry_run_places_no_orders():
    from investment_engine.day_trader.mirror import mirror_to_demo
    class _C:
        def get_positions(self):
            return [{"instrument": {"ticker": "AAPL_US_EQ"}, "quantity": 1.0}]
    live = _C(); demo = _C()
    demo.environment = "demo"
    live.environment = "live"
    cfg = DayTraderConfig()
    out = mirror_to_demo(live, demo, cfg, execute=False)
    assert out["mode"] == "dry-run"
    assert out["executed"] == []


def test_mirror_blocks_when_demo_client_is_actually_live():
    from investment_engine.day_trader.mirror import mirror_to_demo
    class _C:
        environment = "live"
        def get_positions(self):
            return []
    out = mirror_to_demo(_C(), _C(), DayTraderConfig(), execute=True)
    assert out["mode"] == "blocked"


def test_env_mismatch_blocks_demo(monkeypatch):
    monkeypatch.setenv("T212_DEMO_ORDER_ENABLED", "1")
    monkeypatch.setenv("T212_ORDER_ENV", "live")  # mismatched
    cfg = DayTraderConfig()
    cfg.execution.enabled = True
    cfg.execution.environment = "demo"
    cfg.execution.auto_approve = True
    decision = evaluate(
        {"symbol": "AAPL_US_EQ", "side": "BUY", "notional": 10.0, "manual_approval": True},
        cfg, os.environ, recon_status="PASS", account_currency="EUR",
    )
    assert decision.allowed is False
    assert any("environment mismatch" in r for r in decision.reasons)

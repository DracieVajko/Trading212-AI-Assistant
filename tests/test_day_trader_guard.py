from __future__ import annotations

from types import SimpleNamespace

from investment_engine.day_trader.broker.guard import GuardDecision, evaluate


def _cfg():
    return SimpleNamespace(
        execution=SimpleNamespace(
            enabled=True,
            broker="trading212",
            environment="demo",
            auto_approve=True,
            max_order_eur=50.0,
            max_daily_orders=2,
            allowed_sides=["BUY"],
            live_ack="",
        ),
        budget=SimpleNamespace(max_daily_loss=30.0),
    )


def test_guard_blocks_when_disabled():
    cfg = _cfg()
    cfg.execution.enabled = False
    d = evaluate({"symbol": "AAPL", "side": "BUY", "notional": 10.0}, cfg, {"T212_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}, "PASS", "EUR", daily_orders=0, daily_loss=0.0, allowed_symbols={"AAPL"})
    assert not d.allowed
    assert "execution disabled in config" in d.reasons


def test_guard_allows_demo_auto():
    cfg = _cfg()
    d = evaluate({"symbol": "AAPL", "side": "BUY", "notional": 10.0, "manual_approval": False}, cfg, {"T212_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}, "PASS", "EUR", daily_orders=0, daily_loss=0.0, allowed_symbols={"AAPL"})
    assert d.allowed, d.reasons


def test_guard_blocks_live_without_ack():
    cfg = _cfg()
    cfg.execution.environment = "live"
    cfg.execution.live_ack = "I_UNDERSTAND_LIVE_TRADING"
    d = evaluate({"symbol": "AAPL", "side": "BUY", "notional": 10.0}, cfg, {"T212_ORDER_ENABLED": "1", "T212_ORDER_ENV": "live", "T212_LIVE_ACK": ""}, "PASS", "EUR", daily_orders=0, daily_loss=0.0, allowed_symbols={"AAPL"})
    assert not d.allowed


def test_guard_blocks_kill_switch(tmp_path):
    ks = tmp_path / "KILL_SWITCH"
    ks.write_text("stop")
    cfg = _cfg()
    d = evaluate({"symbol": "AAPL", "side": "BUY", "notional": 10.0}, cfg, {"T212_ORDER_ENABLED": "1", "T212_ORDER_ENV": "demo"}, "PASS", "EUR", kill_switch_path=ks, daily_orders=0, daily_loss=0.0, allowed_symbols={"AAPL"})
    assert not d.allowed
    assert "kill switch present" in d.reasons

from __future__ import annotations


def test_live_client_refuses_orders_without_flag(monkeypatch):
    from investment_engine.day_trader.broker.t212_orders import T212OrderClient
    monkeypatch.setenv("T212_LIVE_ORDER_ENABLED", "0")
    monkeypatch.setenv("T212_LIVE_ACK", "")
    client = T212OrderClient("live", "key", "secret")
    res = client.place_market_order("AAPL_US_EQ", 0.1)
    assert res["status"] == "blocked"


def test_live_client_refuses_orders_without_ack(monkeypatch):
    from investment_engine.day_trader.broker.t212_orders import T212OrderClient
    monkeypatch.setenv("T212_LIVE_ORDER_ENABLED", "1")
    monkeypatch.setenv("T212_LIVE_ACK", "wrong")
    client = T212OrderClient("live", "key", "secret")
    res = client.place_market_order("AAPL_US_EQ", 0.1)
    assert res["status"] == "blocked"


def test_live_client_refuses_when_ack_matches_but_flag_off(monkeypatch):
    from investment_engine.day_trader.broker.t212_orders import T212OrderClient
    monkeypatch.setenv("T212_LIVE_ORDER_ENABLED", "0")
    monkeypatch.setenv("T212_LIVE_ACK", "I_UNDERSTAND_LIVE_TRADING")
    client = T212OrderClient("live", "key", "secret")
    assert client.place_market_order("AAPL_US_EQ", 0.1)["status"] == "blocked"


def test_demo_client_is_not_blocked(monkeypatch):
    from investment_engine.day_trader.broker.t212_orders import T212OrderClient
    monkeypatch.setenv("T212_LIVE_ORDER_ENABLED", "0")
    client = T212OrderClient("demo", "key", "secret")
    assert client.environment == "demo"

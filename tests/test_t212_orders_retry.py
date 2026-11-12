"""Bounded retry behaviour of T212OrderClient._request (mocked, no network)."""
from __future__ import annotations

from unittest.mock import MagicMock

from investment_engine.day_trader.broker.t212_orders import T212OrderClient


def _client():
    c = T212OrderClient("demo", "key", "secret")
    return c


def _resp(status, body=None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.content = bool(body)
    r.json.return_value = body if body is not None else {}
    r.text = str(body) if body is not None else ""
    r.headers = headers or {}
    return r


def test_success_on_first_attempt():
    c = _client()
    c.session.get = MagicMock(return_value=_resp(200, {"ok": True}))
    out = c.get_positions()
    assert out == {"ok": True}
    assert c.session.get.call_count == 1


def test_single_429_then_success(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = _client()
    c.session.get = MagicMock(side_effect=[_resp(429, headers={"Retry-After": "1"}), _resp(200, {"ok": True})])
    out = c.get_positions()
    assert out == {"ok": True}
    assert c.session.get.call_count == 2


def test_repeated_429_exhausts(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = _client()
    c.session.get = MagicMock(return_value=_resp(429, headers={"Retry-After": "1"}))
    out = c.get_positions()
    assert out.get("status") == "rate_limited"
    assert c.session.get.call_count == 5


def test_server_error_retries_then_fails(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = _client()
    c.session.get = MagicMock(return_value=_resp(500))
    out = c.get_positions()
    assert out.get("status") == "server_error"
    assert c.session.get.call_count == 5


def test_timeout_retries_then_fails(monkeypatch):
    import requests
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = _client()
    c.session.get = MagicMock(side_effect=requests.Timeout("boom"))
    out = c.get_positions()
    assert out.get("status") == "network_error"
    assert c.session.get.call_count == 5


def test_no_retry_on_401():
    c = _client()
    c.session.get = MagicMock(return_value=_resp(401))
    out = c.get_positions()
    assert out.get("status") == "auth_failed"
    assert c.session.get.call_count == 1


def test_live_order_blocked_no_network(monkeypatch):
    monkeypatch.delenv("T212_LIVE_ORDER_ENABLED", raising=False)
    monkeypatch.delenv("T212_LIVE_ACK", raising=False)
    c = T212OrderClient("live", "key", "secret")
    c.session.post = MagicMock(side_effect=AssertionError("no network"))
    res = c.place_market_order("AAPL_US_EQ", 1)
    assert res.get("status") == "blocked"


def test_invalid_order_id_is_rejected_without_network():
    c = _client()
    c.session.get = MagicMock(side_effect=AssertionError("no network"))
    c.session.delete = MagicMock(side_effect=AssertionError("no network"))
    assert c.get_order("1/../../x").get("status") == "forbidden"
    assert c.cancel_order("abc").get("status") == "forbidden"

from __future__ import annotations

from unittest.mock import MagicMock

from investment_engine.day_trader.broker.t212_orders import T212OrderClient


def _fake_session(status=200, body=None):
    sess = MagicMock()
    resp = MagicMock()
    resp.status_code = status
    resp.content = True
    resp.json.return_value = body if body is not None else {}
    resp.text = ""
    resp.headers = {}
    sess.get.return_value = resp
    sess.post.return_value = resp
    sess.delete.return_value = resp
    return sess, resp


def test_client_auth_header():
    client = T212OrderClient("demo", "key", "secret")
    assert client._auth.startswith("Basic ")
    assert client.base_url == "https://demo.trading212.com"


def test_disallowed_path_blocked():
    client = T212OrderClient("demo", "key", "secret")
    sess, _ = _fake_session()
    client.session = sess
    res = client._request("GET", "/not/allowed")
    assert res.get("status") == "forbidden"


def test_place_market_order_payload():
    client = T212OrderClient("demo", "key", "secret")
    sess, resp = _fake_session(200, {"id": 42, "status": "NEW"})
    client.session = sess
    res = client.place_market_order("AAPL_US_EQ", 3.0)
    assert res.get("id") == 42
    call = sess.post.call_args
    assert call.args[0].endswith("/api/v0/equity/orders/market")
    assert call.kwargs["json"]["quantity"] == 3.0
    assert call.kwargs["json"]["ticker"] == "AAPL_US_EQ"


def test_sell_quantity_negative():
    client = T212OrderClient("demo", "key", "secret")
    sess, resp = _fake_session(200, {"id": 7, "status": "NEW"})
    client.session = sess
    client.place_market_order("AAPL_US_EQ", -2.0)
    assert sess.post.call_args.kwargs["json"]["quantity"] == -2.0


def test_401_auth_failed():
    client = T212OrderClient("demo", "key", "secret")
    sess, _ = _fake_session(401, {})
    client.session = sess
    res = client.get_account_summary()
    assert res.get("status") == "auth_failed"

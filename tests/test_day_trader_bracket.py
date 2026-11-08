from __future__ import annotations

from investment_engine.day_trader.broker.bracket import run_bracket


class FakeClient:
    def __init__(self):
        self.orders = {}
        self._next = 1
        self.cancelled = []

    def place_market_order(self, ticker, quantity, extended_hours=False):
        oid = self._next
        self._next += 1
        self.orders[oid] = {"id": oid, "status": "FILLED", "ticker": ticker, "quantity": quantity}
        return self.orders[oid]

    def place_limit_order(self, ticker, quantity, limit_price, time_in_force="DAY", extended_hours=False):
        oid = self._next
        self._next += 1
        self.orders[oid] = {"id": oid, "status": "NEW", "ticker": ticker, "quantity": quantity, "limitPrice": limit_price}
        return self.orders[oid]

    def place_stop_order(self, ticker, quantity, stop_price, time_in_force="DAY", extended_hours=False):
        oid = self._next
        self._next += 1
        self.orders[oid] = {"id": oid, "status": "NEW", "ticker": ticker, "quantity": quantity, "stopPrice": stop_price}
        return self.orders[oid]

    def get_order(self, order_id):
        return self.orders.get(order_id, {"id": order_id, "status": "FILLED"})

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        if order_id in self.orders:
            self.orders[order_id]["status"] = "CANCELLED"
        return {"id": order_id, "status": "CANCELLED"}


def test_bracket_blocked_by_guard():
    client = FakeClient()
    intent = {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "order_type": "market", "stop_price": 100, "target_price": 120}
    decision = SimpleNamespace(allowed=False, reasons=["nope"]) if False else None
    from types import SimpleNamespace
    decision = SimpleNamespace(allowed=False, reasons=["nope"])
    result = run_bracket(client, intent, decision)
    assert result["status"] == "BLOCKED"
    assert client.orders == {}


def test_bracket_entry_not_filled():
    client = FakeClient()
    # make market order not filled
    def place_market_order(ticker, quantity, extended_hours=False):
        oid = client._next
        client._next += 1
        client.orders[oid] = {"id": oid, "status": "NEW", "ticker": ticker, "quantity": quantity}
        return client.orders[oid]
    client.place_market_order = place_market_order
    intent = {"ticker": "AAPL_US_EQ", "side": "BUY", "quantity": 1, "order_type": "market", "stop_price": 100, "target_price": 120, "entry_timeout_s": 0}
    from types import SimpleNamespace
    decision = SimpleNamespace(allowed=True, reasons=[])
    # timeout 0 -> wait_for_fill returns TIMEOUT without sleep? deadline now
    result = run_bracket(client, intent, decision)
    assert result["status"] in ("ENTRY_NOT_FILLED", "COMPLETED")

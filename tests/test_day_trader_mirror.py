from __future__ import annotations

from types import SimpleNamespace

from investment_engine.day_trader.mirror import compute_mirror_plan, mirror_to_demo


class FakeClient:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self):
        return self._positions

    def place_market_order(self, ticker, quantity, extended_hours=False):
        return {"id": 1, "status": "NEW", "ticker": ticker, "quantity": quantity}


def test_mirror_plan_computes_diff():
    live = FakeClient([{"instrument": {"ticker": "AAPL_US_EQ"}, "quantity": 5.0}])
    demo = FakeClient([{"instrument": {"ticker": "AAPL_US_EQ"}, "quantity": 2.0},
                      {"instrument": {"ticker": "MSFT_US_EQ"}, "quantity": 1.0}])
    plan = compute_mirror_plan(live, demo)
    assert len(plan) == 2
    aapl = next(a for a in plan if a["ticker"] == "AAPL_US_EQ")
    assert aapl["side"] == "BUY" and aapl["quantity"] == 3.0
    msft = next(a for a in plan if a["ticker"] == "MSFT_US_EQ")
    assert msft["side"] == "SELL" and msft["quantity"] == 1.0


def test_mirror_dry_run_does_not_place():
    live = FakeClient([{"instrument": {"ticker": "AAPL_US_EQ"}, "quantity": 5.0}])
    demo = FakeClient([])
    cfg = SimpleNamespace(execution=SimpleNamespace(enabled=True, auto_approve=True, environment="demo", max_order_eur=50.0, max_daily_orders=2, allowed_sides=["BUY"], live_ack=""), budget=SimpleNamespace(max_daily_loss=30.0))
    res = mirror_to_demo(live, demo, cfg, execute=False)
    assert res["mode"] == "dry-run"
    assert res["executed"] == []
    assert len(res["actions"]) == 1


def test_mirror_executes_when_enabled(tmp_path):
    live = FakeClient([{"instrument": {"ticker": "AAPL_US_EQ"}, "quantity": 5.0}])
    demo = FakeClient([])
    cfg = SimpleNamespace(execution=SimpleNamespace(enabled=True, auto_approve=True, environment="demo", max_order_eur=50.0, max_daily_orders=2, allowed_sides=["BUY"], live_ack=""), budget=SimpleNamespace(max_daily_loss=30.0))
    db = tmp_path / "audit.db"
    res = mirror_to_demo(live, demo, cfg, execute=True, db_path=str(db))
    assert res["mode"] == "executed"
    assert len(res["executed"]) == 1
    assert res["executed"][0]["order"]["status"] == "NEW"

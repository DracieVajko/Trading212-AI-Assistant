from pathlib import Path


def _demo_config(*, unlimited: bool = False, max_daily_orders: int = 2):
    from investment_engine.day_trader.config import DayTraderConfig

    cfg = DayTraderConfig()
    cfg.execution.environment = "demo"
    cfg.execution.enabled = True
    cfg.execution.auto_approve = True
    cfg.execution.unlimited = unlimited
    cfg.execution.max_daily_orders = max_daily_orders
    return cfg


class _FakeClient:
    environment = "demo"

    def __init__(self):
        self.calls = []

    def place_market_order(self, ticker, qty, **k):
        self.calls.append((ticker, qty))
        return {"id": 100 + len(self.calls)}


def _guard_env(monkeypatch):
    monkeypatch.setenv("T212_DEMO_ORDER_ENABLED", "1")
    monkeypatch.setenv("T212_ORDER_ENV", "demo")


def test_normalize_ticket_list_and_tool_input():
    from investment_engine.day_trader.execute import normalize_ticket

    norm = normalize_ticket(
        "AAPL", [{"tool_input": {"symbol": "AAPL", "side": "buy", "qty": "1"}}]
    )
    assert norm is not None
    assert norm["ticker"] == "AAPL_US_EQ"
    assert norm["side"] == "BUY"
    assert norm["quantity"] == 1.0


def test_normalize_ticket_prefers_known_instrument():
    from investment_engine.day_trader.execute import normalize_ticket

    norm = normalize_ticket(
        "AAOI",
        {"symbol": "AAOI", "side": "buy", "qty": "2"},
        {"AAOI": "AAOI_US_EQ"},
    )
    assert norm is not None
    assert norm["ticker"] == "AAOI_US_EQ"
    assert norm["quantity"] == 2.0


def test_normalize_ticket_rejects_eu_suffix_without_mapping():
    from investment_engine.day_trader.execute import normalize_ticket

    assert normalize_ticket("EXI2.DE", {"symbol": "EXI2.DE", "side": "buy", "qty": "1"}) is None


def test_normalize_ticket_invalid_qty():
    from investment_engine.day_trader.execute import normalize_ticket

    assert normalize_ticket("AAPL", {"symbol": "AAPL", "side": "buy", "qty": "nope"}) is None


def test_demo_execution_allowed_gate():
    from investment_engine.day_trader.execute import demo_execution_allowed

    assert demo_execution_allowed(True, "demo") is True
    assert demo_execution_allowed(True, "live") is False
    assert demo_execution_allowed(False, "demo") is False


def test_execute_demo_tickets_normalizes_and_places(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_tickets

    _guard_env(monkeypatch)
    monkeypatch.setattr("investment_engine.history.record_trade", lambda *a, **k: None)
    client = _FakeClient()
    payload = {"tickets": {"AAPL": [{"tool_input": {"symbol": "AAPL", "side": "buy", "qty": "1"}}]}}

    results = execute_demo_tickets(
        _demo_config(), payload, client, db_path=str(tmp_path / "audit.db")
    )

    assert len(results) == 1
    assert results[0]["symbol"] == "AAPL"
    assert results[0]["result"]["status"] == "PLACED"
    assert client.calls == [("AAPL_US_EQ", 1.0)]


def test_execute_demo_tickets_skips_unmapped_dotted_symbol(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_tickets

    _guard_env(monkeypatch)
    monkeypatch.setattr("investment_engine.history.record_trade", lambda *a, **k: None)
    client = _FakeClient()
    payload = {"tickets": {"EXI2.DE": [{"tool_input": {"symbol": "EXI2.DE", "side": "buy", "qty": "1"}}]}}

    results = execute_demo_tickets(
        _demo_config(), payload, client, db_path=str(tmp_path / "audit.db")
    )

    assert results == []
    assert client.calls == []


def test_daily_order_limit_from_audit_db(tmp_path, monkeypatch):
    from investment_engine.day_trader.execute import execute_demo_tickets

    _guard_env(monkeypatch)
    monkeypatch.setattr("investment_engine.history.record_trade", lambda *a, **k: None)
    client = _FakeClient()
    payload = {
        "tickets": {
            "AAPL": [{"tool_input": {"symbol": "AAPL", "side": "buy", "qty": "1"}}],
            "MSFT": [{"tool_input": {"symbol": "MSFT", "side": "buy", "qty": "2"}}],
        }
    }

    results = execute_demo_tickets(
        _demo_config(max_daily_orders=1), payload, client,
        db_path=str(tmp_path / "audit.db"),
    )

    assert [r["result"]["status"] for r in results] == ["PLACED", "BLOCKED"]
    assert "daily order limit reached" in results[1]["result"]["reasons"]
    assert len(client.calls) == 1


def test_wiring_source_uses_helpers():
    src = Path("portfolio_ai_assistant.py").read_text(encoding="utf-8")
    assert "demo_execution_allowed(" in src
    assert "execute_demo_tickets(" in src

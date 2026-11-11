"""Live and demo branches: isolated portfolios, isolated AI, shared data."""

from __future__ import annotations

import pytest

from investment_engine import branches
from investment_engine.config.settings import EngineSettings


class _FakeDemoClient:
    environment = "demo"

    def __init__(self, positions, summary):
        self._positions = positions
        self._summary = summary

    def get_positions(self):
        return self._positions

    def get_account_summary(self):
        return self._summary


def _demo_payloads():
    positions = {
        "items": [
            {
                "instrument": {"ticker": "NVDA_US_EQ", "currency": "USD"},
                "quantity": 3.45293247,
                "averagePricePaid": 175.10,
                "currentPrice": 181.40,
                "walletImpact": {
                    "currentValue": 570.25,
                    "totalCost": 550.35,
                    "unrealizedProfitLoss": 19.90,
                    "currency": "EUR",
                },
            },
            {
                "instrument": {"ticker": "AAPL_US_EQ", "currency": "USD"},
                "quantity": 0.64,
                "averagePricePaid": 338.88,
                "currentPrice": 355.12,
                "walletImpact": {
                    "currentValue": 204.99,
                    "totalCost": 194.88,
                    "unrealizedProfitLoss": 10.11,
                    "currency": "EUR",
                },
            },
        ]
    }
    summary = {
        "id": 52364002,
        "currency": "EUR",
        "totalValue": 5110.0,
        "cash": {"availableToTrade": 2966.1},
        "investments": {"currentValue": 2143.9},
    }
    return positions, summary


def test_demo_snapshot_matches_the_pipeline_contract(monkeypatch):
    positions, summary = _demo_payloads()
    monkeypatch.setattr(
        branches, "_demo_client", lambda: _FakeDemoClient(positions, summary)
    )

    snapshot = branches.demo_snapshot()

    assert snapshot["status"] == "ok"
    assert snapshot["reconciliation_ok"] is True
    assert snapshot["source"] == "t212_demo"
    assert snapshot["account_summary"]["total_equity"] == 5110.0
    assert snapshot["cash"]["free"] == 2966.1

    rows = snapshot["all_positions"]
    assert [row["symbol"] for row in rows] == ["NVDA", "AAPL"]
    nvda = rows[0]
    assert nvda["broker_symbol"] == "NVDA_US_EQ"
    assert nvda["quantity"] == pytest.approx(3.45293247)
    assert nvda["value_eur"] == pytest.approx(570.25)
    assert nvda["pnl_eur"] == pytest.approx(19.90)
    assert nvda["quote_currency"] == "USD"
    # Every key the recommendations prompt reads must exist.
    for key in ("symbol", "quantity", "value_eur", "pnl_pct", "average_price_eur",
                "current_price_eur", "quote_currency", "price_unit"):
        assert key in nvda


def test_demo_snapshot_skips_zero_quantity_rows(monkeypatch):
    positions, summary = _demo_payloads()
    positions["items"].append({
        "instrument": {"ticker": "OLD_US_EQ", "currency": "USD"},
        "quantity": 0,
        "walletImpact": {"currentValue": 0},
    })
    monkeypatch.setattr(
        branches, "_demo_client", lambda: _FakeDemoClient(positions, summary)
    )

    snapshot = branches.demo_snapshot()

    assert all(row["symbol"] != "OLD" for row in snapshot["all_positions"])


def test_demo_snapshot_raises_on_broker_error(monkeypatch):
    monkeypatch.setattr(
        branches,
        "_demo_client",
        lambda: _FakeDemoClient({"items": []}, {"status": "error", "error": "HTTP 500"}),
    )

    with pytest.raises(RuntimeError):
        branches.demo_snapshot()


def test_run_branch_demo_injects_its_own_snapshot(monkeypatch):
    captured = {}

    def fake_run_engine(assets, portfolio_context=None, settings=None):
        captured["context"] = portfolio_context or {}
        captured["override"] = settings.t212_snapshot_override
        return {"status": "OK"}

    monkeypatch.setattr(
        "investment_engine.main.run_engine", fake_run_engine, raising=True
    )
    monkeypatch.setattr(branches, "demo_snapshot", lambda: {"status": "ok", "source": "t212_demo"})

    result = branches.run_branch("demo", [], EngineSettings(), run_id="abc")

    assert result["status"] == "OK"
    assert captured["context"]["mode"] == "demo"
    assert captured["override"]["source"] == "t212_demo"


def test_run_branch_live_never_keeps_a_stale_override(monkeypatch):
    captured = {}

    def fake_run_engine(assets, portfolio_context=None, settings=None):
        captured["context"] = portfolio_context or {}
        captured["override"] = settings.t212_snapshot_override
        return {"status": "OK"}

    monkeypatch.setattr(
        "investment_engine.main.run_engine", fake_run_engine, raising=True
    )
    dirty = EngineSettings(t212_snapshot_override={"status": "ok", "source": "t212_demo"})

    branches.run_branch("live", [], dirty)

    assert captured["context"]["mode"] == "live"
    assert captured["override"] is None


def test_run_branch_rejects_unknown_environment():
    with pytest.raises(ValueError):
        branches.run_branch("production", [], EngineSettings())


def test_report_folders_are_separate():
    assert branches.report_subdir("live") != branches.report_subdir("demo")
    assert branches.report_subdir("demo") == "current/demo"

"""Trading 212 CSV statement reconciliation tests (offline, synthetic data)."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from investment_engine.accounting.t212_statement import (
    find_latest_t212_statement,
    parse_t212_statement,
    reconcile_t212_statement,
    render_reconciliation_markdown,
)

FIELDS = [
    "Action", "Time (UTC)", "Total", "Currency (Total)", "Result",
    "Withholding tax", "Currency (Withholding tax)", "Charge amount",
    "Deposit fee", "Currency (Deposit fee)", "Stamp duty reserve tax",
    "Currency (Stamp duty reserve tax)", "Currency conversion fee",
    "Currency (Currency conversion fee)", "French transaction tax",
    "Currency (French transaction tax)",
]


def _write_statement(path: Path, extra: dict | None = None) -> Path:
    rows = [
        {"Action": "Deposit", "Time (UTC)": "2026-01-01T10:00:00+00:00", "Total": "200.00",
         "Currency (Total)": "EUR", "Charge amount": "201.09", "Deposit fee": "-1.09",
         "Currency (Deposit fee)": "EUR"},
        {"Action": "Deposit", "Time (UTC)": "2026-01-02T10:00:00+00:00", "Total": "20.00",
         "Currency (Total)": "EUR", "Charge amount": "20.14", "Deposit fee": "-0.14",
         "Currency (Deposit fee)": "EUR"},
        {"Action": "Card debit", "Time (UTC)": "2026-01-03T10:00:00+00:00", "Total": "-50.00",
         "Currency (Total)": "EUR"},
        {"Action": "Card credit", "Time (UTC)": "2026-01-04T10:00:00+00:00", "Total": "2.00",
         "Currency (Total)": "EUR"},
        {"Action": "Spending cashback", "Time (UTC)": "2026-01-05T10:00:00+00:00", "Total": "1.00",
         "Currency (Total)": "EUR"},
        {"Action": "Spending cashback", "Time (UTC)": "2026-01-06T10:00:00+00:00", "Total": "-0.10",
         "Currency (Total)": "EUR"},
        {"Action": "Dividend (Dividend)", "Time (UTC)": "2026-01-07T10:00:00+00:00", "Total": "5.00",
         "Currency (Total)": "EUR", "Withholding tax": "0.50", "Currency (Withholding tax)": "USD"},
        {"Action": "Lending interest", "Time (UTC)": "2026-01-08T10:00:00+00:00", "Total": "0.50",
         "Currency (Total)": "EUR"},
        {"Action": "Market sell", "Time (UTC)": "2026-01-09T10:00:00+00:00", "Total": "100.00",
         "Currency (Total)": "EUR", "Result": "10.00", "Stamp duty reserve tax": "0.50",
         "Currency (Stamp duty reserve tax)": "EUR", "Currency conversion fee": "1.00",
         "Currency (Currency conversion fee)": "EUR", "French transaction tax": "0.25",
         "Currency (French transaction tax)": "EUR"},
        {"Action": "Stock split close", "Time (UTC)": "2026-01-10T10:00:00+00:00", "Total": "0.00",
         "Currency (Total)": "EUR"},
    ]
    if extra:
        rows.append(extra)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})
    return path


def test_parse_statement_totals(tmp_path):
    path = _write_statement(tmp_path / "from_2026-01-01_to_2026-01-31.csv")
    statement = parse_t212_statement(path)

    assert statement.deposits_eur == Decimal("220")
    assert statement.deposit_fees_eur == Decimal("1.23")
    assert statement.card_debits_eur == Decimal("50")
    assert statement.card_credits_eur == Decimal("2")
    assert statement.cashback_positive_eur == Decimal("1")
    assert statement.cashback_negative_eur == Decimal("0.10")
    assert statement.dividends_eur == Decimal("5")
    assert statement.interest_eur == Decimal("0.50")
    assert statement.realized_pnl_eur == Decimal("10")
    assert statement.fx_conversion_fees_eur == Decimal("1")
    assert statement.stamp_duty_eur == Decimal("0.50")
    assert statement.french_transaction_tax_eur == Decimal("0.25")
    assert statement.explicit_costs_eur == Decimal("2.98")
    assert statement.trades_count == 1
    assert statement.corporate_actions_count == 1
    assert statement.missing_timestamps == 0
    assert statement.unknown_actions == ()
    assert statement.net_capital_eur == Decimal("170")
    assert statement.api_equivalent_deposits_eur == Decimal("224.23")
    assert statement.api_equivalent_withdrawals_eur == Decimal("50.10")
    assert statement.api_equivalent_net_deposits_eur == Decimal("174.13")
    assert statement.expected_pnl_eur(Decimal("-20")) == Decimal("-7.48")
    assert statement.period_start.startswith("2026-01-01")
    assert statement.period_end.startswith("2026-01-10")


def test_reconciliation_passes_when_bridge_matches(tmp_path):
    path = _write_statement(tmp_path / "from_2026-01-01_to_2026-01-31.csv")
    statement = parse_t212_statement(path)

    result = reconcile_t212_statement(
        statement,
        api_total_deposits_eur=224.23,
        api_total_withdrawals_eur=-50.10,
        api_net_deposits_eur=174.13,
        api_net_pnl_eur=-7.48,
        api_fees_eur=1.23,
        api_interest_eur=0.50,
        unrealized_pnl_eur=-20,
    )

    assert result.status == "PASS"
    assert result.deltas["deposits_delta_eur"] == 0
    assert result.deltas["withdrawals_delta_eur"] == 0
    assert result.deltas["net_deposits_delta_eur"] == 0
    assert result.deltas["net_pnl_delta_eur"] == 0
    assert result.reasons == ()
    assert "Status: PASS" in render_reconciliation_markdown(result)


def test_reconciliation_partial_on_unknown_action(tmp_path):
    path = _write_statement(
        tmp_path / "from_2026-01-01_to_2026-01-31.csv",
        extra={"Action": "Mystery action", "Time (UTC)": "2026-01-11T10:00:00+00:00",
               "Total": "0.00", "Currency (Total)": "EUR"},
    )
    statement = parse_t212_statement(path)

    assert statement.unknown_actions == ("Mystery action",)
    result = reconcile_t212_statement(
        statement,
        api_total_deposits_eur=224.23,
        api_total_withdrawals_eur=50.10,
        api_net_deposits_eur=174.13,
        api_net_pnl_eur=-7.48,
        api_fees_eur=1.23,
        api_interest_eur=0.50,
        unrealized_pnl_eur=-20,
    )
    assert result.status == "PARTIAL"
    assert any("Unrecognized" in reason for reason in result.reasons)


def test_reconciliation_unavailable_without_statement():
    result = reconcile_t212_statement(
        None,
        api_total_deposits_eur=1,
        api_total_withdrawals_eur=0,
        api_net_deposits_eur=1,
        api_net_pnl_eur=0,
        api_fees_eur=0,
        api_interest_eur=0,
        unrealized_pnl_eur=0,
    )
    assert result.status == "UNAVAILABLE"
    assert "No Trading 212 CSV" in render_reconciliation_markdown(result)


def test_find_latest_statement_prefers_newest(tmp_path):
    older = _write_statement(tmp_path / "from_2026-01-01_to_2026-01-31.csv")
    newer = _write_statement(tmp_path / "from_2026-02-01_to_2026-02-28.csv")
    older.touch()
    newer.touch()
    # Make the second file unambiguously newer.
    newer.write_text(newer.read_text(encoding="utf-8"), encoding="utf-8")
    assert find_latest_t212_statement(tmp_path) == newer

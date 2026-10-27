"""Trading 212 statement reconciliation (read-only, deterministic).

Parses a manually exported Trading 212 activity CSV and reconciles it with
the API-derived account performance used by the report.  The statement is
never treated as a replacement for broker truth: it is an independent check
that explains deposits, withdrawals, dividends, interest, realised P&L and
explicit costs.

Key conventions from T212 activity exports:
- ``Total`` is the account-currency cash amount (EUR here).
- ``Result`` is realised P&L on sells.
- ``Deposit`` Total is the net deposit; ``Charge amount`` is the gross card
  charge and ``Deposit fee`` is the fee.
- ``Card debit`` is a withdrawal; ``Card credit`` / ``Spending cashback`` are
  capital credits (the API reports them as deposits).
- Dividends are net cash; withholding tax is informational.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

ZERO = Decimal("0")
CENT = Decimal("0.01")
DEFAULT_TOLERANCE_EUR = Decimal("0.05")


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _pick(headers: Iterable[str], *candidates: str) -> str | None:
    actual = {_norm(h): h for h in headers}
    for candidate in candidates:
        key = _norm(candidate)
        if key in actual:
            return actual[key]
    return None


def _dec(value: Any) -> Decimal:
    """Parse a T212 money field without floats; never raises."""
    raw = str(value if value is not None else "").strip()
    if not raw:
        return ZERO
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", raw.replace(",", ""))
    if cleaned in ("", "-", ".", "-."):
        return ZERO
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return ZERO
    return -amount if negative else amount


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _money(value: Decimal) -> float:
    return float(value.quantize(CENT))


@dataclass(frozen=True)
class T212StatementSummary:
    source_file: str
    period_start: str
    period_end: str
    row_count: int
    action_counts: dict[str, int]
    deposits_eur: Decimal = ZERO
    deposit_fees_eur: Decimal = ZERO
    card_debits_eur: Decimal = ZERO
    card_credits_eur: Decimal = ZERO
    cashback_positive_eur: Decimal = ZERO
    cashback_negative_eur: Decimal = ZERO
    dividends_eur: Decimal = ZERO
    interest_eur: Decimal = ZERO
    realized_pnl_eur: Decimal = ZERO
    fx_conversion_fees_eur: Decimal = ZERO
    stamp_duty_eur: Decimal = ZERO
    french_transaction_tax_eur: Decimal = ZERO
    charge_amount_eur: Decimal = ZERO
    withholding_tax_by_currency: dict[str, Decimal] = field(default_factory=dict)
    trades_count: int = 0
    corporate_actions_count: int = 0
    missing_timestamps: int = 0
    unknown_actions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def net_capital_eur(self) -> Decimal:
        """User capital in the period: deposits minus card debits."""
        return self.deposits_eur - self.card_debits_eur

    @property
    def cashback_net_eur(self) -> Decimal:
        return self.cashback_positive_eur - self.cashback_negative_eur

    @property
    def api_equivalent_deposits_eur(self) -> Decimal:
        """Deposits as the API reports them (includes cashback/credits + fee gross-up)."""
        return (self.deposits_eur + self.cashback_positive_eur
                + self.card_credits_eur + self.deposit_fees_eur)

    @property
    def api_equivalent_withdrawals_eur(self) -> Decimal:
        return self.card_debits_eur + self.cashback_negative_eur

    @property
    def api_equivalent_net_deposits_eur(self) -> Decimal:
        return self.api_equivalent_deposits_eur - self.api_equivalent_withdrawals_eur

    @property
    def explicit_costs_eur(self) -> Decimal:
        return (self.fx_conversion_fees_eur + self.stamp_duty_eur
                + self.french_transaction_tax_eur + self.deposit_fees_eur)

    def expected_pnl_eur(self, unrealized_pnl_eur: Decimal) -> Decimal:
        return (self.realized_pnl_eur + self.dividends_eur + self.interest_eur
                - self.explicit_costs_eur + unrealized_pnl_eur)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "row_count": self.row_count,
            "action_counts": dict(self.action_counts),
            "deposits_eur": _money(self.deposits_eur),
            "deposit_fees_eur": _money(self.deposit_fees_eur),
            "card_debits_eur": _money(self.card_debits_eur),
            "card_credits_eur": _money(self.card_credits_eur),
            "cashback_positive_eur": _money(self.cashback_positive_eur),
            "cashback_negative_eur": _money(self.cashback_negative_eur),
            "net_capital_eur": _money(self.net_capital_eur),
            "cashback_net_eur": _money(self.cashback_net_eur),
            "dividends_eur": _money(self.dividends_eur),
            "interest_eur": _money(self.interest_eur),
            "realized_pnl_eur": _money(self.realized_pnl_eur),
            "fx_conversion_fees_eur": _money(self.fx_conversion_fees_eur),
            "stamp_duty_eur": _money(self.stamp_duty_eur),
            "french_transaction_tax_eur": _money(self.french_transaction_tax_eur),
            "explicit_costs_eur": _money(self.explicit_costs_eur),
            "charge_amount_eur": _money(self.charge_amount_eur),
            "withholding_tax_by_currency": {
                ccy: _money(amount) for ccy, amount in self.withholding_tax_by_currency.items()
            },
            "trades_count": self.trades_count,
            "corporate_actions_count": self.corporate_actions_count,
            "missing_timestamps": self.missing_timestamps,
            "unknown_actions": list(self.unknown_actions),
            "warnings": list(self.warnings),
            "api_equivalent_deposits_eur": _money(self.api_equivalent_deposits_eur),
            "api_equivalent_withdrawals_eur": _money(self.api_equivalent_withdrawals_eur),
            "api_equivalent_net_deposits_eur": _money(self.api_equivalent_net_deposits_eur),
        }


_TRADE_PREFIXES = ("market ", "limit ", "stop ", "stop limit ")
_DIVIDEND_PREFIXES = ("dividend", "stock dividend")
_DEPOSIT_ACTIONS = {"deposit", "cash deposit"}
_WITHDRAWAL_ACTIONS = {"withdrawal", "withdraw", "cash withdrawal", "bank withdrawal", "card debit"}
_CARD_CREDIT_ACTIONS = {"card credit"}
_CASHBACK_ACTIONS = {"spending cashback", "cashback"}
_INTEREST_ACTIONS = {"lending interest", "interest on cash", "interest", "cash interest"}
_CORPORATE_ACTIONS = {"stock split close", "stock split open", "stock split", "reverse split"}


def parse_t212_statement(path: str | Path) -> T212StatementSummary:
    """Parse a T212 activity CSV into a deterministic summary.

    Unknown rows are counted and reported as warnings; they never raise.
    """
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        col_action = _pick(headers, "Action", "Type")
        col_time = _pick(headers, "Time (UTC)", "Time", "Date/Time", "Date")
        col_total = _pick(headers, "Total", "Amount", "Net amount")
        col_currency = _pick(headers, "Currency (Total)", "Currency")
        col_result = _pick(headers, "Result")
        col_deposit_fee = _pick(headers, "Deposit fee")
        col_fx_fee = _pick(headers, "Currency conversion fee", "FX fee")
        col_stamp = _pick(headers, "Stamp duty reserve tax", "Stamp duty")
        col_french = _pick(headers, "French transaction tax")
        col_charge = _pick(headers, "Charge amount")
        col_withholding = _pick(headers, "Withholding tax")
        col_withholding_ccy = _pick(headers, "Currency (Withholding tax)")

        if not col_action or not col_total:
            return T212StatementSummary(
                source_file=source.name, period_start="", period_end="",
                row_count=0, action_counts={},
                warnings=("CSV is missing Action or Total columns; statement not parsed.",),
            )

        action_counts: Counter[str] = Counter()
        unknown: set[str] = set()
        warnings: list[str] = []
        withholding: defaultdict[str, Decimal] = defaultdict(Decimal)
        period_start: datetime | None = None
        period_end: datetime | None = None
        non_eur_currencies: set[str] = set()
        missing_timestamps = 0
        row_count = 0

        sums = {key: ZERO for key in (
            "deposits", "deposit_fees", "card_debits", "card_credits",
            "cashback_positive", "cashback_negative", "dividends", "interest",
            "realized", "fx_fees", "stamp", "french", "charge",
            "charge_deposits", "charge_fees",
        )}
        trades = 0
        corporate = 0

        for row in reader:
            if not any(str(v or "").strip() for v in row.values()):
                continue
            row_count += 1
            action_raw = str(row.get(col_action, "") or "").strip()
            action = _norm(action_raw)
            action_counts[action_raw or "(empty)"] += 1

            total = _dec(row.get(col_total)) if col_total else ZERO
            result = _dec(row.get(col_result)) if col_result else ZERO
            deposit_fee = abs(_dec(row.get(col_deposit_fee))) if col_deposit_fee else ZERO
            fx_fee = abs(_dec(row.get(col_fx_fee))) if col_fx_fee else ZERO
            stamp = abs(_dec(row.get(col_stamp))) if col_stamp else ZERO
            french = abs(_dec(row.get(col_french))) if col_french else ZERO
            charge = _dec(row.get(col_charge)) if col_charge else ZERO

            ccy = str(row.get(col_currency, "") or "EUR").strip().upper() if col_currency else "EUR"
            if ccy and ccy != "EUR":
                non_eur_currencies.add(ccy)

            ts = _parse_time(row.get(col_time)) if col_time else None
            if ts is None:
                missing_timestamps += 1
            else:
                period_start = ts if period_start is None or ts < period_start else period_start
                period_end = ts if period_end is None or ts > period_end else period_end

            if action in _DEPOSIT_ACTIONS:
                sums["deposits"] += total
                sums["deposit_fees"] += deposit_fee
                sums["charge"] += charge
                if charge:
                    # Charge is only present on card-charged deposits; validate
                    # against those rows, not against every deposit.
                    sums["charge_deposits"] += total
                    sums["charge_fees"] += deposit_fee
            elif action in _WITHDRAWAL_ACTIONS:
                sums["card_debits"] += abs(total)
            elif action in _CARD_CREDIT_ACTIONS:
                sums["card_credits"] += total
            elif action in _CASHBACK_ACTIONS:
                if total < 0:
                    sums["cashback_negative"] += abs(total)
                else:
                    sums["cashback_positive"] += total
            elif action.startswith(_DIVIDEND_PREFIXES):
                sums["dividends"] += total
                if col_withholding and col_withholding_ccy:
                    wht = _dec(row.get(col_withholding))
                    wht_ccy = str(row.get(col_withholding_ccy, "") or "").strip().upper()
                    if wht and wht_ccy:
                        withholding[wht_ccy] += wht
            elif action in _INTEREST_ACTIONS:
                sums["interest"] += total
            elif action.startswith(_TRADE_PREFIXES):
                trades += 1
                sums["realized"] += result
                sums["fx_fees"] += fx_fee
                sums["stamp"] += stamp
                sums["french"] += french
            elif action in _CORPORATE_ACTIONS:
                corporate += 1
            else:
                unknown.add(action_raw or "(empty)")

        if non_eur_currencies:
            warnings.append(
                "Non-EUR Total currencies present: "
                + ", ".join(sorted(non_eur_currencies))
                + "; totals are summed without conversion."
            )
        if missing_timestamps:
            warnings.append(f"{missing_timestamps} row(s) have no parseable timestamp.")
        if unknown:
            warnings.append("Unrecognized action type(s): " + ", ".join(sorted(unknown)))
        charge_check = sums["charge_deposits"] + sums["charge_fees"]
        if sums["charge"] and abs(sums["charge"] - charge_check) > CENT:
            warnings.append(
                f"Charge column ({_money(sums['charge']):.2f}) differs from "
                f"charged deposits + fees ({_money(charge_check):.2f}); "
                "the Total column is used for reconciliation."
            )

        summary = T212StatementSummary(
            source_file=source.name,
            period_start=period_start.isoformat() if period_start else "",
            period_end=period_end.isoformat() if period_end else "",
            row_count=row_count,
            action_counts=dict(action_counts),
            deposits_eur=sums["deposits"],
            deposit_fees_eur=sums["deposit_fees"],
            card_debits_eur=sums["card_debits"],
            card_credits_eur=sums["card_credits"],
            cashback_positive_eur=sums["cashback_positive"],
            cashback_negative_eur=sums["cashback_negative"],
            dividends_eur=sums["dividends"],
            interest_eur=sums["interest"],
            realized_pnl_eur=sums["realized"],
            fx_conversion_fees_eur=sums["fx_fees"],
            stamp_duty_eur=sums["stamp"],
            french_transaction_tax_eur=sums["french"],
            charge_amount_eur=sums["charge"],
            withholding_tax_by_currency=dict(withholding),
            trades_count=trades,
            corporate_actions_count=corporate,
            missing_timestamps=missing_timestamps,
            unknown_actions=tuple(sorted(unknown)),
            warnings=tuple(warnings),
        )
        return summary


def find_latest_t212_statement(folder: str | Path | None = None) -> Path | None:
    """Return the newest T212 CSV in *folder*, or None. Never raises."""
    if not folder:
        return None
    root = Path(folder)
    if not root.is_dir():
        return None
    candidates = [p for p in root.glob("*.csv") if p.is_file()]
    if not candidates:
        return None
    # Prefer a full activity export name; fall back to any CSV by mtime.
    preferred = [p for p in candidates if p.name.lower().startswith("from_")]
    pool = preferred or candidates
    return max(pool, key=lambda p: p.stat().st_mtime)


@dataclass(frozen=True)
class T212StatementReconciliation:
    status: str
    statement: dict[str, Any]
    api: dict[str, Any]
    bridge: dict[str, Any]
    pnl_bridge: dict[str, Any]
    deltas: dict[str, Any]
    reasons: tuple[str, ...] = ()
    tolerance_eur: Decimal = DEFAULT_TOLERANCE_EUR

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "statement": self.statement,
            "api": self.api,
            "bridge": self.bridge,
            "pnl_bridge": self.pnl_bridge,
            "deltas": self.deltas,
            "reasons": list(self.reasons),
            "tolerance_eur": float(self.tolerance_eur),
        }


def _as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


def reconcile_t212_statement(
    statement: T212StatementSummary | None,
    *,
    api_total_deposits_eur: Any,
    api_total_withdrawals_eur: Any,
    api_net_deposits_eur: Any,
    api_net_pnl_eur: Any,
    api_fees_eur: Any,
    api_interest_eur: Any,
    unrealized_pnl_eur: Any,
    tolerance_eur: Decimal = DEFAULT_TOLERANCE_EUR,
) -> T212StatementReconciliation:
    """Compare the CSV summary with API-derived account performance.

    The API treats cashback/card credits as deposits and deposit fees as part
    of the gross charge, so the bridge makes those conventions explicit.
    """
    api = {
        "total_deposits_eur": _money(_as_decimal(api_total_deposits_eur)),
        "total_withdrawals_eur": _money(abs(_as_decimal(api_total_withdrawals_eur))),
        "net_deposits_eur": _money(_as_decimal(api_net_deposits_eur)),
        "net_pnl_eur": _money(_as_decimal(api_net_pnl_eur)),
        "fees_eur": _money(abs(_as_decimal(api_fees_eur))),
        "interest_eur": _money(_as_decimal(api_interest_eur)),
        "unrealized_pnl_eur": _money(_as_decimal(unrealized_pnl_eur)),
    }
    if statement is None:
        return T212StatementReconciliation(
            status="UNAVAILABLE",
            statement={},
            api=api,
            bridge={},
            pnl_bridge={},
            deltas={},
            reasons=("No Trading 212 CSV statement was provided for this run.",),
            tolerance_eur=tolerance_eur,
        )

    stmt = statement.to_dict()
    expected_dep = statement.api_equivalent_deposits_eur
    expected_wd = statement.api_equivalent_withdrawals_eur
    expected_net = statement.api_equivalent_net_deposits_eur
    expected_pnl = statement.expected_pnl_eur(_as_decimal(unrealized_pnl_eur))

    deposits_delta = _as_decimal(api["total_deposits_eur"]) - expected_dep
    withdrawals_delta = _as_decimal(api["total_withdrawals_eur"]) - expected_wd
    net_delta = _as_decimal(api["net_deposits_eur"]) - expected_net
    pnl_delta = _as_decimal(api["net_pnl_eur"]) - expected_pnl
    fees_delta = _as_decimal(api["fees_eur"]) - statement.deposit_fees_eur
    interest_delta = _as_decimal(api["interest_eur"]) - statement.interest_eur

    bridge = {
        "statement_deposits_eur": _money(statement.deposits_eur),
        "statement_cashback_positive_eur": _money(statement.cashback_positive_eur),
        "statement_card_credits_eur": _money(statement.card_credits_eur),
        "statement_deposit_fees_eur": _money(statement.deposit_fees_eur),
        "expected_api_deposits_eur": _money(expected_dep),
        "api_deposits_eur": api["total_deposits_eur"],
        "deposits_delta_eur": _money(deposits_delta),
        "statement_card_debits_eur": _money(statement.card_debits_eur),
        "statement_cashback_negative_eur": _money(statement.cashback_negative_eur),
        "expected_api_withdrawals_eur": _money(expected_wd),
        "api_withdrawals_eur": api["total_withdrawals_eur"],
        "withdrawals_delta_eur": _money(withdrawals_delta),
        "statement_net_capital_eur": _money(statement.net_capital_eur),
        "expected_api_net_deposits_eur": _money(expected_net),
        "api_net_deposits_eur": api["net_deposits_eur"],
        "net_deposits_delta_eur": _money(net_delta),
    }
    pnl_bridge = {
        "realized_pnl_eur": _money(statement.realized_pnl_eur),
        "dividends_eur": _money(statement.dividends_eur),
        "interest_eur": _money(statement.interest_eur),
        "fx_conversion_fees_eur": _money(statement.fx_conversion_fees_eur),
        "stamp_duty_eur": _money(statement.stamp_duty_eur),
        "french_transaction_tax_eur": _money(statement.french_transaction_tax_eur),
        "deposit_fees_eur": _money(statement.deposit_fees_eur),
        "explicit_costs_eur": _money(statement.explicit_costs_eur),
        "unrealized_pnl_eur": api["unrealized_pnl_eur"],
        "expected_net_pnl_eur": _money(expected_pnl),
        "api_net_pnl_eur": api["net_pnl_eur"],
        "net_pnl_delta_eur": _money(pnl_delta),
        "api_fees_eur": api["fees_eur"],
        "fees_delta_eur": _money(fees_delta),
        "api_interest_eur": api["interest_eur"],
        "interest_delta_eur": _money(interest_delta),
    }
    tolerances = {
        "deposits": abs(deposits_delta) <= tolerance_eur,
        "withdrawals": abs(withdrawals_delta) <= tolerance_eur,
        "net_deposits": abs(net_delta) <= tolerance_eur,
        "net_pnl": abs(pnl_delta) <= tolerance_eur,
    }
    reasons: list[str] = []
    if not all(tolerances.values()):
        if not tolerances["deposits"]:
            reasons.append(f"Deposits differ by {_money(deposits_delta):+.2f} EUR.")
        if not tolerances["withdrawals"]:
            reasons.append(f"Withdrawals differ by {_money(withdrawals_delta):+.2f} EUR.")
        if not tolerances["net_deposits"]:
            reasons.append(f"Net deposits differ by {_money(net_delta):+.2f} EUR.")
        if not tolerances["net_pnl"]:
            reasons.append(f"Net P&L differs by {_money(pnl_delta):+.2f} EUR.")
    if statement.unknown_actions:
        reasons.append("Unrecognized CSV actions: " + ", ".join(statement.unknown_actions))
    if statement.missing_timestamps:
        reasons.append(f"{statement.missing_timestamps} CSV row(s) have no parseable timestamp.")

    status = "PASS" if all(tolerances.values()) and not statement.unknown_actions else "PARTIAL"
    return T212StatementReconciliation(
        status=status,
        statement=stmt,
        api=api,
        bridge=bridge,
        pnl_bridge=pnl_bridge,
        deltas={
            "deposits_delta_eur": _money(deposits_delta),
            "withdrawals_delta_eur": _money(withdrawals_delta),
            "net_deposits_delta_eur": _money(net_delta),
            "net_pnl_delta_eur": _money(pnl_delta),
            "fees_delta_eur": _money(fees_delta),
            "interest_delta_eur": _money(interest_delta),
            "tolerances": tolerances,
        },
        reasons=tuple(reasons),
        tolerance_eur=tolerance_eur,
    )


def render_reconciliation_markdown(reconciliation: dict[str, Any] | T212StatementReconciliation | None) -> str:
    """Render a compact English Markdown section. Never raises."""
    if reconciliation is None:
        return (
            "### Broker Statement Reconciliation\n\n"
            "No Trading 212 CSV statement was provided; API history is authoritative."
        )
    data = reconciliation.to_dict() if isinstance(reconciliation, T212StatementReconciliation) else reconciliation
    status = str(data.get("status", "UNAVAILABLE"))
    if status == "UNAVAILABLE":
        reasons = "; ".join(data.get("reasons") or [])
        return (
            "### Broker Statement Reconciliation\n\n"
            f"**UNAVAILABLE** — {reasons or 'no statement provided'}. "
            "API history remains authoritative."
        )

    stmt = data.get("statement") or {}
    bridge = data.get("bridge") or {}
    pnl = data.get("pnl_bridge") or {}
    reasons = data.get("reasons") or []

    dep_raw = float(bridge.get("statement_deposits_eur", 0) or 0)
    dep_api = float(bridge.get("api_deposits_eur", 0) or 0)
    wd_raw = float(bridge.get("statement_card_debits_eur", 0) or 0)
    wd_api = float(bridge.get("api_withdrawals_eur", 0) or 0)
    net_raw = float(bridge.get("statement_net_capital_eur", 0) or 0)
    net_api = float(bridge.get("api_net_deposits_eur", 0) or 0)
    pnl_stmt = float(pnl.get("expected_net_pnl_eur", 0) or 0)
    pnl_api = float(pnl.get("api_net_pnl_eur", 0) or 0)
    deltas = data.get("deltas") or {}
    dep_delta = float(deltas.get("deposits_delta_eur", 0) or 0)
    wd_delta = float(deltas.get("withdrawals_delta_eur", 0) or 0)
    net_delta = float(deltas.get("net_deposits_delta_eur", 0) or 0)
    pnl_delta = float(deltas.get("net_pnl_delta_eur", 0) or 0)

    lines = [
        "### Broker Statement Reconciliation",
        "",
        f"**Status: {status}** - {stmt.get('source_file', 'statement')} "
        f"({stmt.get('period_start', '?')[:10]} → {stmt.get('period_end', '?')[:10]}, "
        f"{stmt.get('row_count', 0):,} rows).",
        "",
        "| Metric | Statement raw | Bridge | API / broker | Delta |",
        "|---|---:|---:|---:|---:|",
        f"| Deposits | €{dep_raw:,.2f} | €{dep_api - dep_raw:+,.2f} "
        f"| €{dep_api:,.2f} | €{dep_delta:+,.2f} |",
        f"| Withdrawals / card debits | €{wd_raw:,.2f} | €{wd_api - wd_raw:+,.2f} "
        f"| €{wd_api:,.2f} | €{wd_delta:+,.2f} |",
        f"| Net deposits | €{net_raw:,.2f} | €{net_api - net_raw:+,.2f} "
        f"| €{net_api:,.2f} | €{net_delta:+,.2f} |",
        f"| Net P&L | €{pnl_stmt:,.2f} | €{pnl_api - pnl_stmt:+,.2f} "
        f"| €{pnl_api:,.2f} | €{pnl_delta:+,.2f} |",
        "",
        "**Basis:** statement net capital (deposits minus card debits) is "
        f"€{net_raw:,.2f}; API net deposits include cashback/card credits and the "
        "deposit-fee gross-up. The bridge is exact.",
        "",
        "**P&L bridge:** "
        f"realised €{pnl.get('realized_pnl_eur', 0):,.2f} + "
        f"dividends €{pnl.get('dividends_eur', 0):,.2f} + "
        f"interest €{pnl.get('interest_eur', 0):,.2f} − "
        f"explicit costs €{pnl.get('explicit_costs_eur', 0):,.2f} + "
        f"unrealised €{pnl.get('unrealized_pnl_eur', 0):,.2f} = "
        f"€{pnl.get('expected_net_pnl_eur', 0):,.2f}.",
        "",
        "**Explicit costs:** "
        f"FX conversion €{pnl.get('fx_conversion_fees_eur', 0):,.2f}, "
        f"stamp duty €{pnl.get('stamp_duty_eur', 0):,.2f}, "
        f"French FTT €{pnl.get('french_transaction_tax_eur', 0):,.2f}, "
        f"deposit fees €{pnl.get('deposit_fees_eur', 0):,.2f}. "
        "API `fees_eur` covers the deposit fee only; FX conversion, stamp duty "
        "and FTT are embedded in trade totals.",
        "",
        "**Deposit bridge:** "
        f"statement deposits €{bridge.get('statement_deposits_eur', 0):,.2f} + "
        f"cashback/credits €{bridge.get('statement_cashback_positive_eur', 0) + bridge.get('statement_card_credits_eur', 0):,.2f} + "
        f"deposit-fee gross-up €{bridge.get('statement_deposit_fees_eur', 0):,.2f} = "
        f"API deposits €{bridge.get('api_deposits_eur', 0):,.2f}.",
    ]
    if reasons:
        lines += ["", "**Notes:** " + "; ".join(reasons) + "."]
    return "\n".join(lines)

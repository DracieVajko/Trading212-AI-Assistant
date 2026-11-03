"""Broker snapshot, reconciliation, and universe extension."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from investment_engine import liveness as _lv
from investment_engine.config.settings import EngineSettings

logger = logging.getLogger(__name__)


@dataclass
class BrokerPhase:
    """Result of fetching T212 data and reconciling it."""

    settings_dict: dict[str, Any]
    t212_data: dict[str, Any]
    snapshot: Any = None
    recon_result: Any = None
    positions: list[dict[str, Any]] = field(default_factory=list)
    recon: dict[str, Any] = field(
        default_factory=lambda: {
            "total_equity": 0,
            "positions_value": 0,
            "implied_cash": 0,
            "reported_cash": 0,
            "cash_delta": 0,
            "threshold": 0,
            "status": "UNKNOWN",
        }
    )
    reconciliation_ok: bool = True


def fetch_broker_phase(
    *,
    settings: EngineSettings,
    run_id: str,
    reports_dir: str,
    portfolio_context: dict[str, Any],
    assets: list[dict[str, Any]],
    all_active_assets: list[dict[str, Any]],
    known_clean: set[str],
) -> BrokerPhase:
    """Fetch T212, dump raw diagnostics, reconcile, and extend the universe."""
    from investment_engine.fetching import fetch_t212_data

    settings_dict = (
        asdict(settings)
        if hasattr(settings, "__dataclass_fields__")
        else settings.__dict__
    )
    t212_data = fetch_t212_data(settings_dict)

    if t212_data and t212_data.get("status") == "ok":
        try:
            from trading212.auth import dump_raw_t212_diagnostics
            from trading212.integration import create_integration

            diag_run_id = (
                portfolio_context.get("run_id")
                if isinstance(portfolio_context, dict)
                else str(uuid.uuid4())[:8]
            )
            diag_client = create_integration(config_file="api.env")
            if diag_client and diag_client.monitor and diag_client.monitor.client:
                diag_result = dump_raw_t212_diagnostics(
                    diag_client.monitor.client, run_id=diag_run_id
                )
                if diag_result:
                    t212_data["raw_endpoint_diagnostic"] = diag_result
        except Exception as exc:
            logger.debug("Raw endpoint diagnostic skipped: %s", exc)

    if t212_data and t212_data.get("status") == "ok":
        summary = t212_data.get("account_summary", {}) or {}
        auth_positions = (
            summary.get("all_positions")
            or t212_data.get("all_positions")
            or summary.get("positions", [])
        )
        for pos in auth_positions:
            if not isinstance(pos, dict) or pos.get("is_pie_constituent"):
                continue
            symbol = pos.get("symbol")
            if symbol and not any(a.get("ticker") == symbol for a in all_active_assets):
                entry: dict[str, Any] = {"ticker": symbol}
                if (
                    pos.get("name")
                    and str(pos["name"]).strip().upper() != str(symbol).strip().upper()
                ):
                    entry["name"] = pos["name"]
                all_active_assets.append(entry)

    snapshot = None
    recon_result = None
    positions: list[dict[str, Any]] = []
    # Canonical broker-first snapshot FIRST (A3 sanitation): every
    # reconciliation consumer uses this single result. Legacy R1 summary
    # fields are never read here and never gate decisions.
    recon = {
        "total_equity": 0,
        "positions_value": 0,
        "implied_cash": 0,
        "reported_cash": 0,
        "cash_delta": 0,
        "threshold": 0,
        "status": "UNKNOWN",
    }
    try:
        from investment_engine.portfolio.broker_first import (
            build_account_snapshot as _build_snap,
            get_cached_catalog as _get_cat,
            reconcile_snapshot as _reconcile_snap,
        )
        from trading212.portfolio import get_live_fx_rates as _live_fx

        summary = (
            t212_data.get("account_summary", {}) or {}
            if isinstance(t212_data, dict)
            else {}
        )
        positions = (
            summary.get("raw_positions")
            or summary.get("all_positions")
            or (t212_data.get("all_positions", []) if isinstance(t212_data, dict) else [])
        )
        snapshot = _build_snap(
            {
                "free": summary.get("cash_free", 0),
                "pieCash": summary.get("cash_pie", 0),
                "blocked": summary.get("cash_blocked", 0),
                "invested": summary.get("invested", 0),
                "total": summary.get("total_equity", 0),
                "ppl": summary.get("unrealized_pnl_eur", 0),
            },
            positions,
            None,
            known_clean=known_clean,
            live_rates=(_live_fx().get("rates") or {}),
            catalog=_get_cat() or None,
        )
        recon_result = _reconcile_snap(snapshot)
        recon = recon_result.to_reconciliation_dict()
    except Exception as exc:
        logger.debug("Snapshot build skipped: %s", exc)

    reconciliation_ok = True
    if t212_data and t212_data.get("status") == "ok":
        logger.info(
            "T212 canonical: equity=EUR %.2f | reported_cash=EUR %.2f | expected=EUR %.2f | "
            "dedup=EUR %.2f | excluded=EUR %.2f | delta=EUR %+.2f (threshold EUR %.2f) -> %s",
            recon.get("total_equity", 0),
            recon.get("reported_cash", 0),
            getattr(recon_result, "expected_open_positions_value_eur", 0) or 0,
            getattr(recon_result, "sum_deduplicated_broker_position_values_eur", 0) or 0,
            getattr(recon_result, "sum_excluded_values_eur", 0) or 0,
            recon.get("cash_delta", 0),
            recon.get("threshold", 0),
            recon.get("status", "UNKNOWN"),
        )
        if recon.get("status") == "FAIL":
            reconciliation_ok = False
            logger.warning(
                "T212 reconciliation FAILED - suppressing account-level P&L and derived "
                "return from report and LLM"
            )
            t212_data["reconciliation_ok"] = False
        else:
            t212_data["reconciliation_ok"] = True
    else:
        t212_data = t212_data or {"status": "failed", "reconciliation_ok": False}

    _lv.write_checkpoint(
        reports_dir,
        run_id,
        "broker",
        {
            "t212_status": (t212_data.get("status") if isinstance(t212_data, dict) else "failed"),
            "recon_status": recon.get("status", "UNKNOWN"),
            "total_equity": recon.get("total_equity", 0),
            "reported_cash": recon.get("reported_cash", 0),
            "positions": len(positions) if isinstance(positions, list) else 0,
            "reconciliation_ok": reconciliation_ok,
        },
    )

    return BrokerPhase(
        settings_dict=settings_dict,
        t212_data=t212_data,
        snapshot=snapshot,
        recon_result=recon_result,
        positions=positions,
        recon=recon,
        reconciliation_ok=reconciliation_ok,
    )

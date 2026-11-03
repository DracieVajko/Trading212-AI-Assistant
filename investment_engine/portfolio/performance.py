"""Account performance resolution (broker equity vs verified cash flows)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

from investment_engine.schemas.context import T212Snapshot

logger = logging.getLogger(__name__)

def _resolve_account_performance(t212_data: T212Snapshot | None, portfolio_context: dict | None) -> tuple[dict, dict]:
    """Resolve net deposits (verified API history > manual baseline) and build
    broker-equity-based account performance. Returns (performance, ledger_metadata).
    Never logs payloads, references, or credentials — counts and statuses only.
    """
    from investment_engine.accounting import cashflows as _cf
    summary = ((t212_data or {}).get("account_summary", {}) or {})
    cash = ((t212_data or {}).get("cash", {}) or {})
    equity = summary.get("total_equity")
    free_cash = cash.get("free", summary.get("cash_free"))
    pie_cash = cash.get("pie_cash", summary.get("cash_pie"))
    blocked_cash = summary.get("cash_blocked", cash.get("blocked", 0))

    api_result: dict | None = None
    if isinstance(t212_data, dict) and t212_data.get("status") == "ok":
        try:
            from trading212.integration import create_integration
            _t212 = create_integration(config_file="api.env")
            _client = getattr(getattr(_t212, "monitor", None), "client", None)
            if _client is not None:
                with ThreadPoolExecutor(max_workers=1) as _ex:
                    _fut = _ex.submit(_client.get_all_transaction_history)
                    try:
                        _pages = _fut.result(timeout=120)
                    except FuturesTimeoutError:
                        _pages = {"pages": [], "exhausted": False, "timeout": True}
                api_result = _cf.ingest_history_pages(
                    (_pages or {}).get("pages", []), bool((_pages or {}).get("exhausted", False)))
                try:
                    if api_result.get("status") == "VERIFIED":
                        _cf.save_history_cache(api_result)
                except Exception:
                    pass
                logger.info("Cash-flow history: status=%s items=%d pages=%d exhausted=%s",
                            api_result.get("status"), api_result.get("item_count", 0),
                            api_result.get("pages", 0), api_result.get("exhausted", False))
        except Exception as exc:
            logger.debug("Cash-flow history unavailable: %s", type(exc).__name__)

    try:
        _cfg_path = (portfolio_context or {}).get("config_path")
        _root = Path(_cfg_path).parent if _cfg_path else Path.cwd()
    except Exception:
        _root = Path.cwd()
    manual = _cf.load_manual_baseline(_cf.default_baseline_path(_root))
    # Coverage anchor: earliest known account activity (position first fills).
    # An API window starting later cannot be the full capital history.
    _all_pos = ((t212_data or {}).get("account_summary", {}) or {}).get("all_positions", []) or []
    _starts = [str(p.get("initial_fill", ""))[:10] for p in _all_pos
               if isinstance(p, dict) and str(p.get("initial_fill", ""))[:10]]
    _account_start = min(_starts) if _starts else None
    if isinstance(api_result, dict):
        api_result = _cf.enforce_history_coverage(api_result, _account_start)
    resolved = _cf.resolve_net_deposits(api_result, manual, _account_start)

    # Cross-check API truth against the user-editable baseline. API wins, but a
    # silent divergence would flip the reported P&L sign (run 3ab768fb: stale
    # manual baseline turned -EUR 98 into +EUR 48), so surface the delta.
    _manual_net = None
    if isinstance(manual, dict) and isinstance(manual.get("net_deposits_eur"), (int, float)):
        _manual_net = round(float(manual["net_deposits_eur"]), 2)
    _api_net = resolved.get("net_deposits_eur")
    _crosscheck_delta = None
    _crosscheck_warning = ""
    if isinstance(_manual_net, (int, float)) and isinstance(_api_net, (int, float)):
        _crosscheck_delta = round(float(_api_net) - float(_manual_net), 2)
        if abs(_crosscheck_delta) > 1.0:
            _crosscheck_warning = (
                f"net deposits differ: API EUR {_api_net:,.2f} vs manual EUR "
                f"{_manual_net:,.2f} (delta {_crosscheck_delta:+,.2f}); API wins — "
                "update data/portfolio_performance.toml")
            logger.warning("Cash-flow cross-check: %s", _crosscheck_warning)

    api_summary = (api_result or {}).get("summary", {}) if isinstance(api_result, dict) else {}
    metadata = {
        "api_status": (api_result or {}).get("status", "UNAVAILABLE"),
        "api_items": (api_result or {}).get("item_count", 0),
        "api_pages": (api_result or {}).get("pages", 0),
        "api_exhausted": bool((api_result or {}).get("exhausted", False)),
        "api_unresolved_fx": api_summary.get("unresolved_count", 0) if api_summary else 0,
        "manual_present": manual is not None,
        "manual_path": "data/portfolio_performance.toml",
        "manual_baseline_eur": _manual_net,
        "api_vs_manual_delta_eur": _crosscheck_delta,
        "crosscheck_warning": _crosscheck_warning,
        "selected_source": resolved.get("net_deposits_source"),
        "selected_status": resolved.get("net_deposits_status"),
        "fx_complete": bool(resolved.get("net_deposits_status") == "VERIFIED"
                            and (api_summary.get("unresolved_count", 0) if api_summary else 0) == 0)
                        or resolved.get("net_deposits_status") == "MANUAL",
    }
    performance = _cf.build_account_performance(
        equity, free_cash, pie_cash, blocked_cash,
        resolved.get("net_deposits_eur"), resolved.get("net_deposits_source"),
        resolved.get("net_deposits_status"),
        fees_eur=resolved.get("fees_eur"), interest_eur=resolved.get("interest_eur"),
        total_deposits_eur=resolved.get("total_deposits_eur"),
        total_withdrawals_eur=resolved.get("total_withdrawals_eur"),
    )
    return performance, metadata

# Public aliases for cross-module use (private names remain the
# implementation detail and stay available for in-module calls).
resolve_account_performance = _resolve_account_performance

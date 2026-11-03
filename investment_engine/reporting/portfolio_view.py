"""Portfolio-derived report inputs: names, canonical decisions, sanitizers."""

from __future__ import annotations

from dataclasses import asdict

from investment_engine.reporting.sections import _build_monitoring_block
from investment_engine.schemas.context import T212Snapshot

def _canonical_decisions(ai_recs: dict | None) -> dict[str, str]:
    """Canonical display-ticker → action map (see regime_report.build_canonical_signals).

    Single source of truth against duplicated/conflicting verdicts across
    report sections. Values are normalized BUY / SELL / HOLD.
    """
    try:
        from investment_engine.reporting.regime_report import build_canonical_signals
        canon_full = build_canonical_signals(ai_recs)
        out: dict[str, str] = {}
        for k, v in canon_full.items():
            disp = (v.get("display") if isinstance(v, dict) else None) or str(k).split("_")[0]
            sig = (v.get("signal") if isinstance(v, dict) else v) or "HOLD"
            out.setdefault(str(disp).strip().upper(), str(sig))
        return out
    except Exception:
        pass
    canon: dict[str, str] = {}
    if not isinstance(ai_recs, dict):
        return canon
    for t in ai_recs.get("trades", []) or []:
        if isinstance(t, dict) and t.get("asset"):
            canon[str(t["asset"]).strip().upper()] = str(t.get("side", "")).strip().upper() or "HOLD"
    for a in ai_recs.get("portfolio_actions", []) or []:
        if isinstance(a, dict) and a.get("asset"):
            canon.setdefault(str(a["asset"]).strip().upper(), str(a.get("action", "")).strip().upper() or "HOLD")
    return canon


def _portfolio_tickers_for_priority(t212_data: dict | None, known_clean: set | None = None) -> set[str]:
    """Allowed tickers for Priority Actions: display symbols of the unified set."""
    try:
        from investment_engine.portfolio.symbols import to_display_symbol as _td
    except Exception:
        _td = lambda s, *_: str(s or "").strip().upper().split("_")[0]
    tickers: set[str] = set()
    if not isinstance(t212_data, dict):
        return tickers
    summary = t212_data.get("account_summary", {}) or {}
    # Authoritative first; fallback only when unavailable; never merged.
    cands: list[dict] = list(summary.get("all_positions") or [])
    if not cands:
        cands = list(t212_data.get("all_positions") or [])
    if not cands:
        cands = list(t212_data.get("positions", []) or [])
        if not cands and isinstance(summary.get("positions"), list):
            cands = list(summary["positions"])
    for p in cands:
        if isinstance(p, dict) and p.get("symbol"):
            try:
                tickers.add(_td(str(p["symbol"]), known_clean))
            except Exception:
                tickers.add(str(p["symbol"]).strip().upper())
    return tickers


def _build_portfolio_names(all_active_assets, pie_blocks, t212_data: T212Snapshot | None, known_names_base: dict | None = None) -> dict[str, str]:
    """Display symbol -> company name (pie slices + config assets + overrides).

    Never maps a name to an internal broker ID, and never uses an internal
    ID as a name fallback.
    """
    names: dict[str, str] = dict(known_names_base or {})
    try:
        from investment_engine.portfolio.symbols import COMPANY_OVERRIDES, to_display_symbol as _td2
    except Exception:
        COMPANY_OVERRIDES = {}
        _td2 = lambda s, *_: str(s or "").strip().upper().split("_")[0]
    try:
        for item in all_active_assets or []:
            if isinstance(item, dict) and item.get("ticker") and item.get("name"):
                t, n = str(item["ticker"]), str(item["name"])
                if n.strip().upper() == t.strip().upper():
                    continue  # broker ID echoed as name — not a real company name
                disp = _td2(t)
                names.setdefault(disp, n)
    except Exception:
        pass
    try:
        for b in pie_blocks or []:
            for s in (b or {}).get("sample", []) or []:
                if isinstance(s, dict) and s.get("slice"):
                    disp = s.get("display") or _td2(str(s["slice"]))
                    names.setdefault(disp, str(s.get("name") or disp))
                if isinstance(s, dict) and s.get("name") and s.get("slice"):
                    names.setdefault(_td2(str(s["slice"])), str(s["name"]))
    except Exception:
        pass
    try:
        pools: list[dict] = []
        if isinstance(t212_data, dict):
            _s = t212_data.get("account_summary", {}) or {}
            pools.extend(_s.get("all_positions", []) or [])
            pools.extend(t212_data.get("all_positions", []) or [])
            pools.extend(t212_data.get("positions", []) or [])
        for p in pools:
            if isinstance(p, dict) and p.get("symbol") and p.get("name"):
                disp = _td2(str(p["symbol"]))
                nm = str(p["name"]).strip()
                if nm and nm.upper() != str(p["symbol"]).strip().upper():
                    names.setdefault(disp, nm)
    except Exception:
        pass
    for _k, _v in (COMPANY_OVERRIDES or {}).items():
        names.setdefault(str(_k).strip().upper(), str(_v))
    return names


def _apply_fail_watchlist_sweep(
    summary_md: str,
    decision_sections: list,
    portfolio_rows: list[dict] | None = None,
    earnings_status: dict | None = None,
    technicals: dict | None = None,
) -> tuple[str, list]:
    """FAIL-state terminology sweep (see _build_monitoring_block).

    - "Actionable Tickers" line is replaced by the deterministic Portfolio
      Monitoring bullet (owned HOLDs stay HOLD; triggers render REVIEW).
    - Remaining BUY action labels become WATCH (research-only, non-owned).
    - Appends the visible research-only disclaimer.
    """
    import re as _re7
    monitoring = _build_monitoring_block(portfolio_rows, earnings_status, technicals)
    new_md, n_sub = _re7.subn(
        r"^-\s*\*\*Actionable Tickers:?\*\*:?.*$",
        monitoring,
        summary_md,
        flags=_re7.MULTILINE,
    )
    summary_md = new_md if n_sub else summary_md.rstrip() + f"\n\n{monitoring}"
    # Owned HOLD positions must never read as WATCH/BUY in FAIL prose.
    try:
        owned = sorted(
            {str((r or {}).get("display_symbol") or (r or {}).get("ticker") or "").strip().upper()
             for r in (portfolio_rows or []) if isinstance(r, dict)},
            key=len, reverse=True,
        )
        for disp in owned:
            if disp and disp != "UNKNOWN":
                summary_md = summary_md.replace(f"**{disp}** (WATCH)", f"**{disp}** (HOLD)")
                summary_md = _re7.sub(
                    r"\*\*" + _re7.escape(disp) + r"\s*\(WATCH\)(\*\*)?",
                    f"**{disp}** (HOLD)", summary_md)
        summary_md = _re7.sub(r"\bBUY\b(?=\*{0,2}\s+signals?)", "HOLD", summary_md)
    except Exception:
        pass
    summary_md = _re7.sub(r"\*\*Top Opportunities:?\*\*:?", "**Watchlist Candidates — WATCH:**", summary_md)
    summary_md = _re7.sub(r"\*\*BUY\*\*", "**WATCH**", summary_md)
    summary_md = _re7.sub(r"\(BUY(?=[,)])", "(WATCH", summary_md)
    disclaimer = ("Research-only watchlist; no deployment is authorized "
                  "while account reconciliation is failing.")
    if disclaimer not in summary_md:
        summary_md = summary_md.rstrip() + f"\n\n> {disclaimer}"
    return summary_md, decision_sections


def _sanitized_settings(settings) -> dict:
    """Settings safe for JSON reports: secret-bearing fields omitted entirely."""
    import re as _re_san
    try:
        raw = asdict(settings)
    except Exception:
        return {}
    clean: dict = {}
    for key, value in raw.items():
        if _re_san.search(r"key|secret|token|password", str(key), _re_san.IGNORECASE):
            continue
        elif isinstance(value, dict):
            clean[key] = {k: v for k, v in value.items()
                          if not _re_san.search(r"key|secret|token|password", str(k), _re_san.IGNORECASE)}
        else:
            clean[key] = value
    return clean


def _sanitized_t212_data(t212_data: T212Snapshot | None) -> T212Snapshot:
    """Broker snapshot safe for JSON reports: account identifiers removed."""
    import copy as _copy
    try:
        clean = _copy.deepcopy(t212_data) if isinstance(t212_data, dict) else {}
    except Exception:
        return {}
    try:
        summary = clean.get("account_summary")
        if isinstance(summary, dict):
            summary.pop("account_id", None)
    except Exception:
        pass
    return clean

# Public aliases for cross-module use (private names remain the
# implementation detail and stay available for in-module calls).
apply_fail_watchlist_sweep = _apply_fail_watchlist_sweep
build_portfolio_names = _build_portfolio_names
canonical_decisions = _canonical_decisions
portfolio_tickers_for_priority = _portfolio_tickers_for_priority
sanitized_settings = _sanitized_settings
sanitized_t212_data = _sanitized_t212_data

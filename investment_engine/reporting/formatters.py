"""Report formatting helpers extracted from ``main.py``.

Cash deployment, earnings radar, methodology footer, news/trump blocks, and
the deterministic summary. Kept separate from ``sections.py`` to keep each
module focused.
"""

from __future__ import annotations

from datetime import datetime, timezone

from investment_engine.portfolio import t212_view
from investment_engine.reporting.sections import _derive_top_risks, _provider_fallback_note


def _deterministic_summary(
    portfolio_rows: list[dict] | None,
    regime_result,
    t212_data: dict | None,
) -> str:
    """English summary built only from canonical rows; no trade claims."""
    rows = [r for r in (portfolio_rows or []) if isinstance(r, dict)]
    total_equity = 0.0
    free_cash = 0.0
    total_cash = 0.0
    try:
        summary = (t212_data or {}).get("account_summary", {}) or {}
        total_equity = float(summary.get("total_equity", 0) or 0)
        cash_map = (t212_data or {}).get("cash", {}) or {}
        free_cash = float(cash_map.get("free", 0) or 0)
        total_cash = (free_cash + float(cash_map.get("pie_cash", 0) or 0)
                      + float(cash_map.get("blocked", 0) or 0))
    except (TypeError, ValueError):
        pass
    cash_pct = (total_cash / total_equity * 100.0) if total_equity > 0 else 0.0
    regime = str(getattr(regime_result, "regime", "NEUTRAL") or "NEUTRAL").upper()
    target = 10.0
    try:
        target = float((getattr(regime_result, "implications", {}) or {}).get("cash_target_pct", 10.0) or 10.0)
    except (TypeError, ValueError):
        target = 10.0

    by_weight = sorted(rows, key=lambda r: -float(r.get("weight", 0) or 0))
    top = by_weight[:4]
    top_txt = ", ".join(
        f"{str(r.get('display_symbol') or r.get('ticker') or '?')} "
        f"{float(r.get('weight', 0) or 0):.1f}%"
        for r in top
    ) or "n/a"
    top_four = sum(float(r.get("weight", 0) or 0) for r in top)
    worst = sorted(rows, key=lambda r: float(r.get("pnl_pct", 0) or 0))[:3]
    worst_txt = ", ".join(
        f"{str(r.get('display_symbol') or r.get('ticker') or '?')} "
        f"{float(r.get('pnl_pct', 0) or 0):+.1f}%"
        for r in worst
    ) or "n/a"

    return "\n".join([
        "## Summary",
        f"- Portfolio: {len(rows)} positions; equity €{total_equity:,.2f}; "
        f"free cash €{free_cash:,.2f}; total cash €{total_cash:,.2f} ({cash_pct:.2f}%).",
        f"- Regime: {regime}; stance HOLD; 0 advisory orders, no execution.",
        f"- Largest positions: {top_txt}; top four = {top_four:.1f}% of equity.",
        f"- Largest drawdowns: {worst_txt}.",
        f"- Cash target: {target:.0f}% requires manual trims or deposits; no new deployment.",
    ])


def _ensure_consistent_summary(
    summary_md: str,
    portfolio_rows: list[dict] | None,
    regime_result,
    t212_data: dict | None,
) -> str:
    """Return the deterministic summary built from canonical rows.

    LLM summaries can contain unverifiable numeric claims and watchlist
    names presented as holdings. The narrative in the report must match the
    broker-truth rows, so the deterministic version is always used.
    """
    return _deterministic_summary(portfolio_rows, regime_result, t212_data)


def _apply_fail_guards(ai_recs: dict | None, recon_status: str) -> dict:
    """Deterministic FAIL-state guards (delegates to regime_report)."""
    try:
        from investment_engine.reporting.regime_report import apply_fail_guards as _guards
        return _guards(ai_recs, recon_status)
    except ImportError:
        return ai_recs or {}


def _kpi_dashboard(
    regime_result,
    t212_data: dict | None,
    ai_recs: dict | None,
    portfolio_rows: list[dict] | None = None,
    earnings_status: dict | None = None,
    technicals: dict | None = None,
) -> str:
    """Executive KPI block: regime, action counts, top risks, cash.

    Top Risks and Cash Deployment are always populated — never '-', '—',
    blank, null, N/A. Risks are derived from actual holdings (concentration,
    drawdown, earnings proximity, technical extremes). Cash states a concrete
    allocation/action, with exactly one allowed fallback when cash is unknown.
    """
    if regime_result is None:
        regime_line = "Regime unavailable"
    else:
        try:
            close = regime_result.timeframes.get("daily", {}).get("indicators", {}).get("CLOSE", 0)
            rsi = regime_result.timeframes.get("daily", {}).get("indicators", {}).get("RSI_14", 0)
            regime_line = f"**{regime_result.regime}** (EXI2 €{close:,.2f}, RSI {rsi:.0f})"
        except Exception:
            regime_line = f"**{getattr(regime_result, 'regime', 'UNKNOWN')}**"
    risks = _derive_top_risks(regime_result, t212_data, portfolio_rows, earnings_status, technicals)
    # Action counts from normalized portfolio signals (single source of truth).
    buys = sells = 0
    try:
        from investment_engine.reporting.regime_report import normalize_signal as _norm
        if portfolio_rows:
            for r in portfolio_rows:
                s = _norm(r.get("signal"))
                if s == "BUY":
                    buys += 1
                elif s == "SELL":
                    sells += 1
        elif isinstance(ai_recs, dict):
            for t in ai_recs.get("trades", []) or []:
                s = _norm((t or {}).get("side", ""))
                if s == "BUY":
                    buys += 1
                elif s == "SELL":
                    sells += 1
    except Exception:
        pass
    total = buys + sells
    if total:
        actions_line = f"{total} actions ({buys} BUY / {sells} SELL)"
    else:
        n_hold = len(portfolio_rows or [])
        actions_line = f"0 BUY/SELL actions; {n_hold} positions on HOLD/neutral" if n_hold else "No portfolio actions; holdings neutral"
    cash_line = _format_cash_deployment(regime_result, t212_data, ai_recs, portfolio_rows)
    return "\n".join([
        "## Executive Dashboard",
        "",
        "| KPI | Value |",
        "|-----|-------|",
        f"| Market Regime | {regime_line} |",
        f"| Portfolio Actions | {actions_line} |",
        f"| Top Risks | {risks} |",
        f"| Cash & Deployment | {cash_line} |",
    ])


def _format_cash_deployment(
    regime_result,
    t212_data,
    ai_recs,
    portfolio_rows,
    recon_status: str | None = None,
    sell_plan_count: int | None = None,
) -> str:
    """Concrete cash allocation/action. Single allowed fallback when unknown.

    ``sell_plan_count`` is the number of TRIM/SELL plans actually produced by
    the policy engine this run. ``None`` means the caller has no plan context,
    so the wording must not claim that SELL funding exists.
    """
    # FAIL-state guard: deployment withheld until reconciliation passes.
    # Callers pass the canonical status; the recompute below is a fallback only.
    _status = str(recon_status or "").upper()
    if _status == "FAIL":
        try:
            from investment_engine.reporting.regime_report import compute_reconciliation as _recon_fn2
            _recon2 = _recon_fn2(t212_data, portfolio_rows)
            _cash2 = _recon2.get("reported_cash", 0)
        except Exception:
            _cash2 = 0
        return (
            f"€{_cash2:,.2f} reported cash — "
            f"deployment withheld until account reconciliation passes."
        )
    if not _status:
        try:
            from investment_engine.reporting.regime_report import compute_reconciliation as _recon_fn2
            _recon2 = _recon_fn2(t212_data, portfolio_rows)
            if _recon2.get("status") == "FAIL":
                return (
                    f"€{_recon2.get('reported_cash', 0):,.2f} reported cash — "
                    f"deployment withheld until account reconciliation passes."
                )
        except Exception:
            pass
    free_cash = None
    deploy = None
    reserve = None
    targets: list[dict] = []
    if isinstance(ai_recs, dict) and isinstance(ai_recs.get("cash_deployment"), dict):
        cd = ai_recs["cash_deployment"]
        deploy, reserve = cd.get("deploy_amount"), cd.get("reserve")
        if isinstance(cd.get("targets"), list):
            targets = [t for t in cd["targets"] if isinstance(t, dict)]
    # Free cash is ALWAYS the broker figure. Model-proposed "free_cash" is
    # advisory math at best (probed 2026-10-10: Gemini 518.75 vs broker
    # 0.00) and must never override it in the brief line.
    free_cash = t212_view.optional_free_cash(t212_data)
    if free_cash is None:
        return "Cash balance unavailable — no allocation recommendation generated."
    try:
        fc = float(free_cash or 0)
    except (TypeError, ValueError):
        return "Cash balance unavailable — no allocation recommendation generated."
    # Cash target from regime (default 10%).
    cash_target_pct = 10.0
    try:
        cash_target_pct = float((regime_result.implications or {}).get("cash_target_pct", 10.0) or 10.0)
    except Exception:
        pass
    total_equity = 0.0
    try:
        total_equity = float(((t212_data or {}).get("account_summary") or {}).get("total_equity", 0) or 0)
    except Exception:
        pass
    # Explicit AI targets win — but never from empty cash (live 2026-10-12:
    # model proposed Deploy €450 with broker free €0.00). Zero-cash falls
    # through to the no-deployment branch below.
    if targets and deploy and fc > 0.01:
        try:
            from investment_engine.portfolio.symbols import to_display_symbol as _td4
            _disp_map = {}
            for _r in portfolio_rows or []:
                if isinstance(_r, dict) and (_r.get("internal_id") or _r.get("ticker")):
                    _disp_map[str(_r.get("internal_id") or _r.get("ticker")).strip().upper()] = str(
                        _r.get("display_symbol") or _r.get("ticker"))
            def _tgt_disp(a):
                au = str(a or "?").strip().upper()
                if au in _disp_map:
                    return _disp_map[au]
                return _td4(str(a or "?"))
            tstr = ", ".join(f"{_tgt_disp(t.get('asset'))} €{float(t.get('amount', 0)):,.2f}" for t in targets[:3])
            return f"€{fc:,.2f} free — Deploy €{float(deploy):,.2f} to {tstr}; keep €{float(reserve or 0):,.2f} reserve (cash target {cash_target_pct:.0f}%)"
        except Exception:
            pass
    if deploy and fc > 0.01:
        try:
            return f"€{fc:,.2f} free — Deploy €{float(deploy):,.2f}; keep €{float(reserve if reserve is not None else fc - float(deploy)):,.2f} reserve (cash target {cash_target_pct:.0f}%)"
        except Exception:
            pass
    # Derive recommendation: BUY signals available?
    n_buy = 0
    try:
        from investment_engine.reporting.regime_report import normalize_signal as _norm2
        n_buy = sum(1 for r in (portfolio_rows or []) if _norm2(r.get("signal")) == "BUY")
    except Exception:
        pass
    fc_pct = (fc / total_equity * 100.0) if total_equity > 0 else 0.0
    if fc <= 0.01:
        if sell_plan_count is None:
            funding = (f"cash target {cash_target_pct:.0f}% requires "
                       f"trims or deposits")
        elif sell_plan_count > 0:
            _noun = "plan" if sell_plan_count == 1 else "plans"
            funding = (f"{cash_target_pct:.0f}% cash target funded by "
                       f"{sell_plan_count} planned SELL {_noun}")
        else:
            funding = (f"no funded SELL plan this run; {cash_target_pct:.0f}% "
                       f"cash target requires manual trims or deposits")
        return (f"€{fc:,.2f} free ({fc_pct:.1f}% of equity) — "
                f"No deployment; {funding}")
    if n_buy > 0 and fc > 0:
        return f"€{fc:,.2f} free ({fc_pct:.1f}% of equity) — Hold reserve per {(getattr(regime_result, 'regime', 'NEUTRAL') if regime_result else 'NEUTRAL')} regime (cash target {cash_target_pct:.0f}%); deploy selectively to {n_buy} BUY signal(s) on confirmation"
    return f"€{fc:,.2f} free ({fc_pct:.1f}% of equity) — Hold as reserve; no new deployment (cash target {cash_target_pct:.0f}%, no validated BUY signals)"


def _format_earnings_radar(
    earnings_status: dict[str, tuple[str, str]],
    names: dict | None = None,
    unavailable: list[str] | None = None,
) -> str:
    """Chronological earnings timeline grouped by month, inline tags only.

    Strict format:
        ## Earnings Radar
        ## October 2026
        - Oct 14 — ASML, Company — Q3 earnings (confirmed)
    Within each month events are date-sorted ascending. Certainty appears only
    inline as (confirmed) or (estimated). No status column, no duplicates,
    no prose summaries. Instruments without coverage are listed once as
    unavailable (never reported as delisted).
    """
    try:
        from investment_engine.reporting.regime_report import _normalize_earnings_rows, _render_earnings_radar
        rows = _normalize_earnings_rows(earnings_status, names)
        if not rows:
            base = "## Earnings Radar\n\n*No upcoming earnings found in Yahoo Finance.*"
        else:
            base = _render_earnings_radar(rows)
        unav = sorted({str(u).strip().upper() for u in (unavailable or []) if u})
        dated = {r[1].strip().upper() for r in rows}
        missing = [u for u in unav if u not in dated]
        if missing:
            base += "\n\n*Earnings unavailable: " + ", ".join(missing[:12]) + ".*"
        return base.rstrip()
    except Exception:
        pass
    # Minimal deterministic fallback (same format, no imports).
    from datetime import date as _date
    import re as _re2
    norm: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    today = _date.today().isoformat()
    name_lookup = {str(k).strip().upper(): str(v) for k, v in (names or {}).items()}
    for disp, val in (earnings_status or {}).items():
        d = s = None
        if isinstance(val, (tuple, list)) and val:
            d = str(val[0])[:10]
            s = str(val[1]).lower().strip("() ") if len(val) > 1 and val[1] else "estimated"
        elif isinstance(val, str) and _re2.match(r"^\d{4}-\d{2}-\d{2}", val):
            d, s = val[:10], "estimated"
        if not d or d < today or (d, str(disp)) in seen:
            continue
        seen.add((d, str(disp)))
        st = s if s in ("confirmed", "estimated") else "estimated"
        company = name_lookup.get(str(disp).strip().upper(), str(disp).split("_")[0])
        norm.append((d, str(disp), company, st))
    if not norm:
        return "## Earnings Radar\n\n*No upcoming earnings found in Yahoo Finance.*"
    norm.sort(key=lambda r: (r[0], r[1]))
    months: dict[str, list] = {}
    order: list[str] = []
    for d, ticker, company, st in norm:
        try:
            header = f"## {_date.fromisoformat(d).strftime('%B %Y')}"
        except ValueError:
            continue
        if header not in months:
            months[header] = []
            order.append(header)
        months[header].append((d, ticker, company, st))
    lines = ["## Earnings Radar", ""]
    for header in order:
        lines.append(header)
        lines.append("")
        for d, ticker, company, st in sorted(months[header]):
            try:
                day = _date.fromisoformat(d).strftime("%b %d")
            except ValueError:
                day = d
            m = int(d[5:7])
            q = {1: "Q4", 2: "Q4", 3: "Q4", 4: "Q1", 5: "Q1", 6: "Q1", 7: "Q2", 8: "Q2", 9: "Q2", 10: "Q3", 11: "Q3", 12: "Q3"}.get(m, "")
            qlabel = f"{q} earnings" if q else "earnings"
            lines.append(f"- {day} — {ticker}, {company} — {qlabel} ({st})")
        lines.append("")
    return "\n".join(lines).rstrip()


def _methodology_block(t212_data: dict | None, provider, canonical: dict | None = None) -> str:
    """Methodology & data-quality footer (canonical recon preferred)."""
    recon = "N/A"
    if isinstance(canonical, dict) and str(canonical.get("status", "")).upper() in ("PASS", "FAIL", "UNKNOWN"):
        recon = f"{canonical.get('status')} (diff €{canonical.get('cash_delta', 0):,.2f})"
    elif isinstance(t212_data, dict):
        s = t212_data.get("account_summary", {}) or {}
        _v2m = s.get("reconciliation_v2", {}) or {}
        if str(_v2m.get("reconciliation_status", "")).upper() in ("PASS", "FAIL"):
            recon = f"{_v2m.get('reconciliation_status')} (diff €{_v2m.get('reconciliation_delta_eur') or 0:,.2f})"
        else:
            recon = "UNKNOWN (canonical reconciliation unavailable)"
    chain = getattr(provider, "name", "LLM chain")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "## Methodology & Data Quality",
        "",
        f"- Generated: {ts} | Sources: Yahoo Finance, Google News RSS (48h), Trading212 read-only API",
        f"- AI chain: {chain} (first success wins; local-first, public API fallback)",
        f"- Reconciliation: {recon} – per-position P&L is broker data; derived account totals withheld on FAIL",
        "- Full per-ticker analysis, technicals and headlines live in the AI context file.",
    ]
    note = _provider_fallback_note()
    if note:
        lines.append(note)
    return "\n".join(lines)


def _format_trump_watch(trump_watch: list[dict]) -> str:
    if not trump_watch:
        return ""
    lines = ["## Trump Watch (last 48h)"]
    for item in trump_watch:
        lines.append(f"- **{item.get('title','')}** — {item.get('source','')} · {item.get('published','')}")
    return "\n".join(lines)


def _format_news(news_by_symbol: dict[str, list[dict]]) -> str:
    if not news_by_symbol:
        return ""
    lines = ["## News (last 48h)"]
    shown = 0
    for symbol, entries in news_by_symbol.items():
        if symbol == "TRUMP":
            continue  # has its own Trump Watch section
        if not entries:
            continue
        shown += 1
        lines.append(f"### {symbol}")
        for item in entries[:3]:
            title = item.get('title', '')
            url = item.get('url', '')
            source = item.get('source', '')
            pub = item.get('published', '')
            lines.append(f"- [{title}]({url}) — {source} · {pub}")
    return "\n".join(lines) if shown else ""

# Public aliases for cross-module use (private names remain the
# implementation detail and stay available for in-module calls).
deterministic_summary = _deterministic_summary
ensure_consistent_summary = _ensure_consistent_summary
apply_fail_guards = _apply_fail_guards
kpi_dashboard = _kpi_dashboard
format_cash_deployment = _format_cash_deployment
format_earnings_radar = _format_earnings_radar
methodology_block = _methodology_block
format_trump_watch = _format_trump_watch
format_news = _format_news

"""Two-document reporting: decision brief (concise, daily) + T212 snapshot (full).

The brief never renders a full holdings table and carries no sized orders;
the snapshot is the complete financial inventory. All sections are built
deterministically from canonical rows — no LLM prose enters either document.
"""

from __future__ import annotations

import re
from datetime import date as _date
from typing import Any, Dict, List, Optional

from investment_engine.portfolio.symbols import resolve_company_name
from investment_engine.reporting.regime_report import normalize_signal, signal_emoji


# Urgency weights (higher = more urgent). No hard item cap: every triggered
# position is listed, sorted by urgency descending.
_SCORE_SELL_SIGNAL = 100
_SCORE_BREACH = 80
_SCORE_EARNINGS_7D = 70
_SCORE_WEIGHT = 60
_SCORE_BREAKOUT = 55
_SCORE_PNL = 50
_SCORE_RSI = 40
_SCORE_NEAR_LEVEL = 30
_SCORE_PIE_WARNING = 25
_SCORE_UNAVAILABLE = 20


def _fnum(value: Any, fmt: str = "{:.2f}") -> str:
    try:
        import math as _math
        f = float(value) if value is not None else None
        # float("nan")/float("inf") format as "nan"/"inf" — never render those
        # (run 524fffa0 snapshot: ESIF support/resistance showed nan).
        if f is None or _math.isnan(f) or _math.isinf(f):
            return "n/a"
        return fmt.format(f)
    except (TypeError, ValueError):
        return "n/a"


def _feur(value: Any) -> str:
    try:
        import math as _math
        f = float(value) if value is not None else None
        if f is None or _math.isnan(f) or _math.isinf(f):
            return "n/a"
        return f"€{f:,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _rsi_of(technicals: dict | None, display: str) -> float | None:
    try:
        import math as _math
        ind = (technicals or {}).get(display)
        rsi = (ind or {}).get("RSI_14") if isinstance(ind, dict) else None
        f = float(rsi) if rsi is not None else None
        if f is None or _math.isnan(f) or _math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _eur_level(row: dict | None, key: str) -> Any:
    """EUR-denominated S/R level for rendering (support/resistance).

    Rows carry ``<key>_eur`` (native converted via live/static FX) next to
    the raw native ``<key>``. Renderers must use this so levels match the
    EUR prices/P&L around them. When a new-style row explicitly failed
    conversion (support_eur None + sr_fx_status suspect/unresolved), the
    raw native must NOT leak into EUR renders (C7A0: 285 CNY next to a
    EUR 54 price) — return None so it renders as n/a. Raw fallback
    survives only for legacy rows predating these keys (tests, old callers).
    """
    if not isinstance(row, dict):
        return None
    eur = row.get(f"{key}_eur")
    if eur is not None:
        return eur
    if f"{key}_eur" in row or "sr_fx_status" in row:
        return None
    return row.get(key)


def _days_to_earnings(earnings_status: dict | None, display: str, report_date) -> tuple:
    """(days, date_iso) when an earnings date exists, else (None, '')."""
    try:
        val = (earnings_status or {}).get(display)
        d = val[0][:10] if isinstance(val, (tuple, list)) and val and isinstance(val[0], str) else None
        if not d:
            return None, ""
        delta = (_date.fromisoformat(d) - report_date).days
        return delta, d
    except (ValueError, TypeError):
        return None, ""


def build_monitoring_items(
    rows: list[dict] | None,
    *,
    earnings_status: dict | None = None,
    technicals: dict | None = None,
    pie_warnings: dict | None = None,
    recon_status: str = "UNKNOWN",
    report_date=None,
    canonical_map: dict | None = None,
) -> list[dict]:
    """Build urgency-sorted monitoring items for every triggered owned position.

    No item cap. In FAIL state owned positions stay canonical HOLD unless a
    risk-reduction SELL rule fires (weight>=5% or P&L<=-8% or price below
    support); urgent HOLDs present as REVIEW (presentation-only).

    Technical comparisons (support/resistance breach) are ONLY performed when:
    - external_mapping_status == "VERIFIED"
    - broker_quote_currency == external_quote_currency
    - broker_current_price_native is not None
    - external_support_native is not None
    """
    from datetime import date as _d
    if report_date is None:
        try:
            from investment_engine.research.market_data import report_now_bta
            report_date = report_now_bta().date()
        except Exception:
            report_date = _d.today()
    fail = str(recon_status or "").upper() != "PASS"
    items: list[dict] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        disp = str(r.get("display_symbol") or r.get("ticker") or "").strip().upper()
        if not disp or disp == "UNKNOWN":
            continue
        canon_sig = normalize_signal(r.get("signal", "HOLD"))
        entry = (canonical_map or {}).get(disp) if isinstance(canonical_map, dict) else None
        if isinstance(entry, dict) and entry.get("signal") in ("BUY", "SELL", "HOLD"):
            canon_sig = entry["signal"]
        triggers: list[tuple[int, str]] = []
        if canon_sig == "SELL":
            triggers.append((_SCORE_SELL_SIGNAL, "canonical SELL/REDUCE/TRIM signal"))
        try:
            weight = float(r.get("weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight >= 5.0:
            triggers.append((_SCORE_WEIGHT, f"weight {weight:.1f}% ≥ 5%"))
        try:
            pnl = float(r.get("pnl_pct", 0) or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        if pnl <= -8.0 or pnl >= 15.0:
            triggers.append((_SCORE_PNL, f"P&L {pnl:+.1f}% outside −8%/+15% band"))
        rsi = _rsi_of(technicals, disp)
        if rsi is not None and (rsi <= 25 or rsi >= 75):
            triggers.append((_SCORE_RSI, f"RSI {rsi:.1f} extreme"))

        # --- Technical comparison gate ---
        # Only compare if mapping is VERIFIED and currencies match.
        # Pence-scale codes (broker GBX vs Yahoo GBp->GBX) are equivalent:
        # both feeds quote London listings in pence, so natives compare 1:1.
        from investment_engine.portfolio.broker_first import normalize_quote_currency as _norm_ccy
        from investment_engine.portfolio.broker_first import convert_to_eur as _to_eur
        ext_mapping_status = str(r.get("external_mapping_status", r.get("market_data_state", ""))).upper()
        broker_quote_ccy = _norm_ccy(r.get("quote_currency", r.get("broker_quote_currency", "")))
        ext_quote_ccy = _norm_ccy(r.get("external_quote_currency", ""))
        # Get native prices (not EUR-converted)
        broker_price_native = r.get("current_price_native")
        if broker_price_native is None:
            # Fallback: if broker_price_eur and fx_rate available, reverse-calculate
            # But prefer native price field
            pass
        ext_support_native = r.get("support")
        ext_resistance_native = r.get("resistance")
        sup = None
        res = None

        technical_levels_allowed = (
            ext_mapping_status == "VERIFIED"
            and broker_quote_ccy
            and broker_quote_ccy == ext_quote_ccy
            and broker_price_native is not None
            and ext_support_native is not None
        )

        if technical_levels_allowed:
            try:
                px = float(broker_price_native)
                sup = float(ext_support_native) if ext_support_native is not None else None
                res = float(ext_resistance_native) if ext_resistance_native is not None else None

                breached = False
                if sup is not None and px > 0 and px < sup:
                    triggers.append((_SCORE_BREACH, f"stop-loss/invalidation breach: price {px:.2f} {broker_quote_ccy} below support {sup:.2f} {broker_quote_ccy}"))
                    breached = True
                elif res is not None and px > 0 and px > res:
                    triggers.append((_SCORE_BREAKOUT, f"breakout above resistance {res:.2f} {broker_quote_ccy}"))

                for lvl, lname in ((sup, "support"), (res, "resistance")):
                    try:
                        if lvl is not None and px > 0 and not breached and abs(px - lvl) / px <= 0.015:
                            triggers.append((_SCORE_NEAR_LEVEL, f"price within 1.5% of {lname} {lvl:.2f} {broker_quote_ccy}"))
                            break
                    except (TypeError, ValueError, ZeroDivisionError):
                        continue
            except (TypeError, ValueError):
                pass
        else:
            # Technical levels not comparable - add REVIEW_MAPPING flag
            if ext_mapping_status in ("MAPPING_SUSPECT", "UNRESOLVED", "BROKER_ONLY", "NOT_REQUIRED"):
                triggers.append((_SCORE_UNAVAILABLE, f"technical levels suppressed: mapping_status={ext_mapping_status}"))

        delta, earn_date = _days_to_earnings(earnings_status, disp, report_date)
        if delta is not None and 0 <= delta <= 7:
            triggers.append((_SCORE_EARNINGS_7D, f"earnings in {delta}d ({earn_date})"))
        if str(r.get("market_data_state", "") or "").upper() == "UNRESOLVED" and weight >= 2.0:
            triggers.append((_SCORE_UNAVAILABLE, f"market data unavailable (weight {weight:.1f}%)"))
        pie_note = (pie_warnings or {}).get(disp)
        if pie_note:
            triggers.append((_SCORE_PIE_WARNING, str(pie_note)))
        if not triggers:
            continue
        urgency = max(s for s, _ in triggers)
        why = "; ".join(t for _, t in sorted(triggers, key=lambda x: -x[0]))
        # Presentation status.
        # `breached` is only defined when technical_levels_allowed is True
        breached = False  # default
        risk_sell_rule = canon_sig == "SELL" and (weight >= 5.0 or pnl <= -8.0 or breached)
        if canon_sig == "SELL" and (not fail or risk_sell_rule):
            presentation = "SELL"
            action = (f"Risk-reduction review: consider trimming {disp} per stop discipline; "
                      f"no quantity in brief." if not fail else
                      f"Risk-reduction candidate under FAIL: manual review only, no automatic action.")
        elif fail:
            presentation = "REVIEW"
            action = "Review only; no transaction authorized."
        else:
            presentation = "HOLD"
            if canon_sig == "BUY":
                action = "Accumulation candidate — no sized order in this brief."
            else:
                action = "No action; hold position."
        try:
            mval = float(r.get("market_value", 0) or 0)
        except (TypeError, ValueError):
            mval = 0.0
        items.append({
            "display": disp,
            "company": str(r.get("company") or r.get("company_name") or disp),
            "presentation": presentation,
            "canonical": canon_sig,
            "triggers": why,
            "urgency": urgency,
            "market_value": mval,
            "weight": weight,
            "support": sup,
            "resistance": res,
            # EUR-denominated levels for every rendered comparison: prices
            # and P&L in briefs are EUR, so raw natives (USD/DKK/GBX) must
            # never reach the reader. Prefer the row conversion (live FX);
            # fall back to a local static conversion for legacy callers.
            "support_eur": (r.get("support_eur") if r.get("support_eur") is not None
                            else (_to_eur(sup, broker_quote_ccy, {})[0] if sup is not None else None)),
            "resistance_eur": (r.get("resistance_eur") if r.get("resistance_eur") is not None
                               else (_to_eur(res, broker_quote_ccy, {})[0] if res is not None else None)),
            "sr_currency": broker_quote_ccy,
            "earnings_date": earn_date if (delta is not None and 0 <= delta <= 7) else "",
            "action": action,
        })
    items.sort(key=lambda i: (-i["urgency"], -i["market_value"], i["display"]))
    return items


def extract_validated_ideas(
    candidate_section: str | None,
    news_by_symbol: dict | None,
    resolver=None,
) -> list[dict]:
    """Structured watchlist ideas: validated ticker + evidence + source URL.

    A bullet passes with a resolver-verified ticker (supported market data),
    at least one headline evidence with a valid URL, and a stated reason.
    Confidence high with ≥2 evidences, else medium.
    """
    headlines: list[tuple[str, str, str]] = []
    for _sym, entries in (news_by_symbol or {}).items():
        for e in entries or []:
            if isinstance(e, dict) and e.get("title") and e.get("url"):
                headlines.append((str(e["title"]), str(e["url"])))
    found: dict[str, dict] = {}
    for line in (candidate_section or "").splitlines():
        s = line.strip()
        if not s.startswith(("-", "*")):
            continue
        tickers = [t for t in re.findall(r"\b[A-Z]{2,6}\b", s)
                   if t not in ("BUY", "WATCH", "SELL", "HOLD", "THE", "AND", "FOR", "NOT")]
        reason = re.sub(r"^[-*]\s*", "", s)[:200]
        for t in tickers:
            if resolver is not None:
                try:
                    if not resolver(t):
                        continue
                except Exception:
                    continue
            ev = [(title, url) for title, url in headlines if t in title.upper()]
            if not ev:
                continue
            entry = found.setdefault(t, {"evidence": [], "urls": [], "reason": reason})
            for title, url in ev:
                if title not in entry["evidence"]:
                    entry["evidence"].append(title)
                if url not in entry["urls"]:
                    entry["urls"].append(url)
    ideas = []
    for t, info in sorted(found.items()):
        ideas.append({"ticker": t, "reason": info["reason"],
                      "evidence": info["evidence"][0][:140], "url": info["urls"][0],
                      "confidence": "high" if len(info["evidence"]) >= 2 else "medium"})
    return ideas[:5]


def _stance(rows, recon_status: str) -> str:
    if str(recon_status or "").upper() != "PASS":
        return "DEGRADED"
    buys = sum(1 for r in rows or [] if normalize_signal((r or {}).get("signal")) == "BUY")
    sells = sum(1 for r in rows or [] if normalize_signal((r or {}).get("signal")) == "SELL")
    if sells > 0 and sells >= buys:
        return "SELL"
    if buys > sells:
        return "BUY"
    return "HOLD"


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _mday(date_iso: str) -> str:
    """YYYY-MM-DD -> 'MMM DD' without locale dependence."""
    try:
        y, m, d = date_iso[:10].split("-")
        return f"{_MONTHS[int(m) - 1]} {int(d):02d}"
    except (ValueError, TypeError, IndexError):
        return date_iso


def portfolio_stance(rows, recon_status: str) -> str:
    """Single portfolio-stance source of truth (fail-safe: non-PASS → DEGRADED)."""
    return _stance(rows, recon_status)


def _news_assessment(n: dict) -> str:
    links = n.get("links") or []
    q = n.get("link_quality", "unconfirmed")
    if q == "direct":
        return "Directly relevant to held position; verify before action."
    if q == "indirect":
        return "Indirect/sector context only; not direct company evidence."
    if links:
        return "Macro/policy context; no direct holding link."
    return "Unconfirmed relevance; treat as background."


def build_intelligence_brief(result: dict) -> str:
    """Concise human portfolio-intelligence briefing (Phase 4 target brief).

    Deterministic presentation filter over already-computed data. Content rules:
    - max 60 lines; short sections, no per-ticker prose duplication;
    - the account-level warning (FAIL/DEGRADED) appears exactly ONCE;
    - never contains sized orders, prices invented by prose, or trade sizes;
    - models collapsed to one compact line (full attribution lives in the
      manifest + decision-brief methodology section).
    """
    rows = result.get("portfolio_rows", []) or []
    recon = result.get("reconciliation") or {}
    recon_status = str(recon.get("status", "UNKNOWN")).upper()
    regime_result = result.get("regime_result")
    regime = getattr(regime_result, "regime", "UNKNOWN") if regime_result else "UNKNOWN"
    stance = portfolio_stance(rows, recon_status)

    # WP7: Previous run thesis lookup for thesis comparison
    prev_theses: dict[str, str] = {}
    try:
        prev_result = result.get("previous_run") or {}
        for note in (prev_result.get("equity_notes", {}) or {}).get("data", {}).get("notes", []) or []:
            if isinstance(note, dict):
                prev_theses[str(note.get("ticker", "")).upper()] = str(note.get("thesis", "HOLD"))
    except Exception:
        pass

    def _num(value):
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    summary = (result.get("t212_data", {}) or {}).get("account_summary", {}) or {}
    cash = (result.get("t212_data", {}) or {}).get("cash", {}) or {}
    equity = _num(summary.get("total_equity", 0))
    free_cash = _num(cash.get("free", 0))
    perf = result.get("account_performance", {}) or {}
    net_pnl_raw = perf.get("net_pnl_after_costs_eur", None)
    try:
        net_pnl = float(net_pnl_raw) if net_pnl_raw is not None else None
    except (TypeError, ValueError):
        net_pnl = None
    try:
        ret_pct = float(perf.get("return_pct", 0) or 0)
    except (TypeError, ValueError):
        ret_pct = 0.0
    pnl_available = net_pnl is not None
    pnl_line = (f"Net P&L €{net_pnl:+,.2f} ({ret_pct:+.2f}%)"
                if pnl_available else "Net P&L unavailable (no verified deposits baseline)")
    # Fee/interest/tax recording state + cash-flow coverage, when known.
    _pnl_basis = []
    if net_pnl_raw is None and (perf.get("note") or ""):
        pnl_line += f" — {(perf.get('note') or '')[:90]}"
    _cf_status = str(perf.get("net_deposits_status", "") or "").upper()
    if _cf_status == "PARTIAL":
        _pnl_basis.append("cash-flow history: PARTIAL")

    # Phase 1: Run provenance header (run_id, snapshot age, research coverage)
    run_id = str(result.get("run_id", "") or "")
    t212_ts = str((result.get("t212_data", {}) or {}).get("timestamp", "") or "")
    snapshot_age = "unknown"
    if t212_ts:
        try:
            from datetime import datetime as _dt, timezone as _tz
            _ts = _dt.fromisoformat(t212_ts.replace("Z", "+00:00"))
            _age_min = (_dt.now(_tz.utc) - _ts).total_seconds() / 60.0
            snapshot_age = f"{int(_age_min)} min ago" if _age_min < 90 else f"{_age_min / 60.0:.1f}h ago"
        except Exception:
            pass
    corpus_info = result.get("research_corpus", {}) or {}
    corpus_counts = corpus_info.get("counts", {}) or {}
    _corpus_total = corpus_counts.get("total", 0)
    _corpus_decision = corpus_counts.get("decision", 0)
    _selected_news = len(result.get("decision_news", []) or [])
    # Precise counts (WP3): distinguish collected items, fresh decision-tier
    # items, and the items actually selected for analysis. Never present the
    # decision-tier count as "the news shown".
    if _corpus_decision and _selected_news != _corpus_decision:
        research_status = (f"{_corpus_total} items collected, {_corpus_decision} fresh decision-tier, "
                           f"{_selected_news} selected for analysis")
    else:
        research_status = f"{_corpus_total} items, {_corpus_decision} fresh decision-tier"
    brief_generated = str(result.get("brief_generated_at", "") or "")
    header_line = f"Run `{run_id}` | Snapshot: {snapshot_age} | Research: {research_status}"
    if brief_generated:
        header_line += f" | Generated: {brief_generated}"

    # Replace the bare health score rule line with a data-quality status.
    # Deep dive section 1 keeps the score for test compatibility but the
    # intelligence brief never shows a single number for portfolio health.
    lines = [
        "# Portfolio Intelligence Brief",
        "",
        header_line,
        "",
        f"Stance: **{stance}** | Regime: **{regime}** | Reconciliation: **{recon_status}**",
    ]
    for mode_line in (result.get("execution_mode_lines", []) or []):
        lines.append(str(mode_line))
    if recon_status in ("FAIL", "DEGRADED"):
        lines.append("> Account data quality is degraded — deployment withheld; positions individually remain broker data.")
    lines.extend([
        f"Equity: €{equity:,.2f} | {pnl_line} | Free cash: €{free_cash:,.2f}",
        *([f"Note: {'; '.join(_pnl_basis)}"] if _pnl_basis else []),
        "",
        "## Today's plan",
    ])
    _order_plans = result.get("order_plans", {}) or {}
    _plans_now = [p for p in (_order_plans.get("plans", []) or []) if isinstance(p, dict)][:3]
    _blocked_now = [b for b in (_order_plans.get("blocked", []) or []) if isinstance(b, dict)][:3]
    _eval_now = str(_order_plans.get("evaluation_status", "") or "")
    if _plans_now:
        for _p in _plans_now:
            lines.append(f"- NOW: **{_p.get('ticker', '?')}** {_p.get('direction', '')} "
                         f"~€{float(_p.get('indicative_notional_eur', 0) or 0):,.2f} "
                         f"(conditional on manual confirmation)")
    else:
        lines.append("- NOW: no immediately fundable advisory action this run"
                     + (f" ({_eval_now})" if _eval_now else "") + ".")
    if _blocked_now:
        for _b in _blocked_now:
            lines.append(f"- CONDITIONAL: **{_b.get('ticker', '?')}** — {str(_b.get('reason', ''))[:110]}")
    lines.append("- MONITORING: see Priority attention below.")
    lines.append("- RESEARCH-ONLY: see Watchlist below (no deployment).")
    lines.append("")
    lines.append("## Priority attention")
    shown = 0
    for item in (result.get("monitoring_items", []) or []):
        if shown >= 5:
            break
        if not isinstance(item, dict):
            continue
        disp = str(item.get("display", "")).strip().upper()
        pres = str(item.get("presentation", item.get("action", ""))).strip()
        trig = str(item.get("triggers", "") or "").strip()
        try:
            _w = float(item.get("weight", 0) or 0)
            wtxt = f"; {_w:.1f}% weight"
        except (TypeError, ValueError):
            wtxt = ""
        if disp and pres:
            why = f" — {trig[:130]}" if trig else ""
            hold_note = ""
            if str(pres).strip().upper() == "HOLD":
                # WP7: thesis comparison only when previous thesis exists
                prev_thesis = prev_theses.get(disp) if 'prev_theses' in locals() else None
                if prev_thesis and str(prev_thesis) == str(pres):
                    hold_note = " — HOLD: thesis CONFIRMED; no add proposed; reassess on material change"
                elif prev_thesis:
                    hold_note = f" — HOLD: thesis CHANGED ({prev_thesis} → {pres}); reassess on material change"
                else:
                    hold_note = " — HOLD: thesis UNASSESSED; no add proposed; reassess on material change"
            lines.append(f"- **{disp}** — {pres[:100]}{why}{wtxt}{hold_note}")
            shown += 1
    if not shown:
        lines.append("No positions require attention this run.")
    lines.append("")
    lines.append("## News & earnings")
    research_note = str(result.get("research_note", "") or "")
    if research_note:
        lines.append(research_note)
    news_items = result.get("decision_news", []) or []
    if news_items:
        for item in news_items[:3]:
            if isinstance(item, dict):
                title = str(item.get('title', ''))[:110]
                url = str(item.get('url', '') or '')
                source = str(item.get('source', '') or '')
                pub_time = str(item.get('published', '') or item.get('published_at_utc', '') or '')
                # Build clickable title if URL is valid
                if url and url.startswith('http'):
                    title_md = f"[{title}]({url})"
                else:
                    title_md = title
                # Timestamps are UTC with explicit label (never bare local time).
                meta_parts = []
                if source:
                    meta_parts.append(source)
                if pub_time:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        _ts = _dt.fromisoformat(pub_time.replace('Z', '+00:00'))
                        if _ts.tzinfo is None:
                            _ts = _ts.replace(tzinfo=_tz.utc)
                        meta_parts.append(_ts.astimezone(_tz.utc).strftime('%Y-%m-%d %H:%M UTC'))
                    except Exception:
                        meta_parts.append((pub_time[:16] + " (tz unknown)").strip())
                meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
                lines.append(f"- {title_md}{meta}")
                # Pipeline-provided relevance (why/links) when present; otherwise
                # mark the link as unconfirmed context, never as evidence.
                _why = str(item.get('why', '') or '').strip()
                _links = item.get('links', []) if isinstance(item.get('links'), list) else []
                if _why:
                    lines.append(f"  Relevance: {_why[:200]}"
                                 + (f" [linked: {', '.join(str(x) for x in _links[:4])}]" if _links else ""))
                else:
                    _tags = [str(t) for t in (item.get('ticker_tags') or []) if t]
                    if _tags:
                        lines.append(f"  Relevance: tagged [{', '.join(_tags[:3])}] — unconfirmed link, treat as context")
                    else:
                        lines.append("  Relevance: unconfirmed link to holdings — context only, not evidence")
    else:
        lines.append("No decision-relevant news in the last 48 hours.")
    earnings = (result.get("earnings_7d", {}) or {}).get("in_window", []) or []
    if earnings:
        for ev in earnings[:5]:
            if isinstance(ev, dict):
                tag = "(confirmed)" if ev.get("status") == "confirmed" else "(estimated)"
                lines.append(f"- {ev.get('display', '')}: earnings {tag}")
    else:
        lines.append("No upcoming earnings within 7 days.")

    # WP7: Domain sections
    # Trump/Policy
    policy_events = result.get("policy_events", []) or []
    if policy_events:
        lines.append("")
        lines.append("## Trump / Policy")
        for ev in policy_events[:5]:
            if isinstance(ev, dict):
                topic = str(ev.get("topic", "")).upper()
                actors = ", ".join(ev.get("actors", [])) or "unattributed"
                stages = ", ".join(ev.get("stages", [])) or "mentioned"
                sectors = ", ".join(ev.get("sectors", [])) or "sector unspecified"
                lines.append(f"- **{topic}** ({stages}): {actors} — sectors: {sectors}")
    else:
        lines.append("")
        lines.append("## Trump / Policy")
        lines.append("No policy events extracted this run.")

    # Energy/Commodities
    energy_snapshot = result.get("energy_snapshot", {}) or {}
    benchmarks = energy_snapshot.get("benchmarks", {}) or {}
    if benchmarks:
        lines.append("")
        lines.append("## Energy / Commodities")
        for sym, data in list(benchmarks.items())[:5]:
            if isinstance(data, dict) and "price" in data:
                label = str(data.get("label", sym))
                price = data.get("price")
                currency = data.get("currency", "USD")
                unit = data.get("unit", "")
                lines.append(f"- **{label}**: {price} {currency}/{unit} ({data.get('as_of', 'n/a')})")
            elif isinstance(data, dict) and "error" in data:
                lines.append(f"- {sym}: {data['error']}")
    else:
        lines.append("")
        lines.append("## Energy / Commodities")
        lines.append("No benchmark prices available this run.")

    # Healthcare/FDA
    healthcare_events = result.get("healthcare_events", []) or []
    if healthcare_events:
        lines.append("")
        lines.append("## Healthcare / FDA")
        for ev in healthcare_events[:5]:
            if isinstance(ev, dict):
                subtypes = ", ".join(ev.get("subtypes", [])) or "healthcare"
                phase = f" (Phase {ev['phase']})" if ev.get("phase") else ""
                endpoint = f", endpoint: {ev['endpoint']}" if ev.get("endpoint") else ""
                lines.append(f"- **{ev.get('symbol', '?')}** [{subtypes}{phase}{endpoint}]: {ev.get('source', '')} — {ev.get('url', '')}")
    else:
        lines.append("")
        lines.append("## Healthcare / FDA")
        lines.append("No healthcare events extracted this run.")

    # Crypto
    crypto_events = result.get("crypto_events", []) or []
    if crypto_events:
        lines.append("")
        lines.append("## Crypto")
        for ev in crypto_events[:5]:
            if isinstance(ev, dict):
                subtype = ev.get("subtype", "crypto")
                symbols = ", ".join(ev.get("symbols", [])) or "general"
                lines.append(f"- **{subtype}** ({symbols}): {ev.get('source', '')} — {ev.get('url', '')}")
    else:
        lines.append("")
        lines.append("## Crypto")
        lines.append("No crypto events extracted this run.")

    # Social platforms
    social_status = result.get("social_platform_status", []) or []
    if social_status:
        lines.append("")
        lines.append("## Social Platforms")
        for sp in social_status:
            platform = str(sp.get("platform", ""))
            status = str(sp.get("status", "NOT_ATTEMPTED"))
            items = sp.get("items_collected", 0)
            error = sp.get("error", "")
            note = f" — {error}" if error else ""
            lines.append(f"- **{platform}**: {status} ({items} items){note}")
    else:
        lines.append("")
        lines.append("## Social Platforms")
        lines.append("No platform status recorded this run.")

    ideas = result.get("ideas", []) or []
    if ideas:
        lines.append("")
        lines.append("## Watchlist")
        for idea in ideas[:3]:
            if isinstance(idea, dict):
                lines.append(f"- **{idea.get('ticker', '')}** — {str(idea.get('reason', ''))[:120]}")
    stages = result.get("providers_per_stage") or {}
    if stages:
        try:
            from investment_engine.providers.attribution import format_stage_line as _fmt_stage
        except Exception:
            _fmt_stage = None
        if _fmt_stage is not None:
            winners = [_fmt_stage(s, st) for s, st in sorted(stages.items())]
        else:
            winners = [f"{s}={(st or {}).get('provider', '?')}" for s, st in sorted(stages.items())]
        # One bullet per stage (not a single 300+ char line): some formatted
        # Markdown views choke on very long lines and warn about
        # "unsupported syntax" when opening the generated brief.
        lines.extend(["", "Models (per stage):"])
        lines.extend(f"- {w}" for w in winners if str(w).strip())
    # When research is empty the brief still answers "what moves this":
    # top weights + regime + recon + data provenance (never invented).
    if not news_items and not earnings and not ideas:
        lines.extend(["", "## Portfolio drivers (no fresh catalysts)"])
        _top = sorted(((float(r.get("weight", 0) or 0) if isinstance(r, dict) else 0,
                        str(r.get("display_symbol") or r.get("ticker") or "?") if isinstance(r, dict) else "?")
                       for r in rows), reverse=True)[:3]
        if _top and _top[0][0] > 0:
            lines.append("- Largest weights: " + ", ".join(f"{d} {w:.1f}%" for w, d in _top) + ".")
        try:
            _delta = float(recon.get("cash_delta", recon.get("reconciliation_delta_eur", 0)) or 0)
        except (TypeError, ValueError):
            _delta = 0.0
        lines.append(f"- Regime {regime}, reconciliation {recon_status} (Δ €{_delta:+.2f}).")
        t212 = result.get("t212_data", {}) or {}
        _fx_src = ((t212.get("fx_rates_used", {}) or {}).get("source", "") or "broker")
        lines.append(f"- Prices/P&L: broker truth; FX: {_fx_src}; "
                     f"free cash €{free_cash:,.2f}.")
    # Phase 3: Explicit status section (replaces misleading health score).
    # Stage counts come from actual execution records (stage_origin), never
    # from "everything not deterministic is LLM" heuristics — unknown records
    # must not inflate the LLM count.
    try:
        from investment_engine.providers.attribution import stage_origin as _stage_origin
    except Exception:
        _stage_origin = None
    def _classify_stage(rec):
        if not isinstance(rec, dict):
            return "unknown"
        if str(rec.get("execution_type", "")).upper() == "LLM":
            return "llm"
        if str(rec.get("execution_type", "")).upper() in ("DETERMINISTIC", "FALLBACK"):
            return "deterministic"
        if _stage_origin is None:
            return "unknown"
        origin = _stage_origin(rec.get("provider"))
        if origin in ("local", "API"):
            return "llm" if not str(rec.get("error_class", "")) else "failed"
        if origin == "Python":
            return "deterministic"
        return "unknown"
    _stage_classes = [_classify_stage(s) for s in stages.values()]
    _n_llm = sum(1 for c in _stage_classes if c == "llm")
    _n_det = sum(1 for c in _stage_classes if c == "deterministic")
    _n_unk = sum(1 for c in _stage_classes if c in ("unknown", "failed"))
    _ai_line = f"- AI processing: {_n_llm} LLM stages, {_n_det} deterministic"
    if _n_unk:
        _ai_line += f", {_n_unk} unknown/unrecorded"
    lines.extend(["", "## Status"])
    lines.extend([
        f"- Broker data: {'available' if t212_ts else 'unavailable'}",
        f"- Accounting audit: {recon_status}",
        f"- Research coverage: {research_status}",
        _ai_line,
    ])
    # Advisory eligibility: detailed breakdown from the risk engine result.
    # evaluation_status distinguishes NO_CANDIDATES_PRODUCED (nothing entered
    # planning) from UPSTREAM_SKILL_FAILURE (committee skill failed) from
    # ALL_BLOCKED (candidates evaluated, none passed gates).
    policy_info = result.get("investment_policy", {}) or {}
    policy_status = policy_info.get("status", "NOT SET")
    order_plans = result.get("order_plans", {}) or {}
    plans = order_plans.get("plans", []) or []
    blocked = order_plans.get("blocked", []) or []
    _eval_status = str(order_plans.get("evaluation_status", "") or "")
    if not _eval_status:
        if plans or blocked:
            _eval_status = "PLANS_GENERATED" if plans else "ALL_BLOCKED"
        elif policy_status != "OK":
            _eval_status = "POLICY_NOT_SET"
        else:
            _eval_status = "NOT_EVALUATED"
    lines.extend([
        f"- Advisory eligibility: {policy_status}",
        f"  - Policy valid: {'yes' if policy_status == 'OK' else 'no'}",
        f"  - Planning enabled: {'yes' if policy_status == 'OK' else 'no'}",
        f"  - Evaluation: {_eval_status}",
        f"  - Candidates evaluated: {len(plans) + len(blocked)}",
        f"  - Plans generated: {len(plans)}",
        f"  - Blocked candidates: {len(blocked)}",
    ])
    if blocked:
        _reasons = list({str(b.get("reason", "")) for b in blocked if b.get("reason")})
        if _reasons:
            lines.append(f"  - Primary reasons: {'; '.join(_reasons[:3])}")
    # Active policy profile: which sleeves may be added to / sold at all.
    try:
        from investment_engine.risk.profiles import describe_line as _profile_line
        _profile = policy_info.get("profile") if isinstance(policy_info, dict) else None
        if isinstance(_profile, dict) and _profile.get("name"):
            lines.append(f"- {_profile_line(_profile)}")
    except Exception:
        pass
    # Concentration snapshot: effective holdings, top weights, small positions,
    # FX exposure by native quote currency. Pure arithmetic over broker rows.
    try:
        _wts = []
        _fx: dict[str, dict] = {}
        _small_n, _small_w = 0, 0.0
        _top: list[tuple[float, str]] = []
        for _r in (rows or []):
            if not isinstance(_r, dict):
                continue
            try:
                _w = float(_r.get("weight", 0) or 0.0)
            except (TypeError, ValueError):
                continue
            if _w <= 0:
                continue
            _d = str(_r.get("display_symbol") or _r.get("ticker") or "?")
            _wts.append(_w / 100.0)
            _top.append((_w, _d))
            if _w < 1.0:
                _small_n += 1
                _small_w += _w
            _ccy = str(_r.get("quote_currency", "") or "UNKNOWN").upper()
            _bucket = _fx.setdefault(_ccy, {"weight": 0.0, "count": 0})
            _bucket["weight"] = round(_bucket["weight"] + _w, 2)
            _bucket["count"] += 1
        if _wts:
            import math as _math
            _eff_n = round(1.0 / sum(w * w for w in _wts), 1) if sum(_wts) > 0 else 0.0
            _top_sorted = sorted(_top, reverse=True)[:5]
            lines.extend(["", "## Concentration"])
            lines.append(f"- Effective holdings: {_eff_n} (of {len(_wts)} positions)")
            lines.append("- Top weights: " + ", ".join(f"{d} {w:.1f}%" for w, d in _top_sorted))
            if _small_n:
                lines.append(f"- Small positions (<1%): {_small_n}, combined {_small_w:.1f}% weight")
            if _fx:
                _fx_txt = ", ".join(f"{c}: {v['weight']:.1f}% ({v['count']})"
                                    for c, v in sorted(_fx.items(), key=lambda kv: -kv[1]["weight"])[:6])
                lines.append(f"- FX exposure by quote currency: {_fx_txt}")
    except Exception:
        pass
    # Changes since previous run (if available)
    prev_run = result.get("previous_run", {}) or {}
    if prev_run:
        lines.extend(["", "## Changes since previous run"])
        _prev_stance = prev_run.get("stance", "unknown")
        _curr_stance = stance
        if _prev_stance != _curr_stance:
            lines.append(f"- Stance: {_prev_stance} → {_curr_stance}")
        _prev_signals = prev_run.get("signals", {}) or {}
        _curr_signals = {str(r.get("display_symbol") or r.get("ticker")): str(r.get("signal", ""))
                         for r in rows if isinstance(r, dict)}
        _changed = []
        for _t, _s in _curr_signals.items():
            _ps = _prev_signals.get(_t)
            if _ps and _ps != _s:
                _changed.append(f"{_t}: {_ps} → {_s}")
        if _changed:
            lines.append(f"- Signal changes: {'; '.join(_changed[:5])}")
        else:
            lines.append("- Signal changes: none detected")
        _prev_news = prev_run.get("news_count", 0)
        _curr_news = len(news_items)
        if _prev_news != _curr_news:
            lines.append(f"- News items: {_prev_news} → {_curr_news}")
        lines.append("- Causal attribution: " + ("available" if _changed else "unavailable"))
    lines.extend([
        "",
        "Details: t212_portfolio_snapshot.md (full broker-first positions) + "
        "portfolio_deep_dive.md (15-section analysis).",
    ])
    brief = "\n".join(lines)
    if len(brief.splitlines()) > 60:
        brief = "\n".join(brief.splitlines()[:60])
    return brief


def _perf_eur(value: Any) -> str:
    if value is None:
        return "Unavailable"
    try:
        return f"€{float(value):+,.2f}"
    except (TypeError, ValueError):
        return "Unavailable"


def _perf_pct(value: Any) -> str:
    if value is None:
        return "Unavailable"
    try:
        return f"{float(value):+.4f}%"
    except (TypeError, ValueError):
        return "Unavailable"


def _perf_alloc(value: Any) -> str:
    if value is None:
        return "Unavailable"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "Unavailable"


def render_brief(
    *,
    generated_at: str,
    regime_result,
    recon: dict,
    rows: list[dict],
    monitoring_items: list[dict],
    earnings_7d: dict,
    decision_news: list[dict],
    ideas: list[dict],
    cash_line: str,
    catalyst_radar: list[dict] | None = None,
    performance: dict | None = None,
    research_note: str = "",
    execution_mode_lines: list[str] | None = None,
    order_plans: dict | None = None,
    summary: str = "",
) -> str:
    """Render the concise decision-first brief (exact section order).

    Optional research_note renders in the news section (coverage warning);
    optional execution_mode_lines render under the header (API-only mode).
    Both default to absent so existing callers are byte-identical.
    """
    from investment_engine.accounting.cashflows import FAIL_PERFORMANCE_NOTE
    status = recon.get("status", "UNKNOWN")
    regime = getattr(regime_result, "regime", "UNKNOWN") if regime_result is not None else "UNKNOWN"
    try:
        rsi = regime_result.timeframes.get("daily", {}).get("indicators", {}).get("RSI_14", 0)
        regime_line = f"{regime} (RSI {float(rsi):.0f})"
    except Exception:
        regime_line = str(regime)
    if status == "FAIL":
        quality = (f"Data quality: **{status}** — account totals withheld; "
                   f"{len(rows or [])} validated positions shown.")
        constraint = "Reconciliation FAIL blocks all deployment and new buys."
    else:
        quality = (f"Data quality: **{status}** — reconciled; {len(rows or [])} positions.")
        top_w = max([float((r or {}).get("weight", 0) or 0) for r in (rows or [])] or [0.0])
        constraint = ("Single-name concentration caps new adds." if top_w >= 7.0
                      else "No binding constraint; normal sizing rules apply.")
    perf = performance or {}
    perf_ok = perf.get("performance_status") == "Available"
    lines = [
        "# Portfolio Decision Brief", "",
        f"Generated: {generated_at}",
    ]
    for mode_line in (execution_mode_lines or []):
        lines.append(str(mode_line))
    lines += [
        quality, "",
        "## Executive Decision", "",
        f"- Portfolio stance: **{_stance(rows, status)}**",
        f"- Market regime: **{regime_line}**",
        f"- Account reconciliation: **{status}**",
        f"- Broker total equity: {_feur(perf.get('broker_total_equity_eur', (recon or {}).get('total_equity')))}",
        f"- Net deposits: {_feur(perf.get('net_deposits_eur'))} "
        f"({perf.get('net_deposits_source', 'Unavailable — no verified cash-flow source')} / "
        f"{perf.get('net_deposits_status', 'UNAVAILABLE')})",
        f"- Net P&L after costs: {_perf_eur(perf.get('net_pnl_after_costs_eur')) if perf_ok else 'Unavailable'}",
        f"- Return on net deposits: {_perf_pct(perf.get('return_pct')) if perf_ok else 'Unavailable'}",
        f"- Reported free cash: {_feur(perf.get('reported_free_cash_eur'))}",
        f"- Total reported cash: {_feur(perf.get('reported_cash_eur'))}",
        f"- Cash allocation: {_perf_alloc(perf.get('cash_allocation_pct'))}",
        f"- Cash/deployment: {cash_line}",
        f"- Key safety constraint: {constraint}",
    ]
    # Active strategy profile: what the engine may propose under it.
    try:
        from investment_engine.risk.profiles import describe_line as _profile_line
        _profile = (order_plans or {}).get("policy_profile") if isinstance(order_plans, dict) else None
        if isinstance(_profile, dict) and _profile.get("name"):
            lines.append(f"- {_profile_line(_profile)}")
    except Exception:
        pass
    if status == "FAIL":
        lines += ["", f"> {FAIL_PERFORMANCE_NOTE}"]
    if summary:
        block = str(summary).strip()
        if block and not block.startswith("## "):
            block = "## Summary\n" + block
        if block:
            lines += ["", block]
    lines += ["", "## Portfolio Monitoring", ""]
    if not monitoring_items:
        lines.append("No owned positions meet urgency criteria.")
    for it in monitoring_items:
        lines.append(f"- **{it['display']}**, {it['company']} — **{it['presentation']}** "
                     f"(canonical {it['canonical']}) — {it['triggers']}.")
        sr = []
        if _eur_level(it, "support") is not None:
            sr.append(f"support {_fnum(_eur_level(it, 'support'))}")
        if _eur_level(it, "resistance") is not None:
            sr.append(f"resistance {_fnum(_eur_level(it, 'resistance'))}")
        if sr:
            lines.append(f"  - Levels: {' / '.join(sr)}.")
        if it.get("earnings_date"):
            lines.append(f"  - Earnings: {it['earnings_date']} (within 7 days).")
        lines.append(f"  - Action: {it['action']}")
    lines += ["", "## Earnings — Next 7 Days", ""]
    window = (earnings_7d or {}).get("in_window", []) if isinstance(earnings_7d, dict) else []
    if not window:
        lines.append("No relevant earnings events in the next 7 days.")
    else:
        for ev in window:
            tag = "(confirmed)" if ev.get("status") == "confirmed" else "(estimated)"
            lines.append(f"- {_mday(ev['date'])} — {ev['display']}, {ev['company']} — earnings {tag}")
    nxt = (earnings_7d or {}).get("next_after") if isinstance(earnings_7d, dict) else None
    if isinstance(nxt, dict) and nxt.get("date"):
        tag = "(confirmed)" if nxt.get("status") == "confirmed" else "(estimated)"
        lines.append(f"Next relevant earnings after this window: {_mday(nxt['date'])} — "
                     f"{nxt['display']}, {nxt['company']} — earnings {tag}.")
    lines += ["", "## Catalyst Radar — Dated events from linked news", ""]
    if not catalyst_radar:
        lines.append("No dated catalysts found in linked news.")
    else:
        for ev in catalyst_radar or []:
            if not isinstance(ev, dict):
                continue
            lines.append(f"- {_mday(str(ev.get('date', '')))} — {ev.get('ticker', '?')} — "
                         f"{ev.get('title', '')} ({ev.get('url', '')})")
    lines += ["", "## Decision-Relevant News — Last 48 Hours", ""]
    if research_note:
        lines.append(str(research_note))
    if not decision_news:
        if not research_note:
            lines.append("No decision-relevant verified news in the last 48 hours.")
    else:
        for n in decision_news:
            lines.append(f"- [{n['title']}]({n['url']}) — {n['source']} · {n.get('published', '')} ({n.get('age', '')})")
            lines.append(f"  - What happened: {n.get('title', '')}")
            lines.append(f"  - Portfolio relevance: {n.get('why', '') or 'unconfirmed link — context only'}")
            lines.append(f"  - Assessment: {_news_assessment(n)}")
            _lq = n.get('link_quality', 'unconfirmed')
            if _lq and _lq != 'direct':
                lines.append(f"  - Link quality: {_lq}")
    lines += ["", "## Watchlist Candidates", ""]
    if status == "FAIL":
        lines.append("> Research-only watchlist; no deployment is authorized while account reconciliation is failing.")
        lines.append("")
    if not ideas:
        lines.append("No new ideas met the current evidence and validation threshold.")
    else:
        for idea in ideas:
            lines.append(f"- **{idea['ticker']}** — WATCH — {idea['reason']}")
            lines.append(f"  - Evidence: {idea['evidence']} ({idea['url']}) [confidence: {idea['confidence']}]")
    # Advisory order plans: rendered ONLY when gated plans exist (policy set +
    # all gates passed). Always advisory-only, never executable.
    _plans = (order_plans or {}).get("plans", []) or [] if isinstance(order_plans, dict) else []
    if _plans and str(status or "").upper() != "FAIL":
        lines += ["", "## Advisory Order Plans (not executed)", "",
                  "> Advisory only — not executed. Confirm manually outside this program.", ""]
        for plan in _plans:
            if not isinstance(plan, dict):
                continue
            lines.append(
                f"- **{plan.get('ticker')}** {plan.get('direction')} "
                f"~€{float(plan.get('indicative_notional_eur', 0) or 0):,.2f} "
                f"(binding: {plan.get('binding_constraint')}, sleeve: {plan.get('sleeve')})")
    return "\n".join(lines).rstrip() + "\n"


def _group_rows_by_isin(rows: list[dict] | None) -> list[tuple[str, dict, list[dict]]]:
    """Group unified rows by ISIN (fallback: broker internal ID).

    Returns [(group_key, primary_row, lot_rows)] with groups sorted by market
    value descending. The primary row is the highest-value lot; aggregates
    (qty/value/P&L/weight) are exact sums. Rows without ISIN never merge.
    Deterministic, pure, no network.
    """
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []

    def _num(value):
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    for r in rows or []:
        if not isinstance(r, dict):
            continue
        isin = str(r.get("isin") or "").strip().upper()
        if isin:
            key = ("ISIN", isin)
        else:
            key = ("ID", str(r.get("internal_id") or r.get("display_symbol") or r.get("ticker") or "?"))
        if key not in groups:
            groups[key] = {"rows": [], "value": 0.0}
            order.append(key)
        groups[key]["rows"].append(r)
        groups[key]["value"] += _num(r.get("market_value"))

    out: list[tuple[str, dict, list[dict]]] = []
    for key in sorted(order, key=lambda k: groups[k]["value"], reverse=True):
        lots = sorted(groups[key]["rows"],
                      key=lambda r: _num(r.get("market_value")), reverse=True)
        if len(lots) > 1:
            # Same ISIN = same company: backfill lots whose name resolution
            # missed (e.g. EUR-duplicate displays absent from name maps).
            _best_company = next(
                (str(r.get("company") or "").strip() for r in lots
                 if str(r.get("company") or "").strip()
                 and str(r.get("company")).strip().lower() not in ("unknown instrument",)),
                "")
            if _best_company:
                lots = [dict(r) if str(r.get("company") or "").strip() not in ("", "Unknown instrument")
                        else dict(r, company=_best_company) for r in lots]
        primary = dict(lots[0])
        if len(lots) > 1:
            primary = dict(primary)
            primary["quantity"] = sum(_num(r.get("quantity")) for r in lots)
            primary["market_value"] = sum(_num(r.get("market_value")) for r in lots)
            primary["unrealized_pnl"] = sum(_num(r.get("unrealized_pnl")) for r in lots)
            primary["realized_pnl"] = (sum(_num(r.get("realized_pnl")) for r in lots)
                                       if any(isinstance(r.get("realized_pnl"), (int, float)) for r in lots)
                                       else None)
            primary["total_pnl"] = sum(_num(r.get("total_pnl")) for r in lots)
            primary["weight"] = sum(_num(r.get("weight")) for r in lots)
            cost = sum(_num(r.get("quantity")) * _num(r.get("avg_cost")) for r in lots)
            qty = sum(_num(r.get("quantity")) for r in lots)
            primary["avg_cost"] = (cost / qty) if qty else 0.0
            primary["pnl_pct"] = (primary["total_pnl"] / cost * 100.0) if cost else primary.get("pnl_pct", 0)
            others = sorted({str(r.get("display_symbol") or r.get("ticker")) for r in lots[1:]})
            note = str(primary.get("notes") or "")
            extra = f"same ISIN as {', '.join(others)} (separate listings/lots)"
            primary["notes"] = (note + "; " + extra).strip("; ") if note else extra
        out.append((key[1], primary, lots))
    return out


def _snapshot_row_lines(r: dict, monitoring_by_display: dict | None,
                      note_marker: str | None = None) -> list[str]:
    """Render one holdings-table row. Pure helper shared by group/lot rows.

    ``note_marker`` (e.g. "[3]") replaces the free-text Notes cell: long
    sentences inside a 19-column table break formatted Markdown views
    ("unsupported syntax" warnings) — the full text lives in the numbered
    notes list below the table instead.
    """
    if r.get("pnl_validated", True):
        unreal_s = _feur(r.get("unrealized_pnl"))
        total_s = _feur(r.get("total_pnl"))
        try:
            pct_s = f"{float(r.get('pnl_pct', 0) or 0):+.1f}%"
        except (TypeError, ValueError):
            pct_s = "n/a"
    else:
        unreal_s = total_s = pct_s = "n/a"
    mon = (monitoring_by_display or {}).get(
        str(r.get("display_symbol") or r.get("ticker") or "").strip().upper(), "HOLD")
    # Lot identity: same display can be several broker lots/ISINs (e.g. AAPL
    # AAPL_US_EQ + APCd_EQ). internal_id disambiguates the rows.
    lot = str(r.get("internal_id") or "").strip()
    notes_cell = note_marker if note_marker else (r.get("notes") or "—")
    return [
        f"| {r.get('display_symbol') or r.get('ticker')} | {lot or '—'} | {r.get('company')} | "
        f"{float(r.get('quantity', 0) or 0):.4f} | {_feur(r.get('avg_cost'))} | {_feur(r.get('current_price'))} | "
        f"{_feur(r.get('market_value'))} | {unreal_s} | {_feur(r.get('realized_pnl'))} | {total_s} | "
        f"{pct_s} | {float(r.get('weight', 0) or 0):.2f}% | {signal_emoji(r.get('signal', 'HOLD'))} | {mon} | "
        f"{_fnum(_eur_level(r, 'support'))} | {_fnum(_eur_level(r, 'resistance'))} | "
        f"{r.get('market_data_state', 'n/a')} | {notes_cell} |"
    ]


def render_snapshot(
    *,
    generated_at: str,
    recon: dict,
    cash: dict,
    rows: list[dict],
    monitoring_by_display: dict,
    earnings_status: dict | None,
    t212_data: dict | None = None,
    performance: dict | None = None,
    ledger_metadata: dict | None = None,
) -> str:
    """Render the complete Trading212 financial snapshot."""
    from investment_engine.accounting.cashflows import FAIL_PERFORMANCE_NOTE
    status = recon.get("status", "UNKNOWN")
    perf = performance or {}
    perf_ok = perf.get("performance_status") == "Available"

    def _pval(key: str) -> str:
        return _feur(perf.get(key)) if perf_ok or perf.get(key) is not None else "Unavailable"

    lines = [
        "# T212 Portfolio Snapshot", "",
        f"Generated: {generated_at}",
        f"Data quality / reconciliation: **{status}**",
        "",
        "## Account Status", "",
        "### Broker Account Performance",
        "| Metric | Value |",
        "|---|---:|",
        f"| Broker total equity | {_feur(perf.get('broker_total_equity_eur', (recon or {}).get('total_equity')))} |",
        f"| Net deposits | {_pval('net_deposits_eur')} |",
        f"| Net deposits source | {perf.get('net_deposits_source', 'Unavailable — no verified cash-flow source')} |",
        f"| Net P&L after costs | {_perf_eur(perf.get('net_pnl_after_costs_eur')) if perf_ok else 'Unavailable'} |",
        f"| Return on net deposits | {_perf_pct(perf.get('return_pct')) if perf_ok else 'Unavailable'} |",
        f"| Reported free cash | {_feur(perf.get('reported_free_cash_eur'))} |",
        f"| Pie cash | {_feur(perf.get('pie_cash_eur'))} |",
        f"| Reported cash total | {_feur(perf.get('reported_cash_eur'))} |",
        f"| Cash allocation | {_perf_alloc(perf.get('cash_allocation_pct'))} |",
        f"| Fees recorded | {_feur(perf.get('fees_eur')) if perf.get('fees_eur') is not None else 'n/a (display only)'} |",
        f"| Interest recorded | {_feur(perf.get('interest_eur')) if perf.get('interest_eur') is not None else 'n/a (display only)'} |",
        f"| Tax recorded | {_feur(perf.get('tax_eur')) if perf.get('tax_eur') is not None else 'n/a (display only)'} |",
        "",
        "### Position Reconciliation",
        "| Metric | Value |",
        "|---|---:|",
        f"| Authoritative positions value | {_feur(recon.get('positions_value'))} |",
        f"| Implied cash from broker equity | {_feur(recon.get('implied_cash'))} |",
        f"| Reported cash | {_feur(recon.get('reported_cash'))} |",
        f"| Reconciliation delta | {_feur(recon.get('cash_delta'))} |",
        f"| Reconciliation threshold | {_feur(recon.get('threshold'))} |",
        f"| Reconciliation status | **{status}** |",
    ]
    if status == "FAIL":
        lines += ["",
                  "> Reconciliation check failed — derived account totals withheld. "
                  "No cause is asserted.",
                  "",
                  f"> {FAIL_PERFORMANCE_NOTE}"]
    lines += ["", "## Holdings", ""]
    if not rows:
        lines.append("No positions to display.")
    else:
        lines.append("| Ticker | Lot / Broker ID | Company | Qty | Avg Cost | Current Price | Market Value | "
                     "Unrealized P&L | Realized P&L | Total P&L | P&L % | Weight | "
                     "Canonical Signal | Monitoring Status | Support (€) | Resistance (€) | Market Data Status | Notes |")
        lines.append("|--------|---------------|---------|-----|----------|---------------|--------------|----------------|--------------|-----------|-------|--------|"
                     "----------------|-------------------|---------|------------|--------------------|-------|")
        _notes: list[str] = []

        def _emit_row(_rdict: dict, _lot_prefix: str = "") -> None:
            _txt = str(_rdict.get("notes") or "").strip()
            _marker = ""
            if _txt and _txt != "—":
                _notes.append(f"{str(_rdict.get('display_symbol') or _rdict.get('ticker'))}: {_txt}")
                _marker = f"[{len(_notes)}]"
            for _line in _snapshot_row_lines(_rdict, monitoring_by_display,
                                             note_marker=_marker or None):
                lines.append((_lot_prefix + _line[len("| "):]) if _lot_prefix else _line)

        for _group_key, _primary, _lots in _group_rows_by_isin(rows):
            _emit_row(_primary)
            if len(_lots) > 1:
                for _lot in _lots:
                    _emit_row(_lot, _lot_prefix="| ↳ ")
        if _notes:
            lines += ["", "**Holding notes:**"]
            lines.extend(f"- [{i}] {_t}" for i, _t in enumerate(_notes, 1))
    lines += ["", "## Data Coverage", ""]
    unmapped = sorted({str(r.get("display_symbol") or r.get("ticker"))
                       for r in (rows or [])
                       if str(r.get("market_data_state", "") or "").upper() == "UNRESOLVED"})
    lines.append("- Instruments without market-data mapping: " + (", ".join(unmapped) if unmapped else "none."))
    broker_only = sorted({str(r.get("display_symbol") or r.get("ticker"))
                          for r in (rows or [])
                          if str(r.get("market_data_state", "") or "").upper() == "BROKER_ONLY"})
    lines.append("- Broker-only positions (no Yahoo mapping by design — e.g. CFDs/pie slices like APCd; "
                 "broker values authoritative, excluded from external technicals): " +
                 (", ".join(broker_only) if broker_only else "none."))
    no_earn: list[str] = []
    for r in rows or []:
        disp = str(r.get("display_symbol") or r.get("ticker") or "").strip().upper()
        val = (earnings_status or {}).get(disp)
        dated = (isinstance(val, (tuple, list)) and len(val) > 0
                 and isinstance(val[0], str) and len(val[0]) >= 10)
        if not dated:
            no_earn.append(disp)
    lines.append("- Earnings unavailable (actual holdings): " + (", ".join(sorted(set(no_earn))) if no_earn else "none."))
    lines.append("- Realized P&L: unavailable — transaction ledger not imported (shows n/a).")
    led = ledger_metadata or {}
    lines.append("- Cash-flow source: " + str(led.get("selected_source", (perf or {}).get(
        "net_deposits_source", "Unavailable — no verified cash-flow source")))
        + f" ({led.get('selected_status', (perf or {}).get('net_deposits_status', 'UNAVAILABLE'))}).")
    if led.get("selected_status") == "VERIFIED":
        lines.append(f"- Historical FX conversion: complete ({led.get('api_items', 0)} API items, "
                     f"{led.get('api_unresolved_fx', 0)} unresolved).")
    else:
        lines.append("- Historical FX conversion: manual EUR baseline — no per-item conversion required.")
    lines.append(f"- Reconciliation: positions {_feur(recon.get('positions_value'))} + cash "
                 f"{_feur(recon.get('reported_cash'))} = derived {_feur(recon.get('derived_total'))} vs broker "
                 f"{_feur(recon.get('total_equity'))} (delta {_feur(recon.get('cash_delta'))}, "
                 f"threshold {_feur(recon.get('threshold'))}) → **{status}**.")
    return "\n".join(lines).rstrip() + "\n"


def _nv(item: Any, key: str, default: Any = "") -> Any:
    """Field access across dict records and NewsItem-like objects. Never raises."""
    try:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)
    except Exception:
        return default


def portfolio_health_score(rows: list[dict] | None, recon_status: str) -> tuple[int, str]:
    """Deterministic 0-100 health score + label.

    Formula (documented, no judgment calls): FAIL → 40; else any canonical
    SELL → 70; else non-PASS (UNKNOWN/DEGRADED path) → 70; else 90.
    Labels: >=80 HEALTHY, >=60 WATCH, else CRITICAL.
    """
    status = str(recon_status or "").upper()
    if status == "FAIL":
        score = 40
    else:
        sells = sum(1 for r in (rows or []) if isinstance(r, dict)
                    and normalize_signal((r or {}).get("signal")) == "SELL")
        score = 70 if (sells > 0 or status != "PASS") else 90
    label = "HEALTHY" if score >= 80 else ("WATCH" if score >= 60 else "CRITICAL")
    return score, label


def _deep_item_line(item: Any) -> str:
    title = str(_nv(item, "title", "") or "")[:140]
    url = str(_nv(item, "url", "") or "")
    source = str(_nv(item, "source", "") or "")
    pub = str(_nv(item, "published", "") or _nv(item, "published_str", "") or "")
    title_md = f"[{title}]({url})" if url else title
    return f"- {title_md} — {source} · {pub}".rstrip(" ·")


def _deep_bucket_lines(bucket: Any, limit: int = 5) -> list[str]:
    items = bucket if isinstance(bucket, list) else []
    return [_deep_item_line(i) for i in items[:limit]
            if str(_nv(i, "title", "") or "").strip()]


def build_deep_dive(
    *,
    generated_at: str,
    run_id: str,
    regime_result,
    recon: dict,
    rows: list[dict],
    monitoring_items: list[dict],
    t212_data: dict | None,
    news_by_symbol: dict | None,
    decision_news: list[dict],
    earnings_7d: dict,
    ideas: list[dict],
    trump_tracking: dict | None,
    commodity_news: dict | None,
    analyst_news: dict | None,
    order_plans: dict | None,
    dividends_12m: dict | None = None,
    stage_attribution: dict | None = None,
    result_modes: dict | None = None,
) -> str:
    """Render the deep-dive companion brief (15 fixed sections, deterministic).

    Data-contract: every section reads only already-computed structures;
    missing/empty input renders "No coverage this run." — never invented
    content, never LLM prose, never sized orders beyond advisory plans.
    The concise briefs and their contract are untouched by this document.
    """
    recon = recon or {}
    status = str(recon.get("status", "UNKNOWN")).upper()
    regime = getattr(regime_result, "regime", "UNKNOWN") if regime_result is not None else "UNKNOWN"
    perf = ((t212_data or {}).get("account_summary", {}) or {}) if isinstance(t212_data, dict) else {}
    cash = ((t212_data or {}).get("cash", {}) or {}) if isinstance(t212_data, dict) else {}

    def _num(value):
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    # Phase 5: explicit statuses instead of a single opaque health score.
    broker_status = "OK" if rows else "NO_ROWS"
    # Research coverage (WP3): report real counts, never a hardcoded "OK".
    _news_buckets = len([1 for v in (news_by_symbol or {}).values() if v])
    _decision_news_n = len(decision_news or [])
    _research_buckets = sum(len(v) for v in (news_by_symbol or {}).values()) if news_by_symbol else 0
    research_status = (f"{_research_buckets} items across {_news_buckets} buckets; "
                       f"{_decision_news_n} decision-relevant")
    ai_status = "OK" if (result_modes or {}) else "UNKNOWN"
    advisory_status = "OK"
    status_lines = [
        f"- Broker data: **{broker_status}** | Accounting audit: **{status}**",
        f"- Research coverage: **{research_status}** | AI processing: **{ai_status}**",
        f"- Advisory eligibility: **{advisory_status}**",
    ]

    lines = [
        "# Portfolio Deep Dive", "",
        f"Run: `{run_id}` | Generated: {generated_at}",
        f"Reconciliation: **{status}**",
        "",
        "## 1. Executive Summary & Status", "",
        f"- Stance: **{portfolio_stance(rows, status)}** | Regime: **{regime}**",
        *status_lines,
        f"- Broker total equity: {_feur(perf.get('total_equity', (recon or {}).get('total_equity')))}",
        f"- Reported free cash: {_feur(cash.get('free', 0))} | Total reported cash: "
        f"{_feur(_num(cash.get('free', 0)) + _num(cash.get('pie_cash', 0)) + _num(cash.get('blocked', 0)))}",
        "",
        "## 2. Macro & Policy Watch (Trump/Geopolitics)", "",
    ]
    trump_lines: list[str] = []
    for _cat, _items in (trump_tracking or {}).items() if isinstance(trump_tracking, dict) else []:
        for _it in (_items or [])[:3]:
            if str(_nv(_it, "title", "") or "").strip():
                trump_lines.append(f"- [{_cat}] " + _deep_item_line(_it))
    # Add macro-tagged news from news_by_symbol
    macro_lines: list[str] = []
    for _sym, _entries in (news_by_symbol or {}).items() if isinstance(news_by_symbol, dict) else []:
        for _it in (_entries or [])[:3]:
            _sec = str(_nv(_it, "section", "") or "").upper()
            if _sec in ("MACRO", "GENERAL") and str(_nv(_it, "title", "") or "").strip():
                macro_lines.append(f"- [{str(_nv(_it, 'display_symbol', _sym)).upper()}] " + _deep_item_line(_it))
    lines += trump_lines[:8] or macro_lines[:8] or ["No coverage this run."]
    lines += ["", "## 3. Energy & Commodities Analysis", ""]
    energy_lines: list[str] = []
    for _target, _items in (commodity_news or {}).items() if isinstance(commodity_news, dict) else []:
        for _it in (_items or [])[:3]:
            if str(_nv(_it, "title", "") or "").strip():
                energy_lines.append(f"- [{_target}] " + _deep_item_line(_it))
    # Add energy-tagged news
    for _sym, _entries in (news_by_symbol or {}).items() if isinstance(news_by_symbol, dict) else []:
        for _it in (_entries or [])[:3]:
            _sec = str(_nv(_it, "section", "") or "").upper()
            if _sec == "ENERGY" and str(_nv(_it, "title", "") or "").strip():
                energy_lines.append(f"- [{str(_nv(_it, 'display_symbol', _sym)).upper()}] " + _deep_item_line(_it))
    lines += energy_lines[:8] or ["No coverage this run."]

    _health_kw = ("fda", "trial", "pharma", "biotech", "drug", "healthcare", "clinical")
    _crypto_kw = ("bitcoin", "ethereum", "crypto", "solana", "btc", "eth")
    health_lines: list[str] = []
    crypto_lines: list[str] = []
    for _sym, _entries in (news_by_symbol or {}).items() if isinstance(news_by_symbol, dict) else []:
        for _it in (_entries or [])[:5]:
            _sec = str(_nv(_it, "section", "") or "").upper()
            if _sec == "HEALTHCARE" and str(_nv(_it, "title", "") or "").strip():
                health_lines.append(f"- [{str(_nv(_it, 'display_symbol', _sym)).upper()}] " + _deep_item_line(_it))
            elif _sec == "CRYPTO" and str(_nv(_it, "title", "") or "").strip():
                crypto_lines.append(f"- [{str(_nv(_it, 'display_symbol', _sym)).upper()}] " + _deep_item_line(_it))
    lines += ["", "## 4. Healthcare Sector Update", ""]
    lines += health_lines[:6] or ["No coverage this run."]
    lines += ["", "## 5. Crypto Market Trends", ""]
    lines += crypto_lines[:6] or ["No coverage this run."]
    lines += ["", "## 6. Earnings Calendar & Upcoming Catalysts", ""]
    window = (earnings_7d or {}).get("in_window", []) if isinstance(earnings_7d, dict) else []
    if window:
        for ev in window[:10]:
            tag = "(confirmed)" if ev.get("status") == "confirmed" else "(estimated)"
            lines.append(f"- {_mday(ev.get('date', ''))} — {ev.get('display', '')}, "
                         f"{ev.get('company', '')} — earnings {tag}")
    else:
        lines.append("No relevant earnings events in the next 7 days.")
    _nxt = (earnings_7d or {}).get("next_after") if isinstance(earnings_7d, dict) else None
    if isinstance(_nxt, dict) and _nxt.get("date"):
        tag = "(confirmed)" if _nxt.get("status") == "confirmed" else "(estimated)"
        lines.append(f"- Next after this window: {_nxt.get('date', '')} — {_nxt.get('display', '')}, "
                     f"{_nxt.get('company', '')} — earnings {tag}.")
    lines += ["", "## 7. Analyst Ratings & Consensus Changes", ""]
    analyst_lines: list[str] = []
    for _sym, _items in (analyst_news or {}).items() if isinstance(analyst_news, dict) else []:
        for _it in (_items or [])[:3]:
            if str(_nv(_it, "title", "") or "").strip():
                analyst_lines.append(f"- [{_sym}] " + _deep_item_line(_it))
    lines += analyst_lines[:8] or ["No coverage this run."]
    lines += ["", "## 8. Watchlist & Discovery Opportunities", ""]
    if ideas:
        for idea in ideas[:5]:
            lines.append(f"- **{idea.get('ticker', '')}** — WATCH — {idea.get('reason', '')}")
    else:
        lines.append("No new ideas met the current evidence and validation threshold.")
    lines += ["", "## 9. Portfolio Advisory & Rebalancing Recommendations", ""]
    _plans = (order_plans or {}).get("plans", []) or [] if isinstance(order_plans, dict) else []
    try:
        from investment_engine.risk.profiles import describe_line as _profile_line
        _profile = (order_plans or {}).get("policy_profile") if isinstance(order_plans, dict) else None
        if isinstance(_profile, dict) and _profile.get("name"):
            lines += [_profile_line(_profile), ""]
    except Exception:
        pass
    if _plans and status != "FAIL":
        lines.append("> Advisory only — not executed. Confirm manually outside this program.")
        lines.append("")
        for plan in _plans:
            if isinstance(plan, dict):
                lines.append(f"- **{plan.get('ticker')}** {plan.get('direction')} "
                             f"~€{float(plan.get('indicative_notional_eur', 0) or 0):,.2f}")
    else:
        # Phase 5: specific blocker reason instead of generic text
        blocked = (order_plans or {}).get("blocked", []) or []
        # Policy status comes from order_plans (set by caller) or defaults to NOT SET
        policy_status = str((order_plans or {}).get("policy_version", "") or "")
        has_policy = bool(policy_status) and policy_status != "NOT SET"
        if not has_policy:
            lines.append("No advisory plans this run: investment policy NOT SET.")
        elif blocked:
            reasons = list({str(b.get("reason", "")) for b in blocked if b.get("reason")})
            if reasons:
                lines.append(f"No advisory plans this run: {'; '.join(reasons[:3])}.")
            else:
                lines.append("No advisory plans this run: all candidates blocked by gates.")
        else:
            lines.append("No advisory plans this run: no valid candidates passed all gates.")
    lines += ["", "## 10. Risk Management & Drawdown Analysis", ""]
    _sells = [r for r in (rows or []) if isinstance(r, dict)
              and normalize_signal((r or {}).get("signal")) == "SELL"]
    _conc = sorted(((float(r.get("weight", 0) or 0), str(r.get("display_symbol") or r.get("ticker")))
                    for r in (rows or []) if isinstance(r, dict)), reverse=True)[:5]
    if _sells:
        lines.append(f"- Positions flagged for reduction: {', '.join(sorted({str(r.get('display_symbol') or r.get('ticker')) for r in _sells}))}.")
    else:
        lines.append("- No positions flagged for reduction.")
    if _conc and _conc[0][0] > 0:
        lines.append("- Largest weights: " + ", ".join(f"{d} {w:.1f}%" for w, d in _conc) + ".")
    lines.append("- Drawdown history: unavailable — no historical equity series retained (per-run snapshots only).")
    if status == "FAIL":
        lines.append("- Deployment blocked: reconciliation FAIL (see brief).")
    lines += ["", "## 11. Technical Overview & Support/Resistance Levels", ""]
    _tech_rows = [r for r in (rows or []) if isinstance(r, dict)
                  and (_eur_level(r, "support_eur") is not None or _eur_level(r, "resistance_eur") is not None
                       or _eur_level(r, "support") is not None or _eur_level(r, "resistance") is not None)][:10]
    if _tech_rows:
        for r in _tech_rows:
            # Prefer anchored EUR levels; fall back to raw S/R with currency note
            sup_eur = _eur_level(r, "support_eur")
            res_eur = _eur_level(r, "resistance_eur")
            if sup_eur is not None and res_eur is not None:
                sr_note = f" ({r.get('sr_currency', '')}→EUR)" if r.get("sr_currency") else ""
                lines.append(f"- **{r.get('display_symbol') or r.get('ticker')}**: "
                             f"support {_fnum(sup_eur)} / resistance {_fnum(res_eur)}{sr_note}.")
            else:
                # Fallback to raw S/R with native currency
                sup_raw = _eur_level(r, "support")
                res_raw = _eur_level(r, "resistance")
                ccy = r.get("quote_currency") or r.get("sr_currency") or ""
                ccy_note = f" [{ccy}]" if ccy else ""
                lines.append(f"- **{r.get('display_symbol') or r.get('ticker')}**: "
                             f"support {_fnum(sup_raw)} / resistance {_fnum(res_raw)}{ccy_note} (native).")
    else:
        lines.append("No support/resistance levels available (mappings unverified or no data).")
    lines += ["", "## 12. Asset Allocation Breakdown", ""]
    _alloc = sorted(((float(r.get("weight", 0) or 0), str(r.get("display_symbol") or r.get("ticker")))
                     for r in (rows or []) if isinstance(r, dict)), reverse=True)[:10]
    if _alloc and _alloc[0][0] > 0:
        for w, d in _alloc:
            lines.append(f"- {d}: {w:.2f}%")
    else:
        lines.append("No allocation weights available.")
    lines += ["", "## 13. Dividend & Yield Tracker", ""]
    _divs = dividends_12m if isinstance(dividends_12m, dict) else {}
    _div_rows = sorted(
        ((v.get("yield_pct") if isinstance(v.get("yield_pct"), (int, float)) else -1.0, k, v)
         for k, v in _divs.items() if isinstance(v, dict)),
        reverse=True)[:8]
    if _div_rows and _div_rows[0][0] >= 0:
        for _y, _d, _v in _div_rows:
            lines.append(f"- **{_d}**: TTM yield {_y:.2f}% "
                         f"({_v.get('ttm_per_share', '?')}/share native, "
                         f"{_v.get('payments_12m', '?')}x/12M, last ex {_v.get('last_ex_date', '?')}).")
        lines.append("- Yields from Yahoo Finance payouts vs latest close; broker P&L untouched.")
    else:
        lines.append("No trailing-12M dividends reported for covered holdings (Yahoo Finance).")
    lines += ["",
              "## 14. ESG & Governance Notes", "",
              "No ESG feed wired - governance notes out of scope for this run.",
              ""]
    # Phase 4: Runtime indicator backend detection (not hardcoded)
    try:
        import importlib.util as _ilu
        _has_ta = _ilu.find_spec("pandas_ta") is not None
        _indicator_backend = "reference (pandas-ta)" if _has_ta else "manual"
    except Exception:
        _indicator_backend = "unknown"
    lines += ["", "## 15. Appendix & Data Sources", "",
              "- Broker: Trading 212 read-only API (quantities, prices, P&L are broker truth).",
              f"- Market data: Yahoo Finance (+ Playwright sweep fallback); indicators: {_indicator_backend}.",
              "- News: Google News RSS + verified RSS fallbacks + corpus tiers + TradingView symbol news.",
              "- Dividends: Yahoo Finance trailing-12M payouts (informational; broker P&L untouched).",
              ]
    _sa = stage_attribution if isinstance(stage_attribution, dict) else {}
    if _sa:
        try:
            from investment_engine.providers.attribution import format_stage_line as _fmt_sa
        except Exception:
            _fmt_sa = None
        lines.append("- Models actually used this run:")
        for _st in sorted(_sa):
            _rec = _sa.get(_st) or {}
            if _fmt_sa is not None:
                lines.append(f"  - {_fmt_sa(_st, _rec)}")
            else:
                lines.append(f"  - {_st}: {(_rec.get('provider') or '?')}/"
                             f"{(_rec.get('model_served') or '?')}")
    else:
        lines.append("- Models per stage: see run_manifest `providers_per_stage`.")
    _mode_line = str((result_modes or {}).get("api_execution_mode", "") or "").strip() if isinstance(result_modes, dict) else ""
    lines.append("- Execution mode: " + (_mode_line or "see run_manifest ai_execution_mode") + ".")
    return "\n".join(lines).rstrip() + "\n"
    return "\n".join(lines).rstrip() + "\n"

"""Deterministic report sections extracted from ``main.py``.

Priority actions, KPIs, monitoring, venue warnings, and canonical enforcement.
Formatting helpers that consume these live in ``reporting.formatters``.
"""

from __future__ import annotations

from typing import Any

from investment_engine.reporting.documents import _eur_level
from investment_engine.run_state import FALLBACK_EVENTS as _FALLBACK_EVENTS


def _provider_fallback_note() -> str:
    if not _FALLBACK_EVENTS:
        return ""
    stages = sorted({e.split(":")[0] for e in _FALLBACK_EVENTS})
    return (
        f"> ℹ️ **Provider note:** local LLM endpoints unavailable; "
        f"deterministic fallback used for: {', '.join(stages)}."
    )


def _passive_pie_lines(pies: list[dict[str, Any]]) -> str:
    lines = ["## Passive Pies — pie-level decision only"]
    for pie in pies:
        lines.append(f"- **{pie['name']}** — HOLD / regular add — long-term. Decisions are intentionally at Pie level; individual constituents are not analysed.")
    return "\n".join(lines)


def _validate_new_ideas(candidate_section: str | None, news_by_symbol: dict | None) -> str:
    """Render only validated structured ideas; never raw LLM prose.

    Shared extractor (see reporting.documents); this wrapper preserves the
    legacy "Potential New Ideas" section shape.
    """
    from investment_engine.reporting.documents import extract_validated_ideas
    FALLBACK = "No new ideas met the current evidence and validation threshold."
    ideas = extract_validated_ideas(candidate_section, news_by_symbol)
    lines = ["## Potential New Ideas", ""]
    if not ideas:
        lines.append(FALLBACK)
        return "\n".join(lines)
    lines.append("| Ticker | Evidence | Source | Confidence |")
    lines.append("|--------|----------|--------|------------|")
    for idea in ideas:
        lines.append(f"| **{idea['ticker']}** | {idea['evidence']} | {idea['url']} | {idea['confidence']} |")
    return "\n".join(lines)


def _build_monitoring_block(
    portfolio_rows: list[dict] | None,
    earnings_status: dict | None = None,
    technicals: dict | None = None,
) -> str:
    """Deterministic Portfolio Monitoring bullet for FAIL state.

    Owned HOLD positions with a priority trigger render REVIEW as a
    presentation-only status; everything else stays HOLD. Never WATCH.
    """
    earn_by_ticker: dict[str, str] = {}
    try:
        for disp, val in (earnings_status or {}).items():
            d = val[0][:10] if isinstance(val, (tuple, list)) and val and isinstance(val[0], str) else None
            if d:
                earn_by_ticker[str(disp).strip().upper()] = d
    except Exception:
        pass
    items: list[str] = []
    for r in sorted(portfolio_rows or [], key=lambda x: float((x or {}).get("market_value", 0) or 0), reverse=True):
        if not isinstance(r, dict):
            continue
        disp = str(r.get("display_symbol") or r.get("ticker") or "").strip().upper()
        if not disp or str(r.get("signal", "HOLD")).strip().upper() != "HOLD":
            continue
        tech = (technicals or {}).get(disp) if isinstance(technicals, dict) else None
        trig = _hold_trigger_reason(r, earn_by_ticker.get(disp, ""), tech if isinstance(tech, dict) else None)
        if trig:
            items.append(f"**{disp}** — REVIEW: {trig}; canonical holding action remains HOLD. No transaction authorized.")
    body = "; ".join(items) if items else ""
    if body:
        body += "; "
    return f"- **Portfolio Monitoring:** {body}rest **HOLD**."


def _strip_priority_actions_from_summary(summary_md: str) -> str:
    """Remove any LLM-generated Priority Actions table; it is rebuilt deterministically."""
    import re as _re3
    if not summary_md:
        return "## Summary\n- Portfolio review completed; see deterministic Priority Actions below."
    # Strip code fences the model sometimes wraps around the section.
    fence_stripped = _re3.sub(r"^\s*```(?:markdown|md)?\s*\n", "", summary_md.strip())
    fence_stripped = _re3.sub(r"\n?\s*```\s*$", "", fence_stripped).strip()
    summary_md = fence_stripped or summary_md
    # Cut from '## Priority Actions' (or '# Priority Actions') to end/next top header.
    cut = _re3.split(r"^#{1,3}\s*Priority Actions.*$", summary_md, flags=_re3.MULTILINE | _re3.IGNORECASE)
    base = cut[0].rstrip() if cut else summary_md
    # Also drop stray markdown tables that look like action tables (Ticker|Action).
    lines = []
    skip_table = False
    for ln in base.splitlines():
        if _re3.match(r"^\s*\|.*Ticker.*Action.*\|\s*$", ln, _re3.IGNORECASE):
            skip_table = True
            continue
        if skip_table:
            if _re3.match(r"^\s*\|", ln) or _re3.match(r"^\s*\|?[\s:\-|]+\|?\s*$", ln):
                continue
            if not ln.strip():
                continue
            skip_table = False
        lines.append(ln)
    out = "\n".join(lines).strip()
    return out or "## Summary\n- Portfolio review completed; see deterministic Priority Actions below."


def _hold_trigger_reason(row: dict, earnings_date: str = "", tech: dict | None = None) -> str:
    """Concrete trigger for surfacing a HOLD row, or '' when there is none.

    Triggers: earnings within 14 days, weight >= 5%, abs(P&L%) >= 10%,
    RSI <= 25 or >= 75, or price within 2% of a key level.
    """
    try:
        if earnings_date:
            from datetime import date as _d
            delta = (_d.fromisoformat(earnings_date[:10]) - _d.today()).days
            if 0 <= delta <= 14:
                return f"earnings in {delta}d"
    except (ValueError, TypeError):
        pass
    try:
        if float(row.get("weight", 0) or 0) >= 5.0:
            return "weight >= 5%"
    except (TypeError, ValueError):
        pass
    try:
        if abs(float(row.get("pnl_pct", 0) or 0)) >= 10.0:
            return "P&L move >= 10%"
    except (TypeError, ValueError):
        pass
    rsi = (tech or {}).get("RSI_14") if isinstance(tech, dict) else None
    try:
        if rsi is not None and (float(rsi) <= 25 or float(rsi) >= 75):
            return f"RSI {float(rsi):.1f} extreme"
    except (TypeError, ValueError):
        pass
    try:
        px = float(row.get("current_price", 0) or 0)
        # EUR-vs-EUR: row prices are EUR, so proximity must use the converted
        # levels (raw natives are USD/DKK/GBX-scale and would never match).
        for lvl in (row.get("support_eur", row.get("support")),
                    row.get("resistance_eur", row.get("resistance"))):
            if lvl is not None and px > 0 and abs(px - float(lvl)) / px <= 0.02:
                return "price near key level"
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return ""


def _safe_pct(v) -> str:
    try:
        return f"{float(v or 0):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _safe_money(v) -> str:
    try:
        return f"€{float(v or 0):+,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _safe_w(v) -> str:
    try:
        return f"{float(v or 0):.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _build_priority_actions_table(
    portfolio_rows: list[dict] | None,
    earnings_status: dict | None = None,
    technicals: dict | None = None,
    max_rows: int = 10,
    canonical_map: dict | None = None,
) -> str:
    """Deterministic Priority Actions from canonical portfolio rows only.

    Every ticker exists in the T212 Portfolio table and every signal equals
    the canonical signal. SELL/BUY actions first; HOLD rows appear only with
    a concrete trigger (see _hold_trigger_reason). The table is never padded
    artificially.
    """
    import re as _re4
    rows = [r for r in (portfolio_rows or []) if isinstance(r, dict) and (r.get("display_symbol") or r.get("ticker"))]
    if not rows:
        return "### Priority Actions\n\nNo actionable signals — all holdings neutral on current data."
    for r in rows:
        disp = r.get("display_symbol") or r.get("ticker")
        sig = r.get("signal", "HOLD")
        if isinstance(canonical_map, dict):
            entry = canonical_map.get(str(disp).strip().upper())
            if isinstance(entry, dict) and entry.get("signal"):
                sig = entry["signal"]
        r["_norm"] = str(sig).strip().upper() if str(sig).strip().upper() in ("BUY", "SELL") else "HOLD"
        r["_disp"] = disp
    sells = sorted([r for r in rows if r["_norm"] == "SELL"], key=lambda r: float(r.get("market_value", 0) or 0), reverse=True)
    buys = sorted([r for r in rows if r["_norm"] == "BUY"], key=lambda r: float(r.get("market_value", 0) or 0), reverse=True)
    earn_by_ticker: dict[str, str] = {}
    try:
        for disp, val in (earnings_status or {}).items():
            d = val[0][:10] if isinstance(val, (tuple, list)) and val and isinstance(val[0], str) else None
            if d:
                earn_by_ticker[str(disp).strip().upper()] = d
    except Exception:
        pass
    holds: list[dict] = []
    for r in sorted([r for r in rows if r["_norm"] == "HOLD"], key=lambda r: float(r.get("market_value", 0) or 0), reverse=True):
        tech = (technicals or {}).get(r["_disp"])
        trig = _hold_trigger_reason(r, earn_by_ticker.get(str(r["_disp"]).strip().upper(), ""), tech if isinstance(tech, dict) else None)
        if trig:
            r["_trigger"] = trig
            holds.append(r)
    picked = (sells + buys + holds)[:max_rows]
    if not picked:
        return "### Priority Actions\n\nNo action triggers — all holdings neutral on current data."
    lines = ["### Priority Actions", "",
             "| Ticker | Action | Why | Horizon | Catalyst/Key Level |",
             "|--------|--------|-----|---------|---------------------|"]
    for r in picked:
        ticker = str(r["_disp"])
        sig = r["_norm"]
        emoji = {"BUY": "🟢 BUY", "SELL": "🔴 SELL"}.get(sig, "🟡 HOLD")
        # Brief prices/P&L are EUR; native S/R (USD/GBX/CNY) must never leak
        # into this column. _eur_level also returns None when FX conversion
        # failed instead of falling back to the raw native value.
        sup = _eur_level(r, "support")
        res = _eur_level(r, "resistance")
        try:
            sup_s = f"{float(sup):.2f}" if sup is not None else "n/a"
        except (TypeError, ValueError):
            sup_s = "n/a"
        try:
            res_s = f"{float(res):.2f}" if res is not None else "n/a"
        except (TypeError, ValueError):
            res_s = "n/a"
        tech = (technicals or {}).get(ticker)
        rsi_s = ""
        try:
            if isinstance(tech, dict) and tech.get("RSI_14") is not None:
                rsi_s = f"RSI {float(tech['RSI_14']):.1f}; "
        except (TypeError, ValueError):
            pass
        earn = earn_by_ticker.get(ticker.strip().upper(), "")
        earn_s = f"earnings {earn}; " if earn else ""
        trig_s = f"trigger: {r['_trigger']}; " if r.get("_trigger") else ""
        why = f"{trig_s}{rsi_s}{earn_s}P&L {_safe_pct(r.get('pnl_pct'))} ({_safe_money(r.get('unrealized_pnl'))}), weight {_safe_w(r.get('weight'))}".strip()
        horizon = "Swing" if sig == "SELL" else ("Long" if sig == "BUY" else "long-term")
        catalyst = f"Support {sup_s} / Resistance {res_s}"
        # Keep cells single-line.
        why = _re4.sub(r"\s*\|\s*", "; ", why)
        lines.append(f"| **{ticker}** | {emoji} | {why} | {horizon} | {catalyst} |")
    return "\n".join(lines)


def _enforce_canonical_in_pie_section(
    pie_md: str,
    canonical_map: dict | None,
    known_clean: set | None = None,
) -> str:
    """Rewrite PIE sample bullets to the canonical signal (display symbols).

    The technical observation is preserved after the em dash, e.g.
    ``NEE — HOLD — improving setup; watch €86.87 resistance before upgrade.``
    Internal broker IDs are replaced with display symbols.
    """
    if not pie_md or not isinstance(canonical_map, dict) or not canonical_map:
        return pie_md
    try:
        from investment_engine.portfolio.symbols import to_display_symbol as _td3
    except Exception:
        _td3 = lambda s, *_: str(s or "").strip().upper().split("_")[0]
    import re as _re5

    # Normalize any internal broker IDs in the prose to display symbols first.
    def _disp_sub(m):
        return _td3(m.group(0), known_clean)
    text = _re5.sub(r"\b[A-Z0-9]+_(?:US_EQ|DE_EQ|IM_EQ|EQ)\b", _disp_sub, pie_md, flags=_re5.IGNORECASE)

    def _repl(m):
        raw_ticker = m.group("ticker")
        raw_sig = m.group("sig")
        disp = _td3(raw_ticker, known_clean)
        entry = canonical_map.get(disp.strip().upper())
        if not isinstance(entry, dict) or not entry.get("signal"):
            # No canonical entry: normalize the ticker spelling only.
            if disp != raw_ticker:
                return f"{m.group('prefix')}{disp} — **{raw_sig.strip().upper()}**{m.group('rest')}"
            return m.group(0)
        want = entry["signal"]
        rest = m.group("rest") or ""
        # Preserve the observation; drop a contradictory trailing marker.
        rest = _re5.sub(r"\s*\(normalized to [^)]*\)\s*$", "", rest)
        marker = ""
        if want == "HOLD" and "HOLD —" not in rest:
            # Keep any existing observation text as-is.
            marker = ""
        return f"{m.group('prefix')}{disp} — **{want}**{rest}{marker}"

    # Matches bullets like: - **TICKER** — **SELL** — ... (display or internal IDs)
    pat = _re5.compile(
        r"(?P<prefix>(?:^|\n)\s*(?:[-*]\s*)?(?:\*\*)?)(?P<ticker>[A-Za-z0-9.]{1,12}(?:_(?:US_EQ|DE_EQ|IM_EQ|EQ))?)(?:\*\*)?\s*—\s*(?:\*\*)?(?P<sig>BUY|SELL|HOLD|ACCUMULATE|ACCUMLATE|TRIM|REDUCE|WATCH|WAIT)(?:\*\*)?(?P<rest>[^\n]*)",
        _re5.IGNORECASE,
    )
    return pat.sub(_repl, text)


def _derive_top_risks(regime_result, t212_data, portfolio_rows, earnings_status, technicals) -> str:
    """Derive 2-3 concise risk items from actual holdings. Never blank/dash."""
    items: list[str] = []
    rows = list(portfolio_rows or [])
    # 1. Concentration: largest portfolio weight.
    try:
        if rows:
            top = max(rows, key=lambda r: float(r.get("weight", 0) or 0))
            w = float(top.get("weight", 0) or 0)
            if w > 0:
                items.append(f"Concentration: {top.get('ticker')} {w:.1f}% of equity (€{float(top.get('market_value', 0)):,.2f})")
    except Exception:
        pass
    # 2. Drawdown: worst unrealized P&L %.
    try:
        if rows:
            worst = min(rows, key=lambda r: float(r.get("pnl_pct", 0) or 0))
            wp = float(worst.get("pnl_pct", 0) or 0)
            if wp < 0:
                items.append(f"Drawdown: {worst.get('ticker')} {wp:+.1f}% (€{float(worst.get('unrealized_pnl', 0)):+,.2f})")
            elif worst.get("ticker"):
                items.append(f"P&L laggard: {worst.get('ticker')} {wp:+.1f}% — limited cushion on pullback")
    except Exception:
        pass
    # 3. Earnings proximity: nearest upcoming earnings among holdings.
    try:
        tickers = {str(r.get("ticker", "")).strip().upper() for r in rows}
        bases = {t.split("_")[0] for t in tickers}
        upcoming: list[tuple[str, str]] = []
        for disp, val in (earnings_status or {}).items():
            d = val[0][:10] if isinstance(val, (tuple, list)) and val else (val[:10] if isinstance(val, str) else None)
            if not d:
                continue
            key = str(disp).strip().upper()
            if key in tickers or key.split("_")[0] in bases:
                upcoming.append((d, str(disp)))
        upcoming.sort()
        if upcoming:
            nxt = "; ".join(f"{t} {d}" for d, t in upcoming[:2])
            items.append(f"Earnings event risk: {nxt}")
    except Exception:
        pass
    # 4. Technical extremes (RSI overbought/oversold) from available technicals.
    try:
        extremes: list[str] = []
        for sym, ind in (technicals or {}).items():
            if not isinstance(ind, dict):
                continue
            rsi = ind.get("RSI_14")
            if rsi is None:
                continue
            try:
                r = float(rsi)
            except (TypeError, ValueError):
                continue
            if r >= 70:
                extremes.append(f"{sym} overbought RSI {r:.1f}")
            elif r <= 30:
                extremes.append(f"{sym} oversold RSI {r:.1f}")
        if extremes:
            items.append("Technicals: " + "; ".join(sorted(set(extremes))[:2]))
    except Exception:
        pass
    # 5. Regime fallback (only to fill up to 2 items, still holding-aware).
    if len(items) < 2 and regime_result is not None:
        try:
            reg = getattr(regime_result, "regime", "NEUTRAL")
            if reg in ("PEAK_HOLD", "DECLINING"):
                items.append(f"Regime {reg}: reduce new exposure, prefer cash buffer")
            else:
                n = len(rows)
                items.append(f"Market {reg}: {n} holdings exposed to broad pullback; no cash hedge beyond reserve")
        except Exception:
            pass
    if not items:
        # Last-resort holding-aware fallback (still never blank/dash).
        n = len(rows)
        items.append(f"{n} holdings monitored; single-name and earnings risks under review")
    return "; ".join(items[:3])

# Public aliases for cross-module use (private names remain the
# implementation detail and stay available for in-module calls).
provider_fallback_note = _provider_fallback_note
passive_pie_lines = _passive_pie_lines
validate_new_ideas = _validate_new_ideas
build_monitoring_block = _build_monitoring_block
strip_priority_actions_from_summary = _strip_priority_actions_from_summary
hold_trigger_reason = _hold_trigger_reason
safe_pct = _safe_pct
safe_money = _safe_money
safe_w = _safe_w
build_priority_actions_table = _build_priority_actions_table
enforce_canonical_in_pie_section = _enforce_canonical_in_pie_section
derive_top_risks = _derive_top_risks

def _headlines_block(news: dict[str, list[dict]]) -> str:
    """Compact headline list for prompts: SYM: title (source)."""
    parts = []
    for sym, entries in news.items():
        for e in entries[:2]:
            parts.append(f"{sym}: {e.get('title','')[:120]} ({e.get('source','')})")
    return "\n".join(parts) if parts else "None"

headlines_block = _headlines_block


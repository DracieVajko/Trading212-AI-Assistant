"""WatchlistStance v1: sector-style research watchlist with an explicit stance.

Generalises the "SECTOR | WATCHLIST | VERIFIED CATALYST | CONFIRMATION |
KEY RISK | RESEARCH STANCE" brief format. Every field is derived from the
supplied evidence; nothing is invented. Stance rules are deterministic and
enforce "no chasing" and "event-risk wait".

Stance vocabulary (ordered by priority):
- EVENT_RISK_WAIT     earnings or macro event within 2 trading days
- NO_CHASING          RSI >= 70 or price within 1% of resistance without confirmation
- SELECTIVE_WATCH     catalyst present, confirmation not yet met
- FUNDAMENTAL_WATCH   fundamental catalyst present and trend intact
- WATCH               evidence too thin to act
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from investment_engine.skills import contracts

SKILL = "watchlist_stance"
VERSION = "v1"

_STANCE_PRIORITY = ("EVENT_RISK_WAIT", "NO_CHASING", "SELECTIVE_WATCH", "FUNDAMENTAL_WATCH", "WATCH")
_EVENT_RISK_DAYS = 2
_RSI_OVERBOUGHT = 70.0
_RESISTANCE_PROXIMITY = 0.01


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _days_until(value: Any) -> int | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        d = datetime.fromisoformat(text).date()
    except ValueError:
        return None
    return (d - date.today()).days


def _catalyst_for(ticker: str, news_events: list[dict[str, Any]],
                  earnings_status: dict[str, Any]) -> str:
    best = None
    for event in news_events:
        if str(event.get("ticker", "")).upper() != ticker:
            continue
        if event.get("state") != "CONFIRMED":
            continue
        if best is None or str(event.get("severity")) == "high":
            best = event
    if best is not None:
        return f"{best.get('type', 'event')}: {str(best.get('what_is_new', ''))[:140]}"
    status = str((earnings_status or {}).get(ticker, "") or "")
    if status and status.lower() not in ("n/a", "none", "unknown"):
        return f"Earnings: {status[:140]}"
    return ""


def _confirmation_for(ticker: str, tech: dict[str, Any] | None) -> str:
    tech = tech or {}
    price = _num(tech.get("price"))
    resistance = _num(tech.get("resistance"))
    support = _num(tech.get("support"))
    rsi = _num(tech.get("rsi"))
    parts: list[str] = []
    if price and resistance and resistance > price:
        parts.append(f"close above {round(resistance, 2)}")
    if price and support and support < price:
        parts.append(f"hold above {round(support, 2)}")
    if rsi is not None:
        parts.append(f"RSI recovery from {round(rsi, 1)}")
    return "; ".join(parts) if parts else "no technical confirmation available"


def _key_risk(ticker: str, tech: dict[str, Any] | None, weight: float,
              earnings_days: int | None, cap_pct: float) -> str:
    tech = tech or {}
    risks: list[str] = []
    if earnings_days is not None and 0 <= earnings_days <= _EVENT_RISK_DAYS:
        risks.append(f"earnings in {earnings_days}d")
    if weight > cap_pct:
        risks.append(f"weight {weight:.1f}% above {cap_pct:.0f}% cap")
    rsi = _num(tech.get("rsi"))
    if rsi is not None and rsi >= _RSI_OVERBOUGHT:
        risks.append(f"RSI {rsi:.1f} extended")
    atr = _num(tech.get("atr"))
    price = _num(tech.get("price"))
    if atr and price:
        atr_pct = atr / price * 100.0
        if atr_pct >= 5.0:
            risks.append(f"high volatility {atr_pct:.1f}% ATR")
    return "; ".join(risks) if risks else "no specific risk flags"


def _stance(tech: dict[str, Any] | None, catalyst: str, earnings_days: int | None,
            has_confirmation: bool) -> str:
    tech = tech or {}
    rsi = _num(tech.get("rsi"))
    price = _num(tech.get("price"))
    resistance = _num(tech.get("resistance"))
    if earnings_days is not None and 0 <= earnings_days <= _EVENT_RISK_DAYS:
        return "EVENT_RISK_WAIT"
    near_resistance = bool(price and resistance and price > 0
                           and abs(price - resistance) / price <= _RESISTANCE_PROXIMITY)
    if (rsi is not None and rsi >= _RSI_OVERBOUGHT) or near_resistance:
        return "NO_CHASING"
    if catalyst and not has_confirmation:
        return "SELECTIVE_WATCH"
    if catalyst and has_confirmation:
        trend = str(tech.get("trend", "")).upper()
        if trend.endswith("_UP") or trend == "UP":
            return "FUNDAMENTAL_WATCH"
    return "WATCH"


def run(inputs: dict[str, Any], provider=None, settings=None, language: str = "English") -> dict[str, Any]:
    watchlist = [str(t).upper() for t in (inputs.get("watchlist", []) or []) if str(t).strip()]
    portfolio_rows = [r for r in (inputs.get("portfolio_rows", []) or []) if isinstance(r, dict)]
    if not watchlist:
        for row in portfolio_rows:
            tick = str(row.get("display_symbol") or row.get("ticker") or "").strip().upper()
            if tick:
                watchlist.append(tick)
    if not watchlist:
        return contracts.insufficient_output(SKILL, VERSION, "no watchlist or portfolio tickers")

    techs = inputs.get("technicals", {}) or {}
    news_events = [e for e in (inputs.get("news_events", []) or []) if isinstance(e, dict)]
    earnings_status = inputs.get("earnings_status", {}) or {}
    sectors = inputs.get("sectors", {}) or {}
    rows_by_ticker = {}
    for row in portfolio_rows:
        tick = str(row.get("display_symbol") or row.get("ticker") or "").strip().upper()
        if tick:
            rows_by_ticker[tick] = row
    try:
        cap_pct = float(inputs.get("concentration_cap_pct", 20.0) or 20.0)
    except (TypeError, ValueError):
        cap_pct = 20.0

    rows: list[dict[str, Any]] = []
    for tick in watchlist:
        row = rows_by_ticker.get(tick, {})
        tech = (techs.get(tick) if isinstance(techs, dict) else None) or {}
        if not tech and row:
            tech = {
                "price": row.get("current_price") or row.get("price"),
                "support": row.get("support") or row.get("support_eur"),
                "resistance": row.get("resistance") or row.get("resistance_eur"),
                "rsi": row.get("rsi"),
                "atr": row.get("atr"),
                "trend": row.get("trend", ""),
            }
        weight = _num(row.get("weight")) or 0.0
        earnings_days = _days_until(
            (earnings_status or {}).get(tick)
            if isinstance((earnings_status or {}).get(tick), str) else None
        )
        catalyst = _catalyst_for(tick, news_events, earnings_status)
        confirmation = _confirmation_for(tick, tech)
        has_confirmation = confirmation != "no technical confirmation available"
        risk = _key_risk(tick, tech, weight, earnings_days, cap_pct)
        stance = _stance(tech, catalyst, earnings_days, has_confirmation)
        rows.append({
            "ticker": tick,
            "sector": str((sectors or {}).get(tick, "") or "Unclassified"),
            "catalyst": catalyst or "no verified catalyst",
            "confirmation_to_watch": confirmation,
            "key_risk": risk,
            "research_stance": stance,
            "weight_pct": round(weight, 2),
            "earnings_days": earnings_days,
        })

    # Event calendar enrichment: attach a deterministic "why it matters".
    # When no explicit calendar is supplied, derive earnings events from the
    # earnings_status map (ticker -> date) for the next 14 days.
    calendar: list[dict[str, Any]] = []
    for event in (inputs.get("event_calendar", []) or []):
        if not isinstance(event, dict):
            continue
        name = str(event.get("event", "")).strip()
        if not name:
            continue
        calendar.append({
            "date": str(event.get("date", ""))[:10],
            "event": name,
            "why_it_matters": _why_it_matters(name),
        })
    if not calendar and isinstance(earnings_status, dict):
        for tick, when in earnings_status.items():
            days = _days_until(when if isinstance(when, str) else None)
            if days is None or not (0 <= days <= 14):
                continue
            name = f"{tick} earnings"
            calendar.append({
                "date": str(when)[:10],
                "event": name,
                "why_it_matters": _why_it_matters(name),
            })
        calendar.sort(key=lambda e: e.get("date", ""))

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["research_stance"]] = counts.get(row["research_stance"], 0) + 1
    basis = [f"tickers={len(rows)}", "deterministic-stance-rules"]
    return {
        "skill": SKILL,
        "version": VERSION,
        "execution_type": "DETERMINISTIC",
        "execution_reason": "DETERMINISTIC_BY_DESIGN",
        "fallback_reason": "",
        "status": "OK",
        "reason": "",
        "confidence": contracts.confidence(0.6, basis),
        "unverified": [r["ticker"] for r in rows if r["research_stance"] == "WATCH"],
        "data": {"rows": rows, "stance_counts": counts, "event_calendar": calendar},
    }


def _why_it_matters(event_name: str) -> str:
    low = event_name.lower()
    if "earnings" in low or "results" in low:
        return "Earnings quality: revenue, margins and guidance."
    if "cpi" in low or "consumer price" in low:
        return "Fed expectations; impact on growth and gold."
    if "ppi" in low or "producer price" in low:
        return "Wholesale price trends and the inflation outlook."
    if "fed" in low or "fomc" in low or "rate" in low:
        return "Rate path; impact on valuations and the dollar."
    if "job" in low or "payroll" in low or "unemployment" in low:
        return "Labour market strength and rate expectations."
    if "gdp" in low:
        return "Growth momentum and the macro backdrop."
    return "Macro or company event affecting sentiment and positioning."


def render(output: dict[str, Any]) -> str:
    data = output.get("data", {}) or {}
    lines: list[str] = []
    for row in data.get("rows", []) or []:
        lines.append(
            f"- **{row.get('ticker')}** ({row.get('sector')}) — {row.get('research_stance')} | "
            f"catalyst: {row.get('catalyst')} | confirm: {row.get('confirmation_to_watch')} | "
            f"risk: {row.get('key_risk')}"
        )
    calendar = data.get("event_calendar", []) or []
    if calendar:
        lines.append("")
        for event in calendar:
            lines.append(f"- {event.get('date')} — {event.get('event')}: {event.get('why_it_matters')}")
    return "\n".join(lines) if lines else "No watchlist rows."

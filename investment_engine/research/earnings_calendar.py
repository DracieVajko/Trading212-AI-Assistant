"""Earnings calendar ingestion from a weekly markdown file.

The agent (or a scheduled job) drops a markdown file (default name
``stocks_earnings.md``) into the project root each week. It lists the tickers
reporting that week with their dates and company names. This module parses that
file into a structured list and produces a compact prompt block so the LLM and
the research pipeline know which names have imminent catalysts.

The file is re-read on every call (mtime-cached) so a weekly update is picked
up without a restart. Format is intentionally tolerant: markdown tables,
``date ticker company`` lines and ``ticker - date - company`` lines are all
accepted.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILENAME = "stocks_earnings.md"
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _parse_date(tok: str) -> str | None:
    tok = tok.strip().strip("|").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y",
                "%b %d", "%B %d", "%d %b", "%d %B"):
        try:
            d = datetime.strptime(tok, fmt)
            if "%Y" not in fmt and "%y" not in fmt:
                d = d.replace(year=date.today().year)
            return d.date().isoformat()
        except ValueError:
            continue
    # ISO-ish fallback
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", tok)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _find_file(path: str | Path | None = None) -> Path | None:
    if path is not None:
        p = Path(path)
        return p if p.is_file() else None
    for cand in (ROOT / DEFAULT_FILENAME, Path.cwd() / DEFAULT_FILENAME,
                 ROOT / "data" / DEFAULT_FILENAME):
        if cand.is_file():
            return cand
    return None


def load_earnings_calendar(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Parse the weekly earnings file into a list of {date, ticker, company}.

    Returns [] when the file is missing or unparseable. Cached by mtime.
    """
    p = _find_file(path)
    if p is None:
        return []
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return []
    key = str(p)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return [dict(r) for r in cached[1]]
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    text = text.lstrip("\ufeff")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        # Markdown table row
        if "|" in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and not all(set(c) <= set("-: ") for c in cells):
                # try to find a date and a ticker among cells
                date_val = None
                ticker = None
                company = ""
                for c in cells:
                    if date_val is None:
                        d = _parse_date(c)
                        if d:
                            date_val = d
                            continue
                    if ticker is None and re.fullmatch(r"[A-Z][A-Z0-9.\-]{1,9}", c):
                        ticker = c
                        continue
                    if not company and c and not re.fullmatch(r"[A-Z][A-Z0-9.\-]{1,9}", c):
                        company = c
                if date_val and ticker:
                    key_ = (date_val, ticker)
                    if key_ not in seen:
                        seen.add(key_)
                        rows.append({"date": date_val, "ticker": ticker, "company": company})
            continue
        # Plain line: split on whitespace or dashes
        toks = re.split(r"\s+[-–—]\s+|\s+", line)
        toks = [t for t in toks if t]
        if len(toks) < 2:
            continue
        date_val = None
        ticker = None
        company_parts: list[str] = []
        for t in toks:
            if date_val is None:
                d = _parse_date(t)
                if d:
                    date_val = d
                    continue
            if ticker is None and re.fullmatch(r"[A-Z][A-Z0-9.\-]{1,9}", t):
                ticker = t
                continue
            company_parts.append(t)
        if date_val and ticker:
            key_ = (date_val, ticker)
            if key_ not in seen:
                seen.add(key_)
                rows.append({"date": date_val, "ticker": ticker,
                            "company": " ".join(company_parts)})
    _CACHE[key] = (mtime, rows)
    return [dict(r) for r in rows]


def upcoming_earnings(days: int = 7, path: str | Path | None = None) -> list[dict[str, Any]]:
    """Subset of the calendar falling within the next ``days`` days."""
    today = date.today()
    out = []
    for r in load_earnings_calendar(path):
        try:
            d = date.fromisoformat(r["date"])
        except (TypeError, ValueError):
            continue
        if 0 <= (d - today).days <= days:
            out.append(r)
    out.sort(key=lambda r: r["date"])
    return out


def earnings_block(days: int = 7, path: str | Path | None = None) -> str:
    """Compact prompt block listing imminent earnings catalysts."""
    rows = upcoming_earnings(days, path)
    if not rows:
        return ""
    lines = [f"EARNINGS CALENDAR (next {days} days):"]
    for r in rows:
        comp = f" - {r['company']}" if r.get("company") else ""
        lines.append(f"- {r['date']}: {r['ticker']}{comp}")
    return "\n".join(lines)

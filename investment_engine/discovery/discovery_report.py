"""discovery_report.py — Generate discovery_opportunities.md report.

Formats discovery screener results into a markdown report with:
- Top candidates (CANDIDATE status) with price targets
- Watch list (WATCH status)
- Rejected (REJECT status with reasons)
- Discovery metadata (universe size, filters applied)
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def write_discovery_report(candidates: list[dict], universe_size: int, run_id: str, price_targets: dict | None = None) -> str:
    """Render discovery results as markdown with price targets."""
    price_targets = price_targets or {}
    lines: list[str] = [
        "# Discovery Opportunities",
        "",
        f"- **Run ID**: `{run_id}`",
        f"- **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **Universe size**: {universe_size} tickers screened",
        f"- **Candidates found**: {len(candidates)}",
        "",
        ("> **Disclaimer**: Discovery results are algorithmic screening outputs. "
        "Each candidate must be verified by the AI agent (Stage 2) before any action. "
        "Discovery never emits BUY signals — only CANDIDATE / WATCH / REJECT."),
        "",
    ]

    if not candidates:
        lines.extend([
            "## No candidates found",
            "",
            "No tickers passed the screening filters. This may indicate:",
            "- Market regime is risk-off (SPY below 200 SMA)",
            "- All candidates failed pump-risk or technical filters",
            "- Universe is too small or data is stale",
            "",
        ])
        return "\n".join(lines)

    # Group by status
    candidates_list = [c for c in candidates if c.get("status") == "CANDIDATE"]
    watch_list = [c for c in candidates if c.get("status") == "WATCH"]
    reject_list = [c for c in candidates if c.get("status") == "REJECT"]

    if candidates_list:
        lines.extend([
            f"## Top Candidates ({len(candidates_list)})",
            "",
            "| # | Ticker | Score | Base | Ext | Buy Range | Take Profit | Stop Loss | Expected (30d) | R/R |",
            "|---|--------|-------|------|-----|-----------|-------------|-----------|----------------|-----|",
        ])
        for idx, c in enumerate(candidates_list, 1):
            ticker = c.get("ticker", "?")
            pt = price_targets.get(ticker, {})
            buy_range = f"{pt.get('buy_range_low', '—')} - {pt.get('buy_range_high', '—')}" if pt.get("buy_range_low") else "—"
            tp = pt.get("take_profit", "—")
            sl = pt.get("stop_loss", "—")
            exp = pt.get("expected_price_30d", "—")
            rr = pt.get("risk_reward_ratio", "—")
            lines.append(
                f"| {idx} | `{ticker}` | {c.get('score', 0)} | {c.get('base', 0)} | {c.get('ext', 0)} | {buy_range} | {tp} | {sl} | {exp} | {rr} |"
            )
        # Add detailed price target section
        lines.extend(["", "### Price Target Details", ""])
        for c in candidates_list:
            ticker = c.get("ticker", "?")
            pt = price_targets.get(ticker, {})
            if pt.get("current_price"):
                lines.extend([
                    f"**{ticker}** (current: {pt['current_price']})",
                    f"- Support: {pt.get('support', 'N/A')} | Resistance: {pt.get('resistance', 'N/A')}",
                    f"- Buy range: {pt.get('buy_range_low', 'N/A')} - {pt.get('buy_range_high', 'N/A')}",
                    f"- Take profit: {pt.get('take_profit', 'N/A')} | Stop loss: {pt.get('stop_loss', 'N/A')}",
                    f"- Expected (30d): {pt.get('expected_price_30d', 'N/A')} | Risk/Reward: {pt.get('risk_reward_ratio', 'N/A')}",
                    f"- ATR(14): {pt.get('atr', 'N/A')} | SMA50: {pt.get('sma50', 'N/A')} | SMA200: {pt.get('sma200', 'N/A')}",
                    "",
                ])
        lines.append("")

    if watch_list:
        lines.extend([
            f"## Watch List ({len(watch_list)})",
            "",
            "| # | Ticker | Score | Base | Ext | Reasons | Flags |",
            "|---|--------|-------|------|-----|---------|-------|",
        ])
        for idx, c in enumerate(watch_list, 1):
            reasons = ", ".join(c.get("reasons", [])) or "—"
            flags = ", ".join(c.get("flags", [])) or "—"
            lines.append(
                f"| {idx} | `{c.get('ticker', '?')}` | {c.get('score', 0)} | {c.get('base', 0)} | {c.get('ext', 0)} | {reasons} | {flags} |"
            )
        lines.append("")

    if reject_list:
        lines.extend([
            f"## Rejected ({len(reject_list)})",
            "",
            "| Ticker | Reasons |",
            "|--------|---------|",
        ])
        for c in reject_list[:20]:
            reasons = ", ".join(c.get("reasons", [])) or "—"
            lines.append(f"| `{c.get('ticker', '?')}` | {reasons} |")
        if len(reject_list) > 20:
            lines.append(f"| ... | +{len(reject_list) - 20} more rejected |")
        lines.append("")

    lines.extend([
        "---",
        "*Generated by Portfolio AI Assistant — Discovery Engine (Stage 0).*",
        "*Candidates must be verified by Stage 2 (AI agent) before any action.*",
    ])
    return "\n".join(lines)

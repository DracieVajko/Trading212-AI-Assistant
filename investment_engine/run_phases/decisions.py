"""Per-scope LLM decision sections (crypto, tech, renewables)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from investment_engine.config.settings import EngineSettings

logger = logging.getLogger(__name__)


@dataclass
class DecisionInputs:
    """Inputs for the decision-section loop."""

    crypto: list[dict[str, str]]
    tech: list[dict[str, str]]
    other: list[dict[str, str]]
    renewable: list[dict[str, str]]
    news_by_symbol: dict[str, list[dict[str, Any]]]
    earnings: dict[str, Any]
    language: str
    regime_context: str
    provider: Any
    settings: EngineSettings
    decision_sections: list[str] = field(default_factory=list)
    verbose_sections: list[str] = field(default_factory=list)


@dataclass
class DecisionSections:
    """Curated and verbose sections produced by the loop."""

    decision_sections: list[str]
    verbose_sections: list[str]


def build_decision_sections(inputs: DecisionInputs) -> DecisionSections:
    """Generate the Crypto/Tech/Renewables decision sections."""
    from investment_engine.providers.generation import generate_with_fallback
    from investment_engine.research.earnings_fetch import tech_summary_line

    news_for_llm = inputs.news_by_symbol
    decision_sections = list(inputs.decision_sections)
    verbose_sections = list(inputs.verbose_sections)

    groups = (
        ("Crypto — decision only", inputs.crypto),
        ("Active Positions — Tech", inputs.tech + inputs.other),
        ("Active Positions — Renewables", inputs.renewable),
    )
    for title, positions in groups:
        if not positions:
            continue
        try:
            from investment_engine.portfolio.symbols import to_display_symbol

            position_symbols = {to_display_symbol(str(item.get("ticker", ""))) for item in positions}
        except Exception:
            position_symbols = {item["ticker"] for item in positions}
        scoped_news = {
            symbol: entries
            for symbol, entries in news_for_llm.items()
            if symbol in position_symbols
            or (title.startswith("Crypto") and symbol in ["CRYPTO-MACRO", "MACRO"])
        }
        scoped_earnings = {
            symbol: date
            for symbol, date in inputs.earnings.items()
            if symbol in position_symbols
        }

        tech_data: dict[str, dict] = {}
        for pos in positions:
            symbol = pos["ticker"]
            try:
                from investment_engine.portfolio.symbols import to_display_symbol
                from investment_engine.portfolio.symbols import to_yahoo_symbol
                from investment_engine.research.market_data import fetch_technical_indicators

                display = to_display_symbol(symbol)
                yahoo = to_yahoo_symbol(symbol, display, None)
                if not yahoo:
                    continue
                indicators = fetch_technical_indicators(yahoo, period="3mo", interval="1d")
                if indicators:
                    tech_data[symbol] = indicators
            except Exception:
                pass

        tech_summary = ""
        for symbol, indicators in tech_data.items():
            tech_summary += tech_summary_line(symbol, indicators) + "\n"

        if title.startswith("Crypto"):
            prompt = f"""Write only the '{title}' section of a concise portfolio report in {inputs.language}. This is research, not financial advice.
Return at most 300 tokens. Use one Markdown bullet for every supplied ticker, with exactly: TICKER — BUY/SELL/HOLD/WAIT/WATCH — horizon (swing/long-term) — concise catalyst or risk — key level (support/resistance).
Do not invent prices, results, dates, news, or analyst opinions. Use the supplied headlines only as current evidence.

MARKET REGIME CONTEXT:
{inputs.regime_context}

TECHNICAL DATA:
{tech_summary or 'None available'}

POSITIONS: {positions}
RECENT HEADLINES: {[f"{sym}: {e.get('title','')[:120]} ({e.get('source','')}, {e.get('published','')})" for sym, entries in scoped_news.items() for e in entries] or 'None'}"""
        else:
            prompt = f"""Write only the '{title}' section of a concise portfolio report in {inputs.language}. This is research, not financial advice.
Return at most 500 tokens. Use one Markdown bullet for every supplied ticker, with exactly: TICKER — BUY/SELL/HOLD/WAIT/WATCH — horizon (intraday/swing/long-term) — concise catalyst or risk — key level (support/resistance) — earnings date/status.
Do not invent prices, results, dates, news, or analyst opinions. Use the supplied headlines only as current evidence. Aggressive short or intraday ideas must be marked HIGH RISK.

MARKET REGIME CONTEXT:
{inputs.regime_context}

TECHNICAL DATA:
{tech_summary or 'None available'}

POSITIONS: {positions}
EARNINGS: {scoped_earnings}
RECENT HEADLINES: {[f"{sym}: {e.get('title','')[:120]} ({e.get('source','')}, {e.get('published','')})" for sym, entries in scoped_news.items() for e in entries] or 'None'}"""

        section = generate_with_fallback(
            inputs.provider,
            prompt,
            inputs.settings,
            tokens=500,
            stage="decision",
        )
        verbose_sections.append(f"## {title}\n{section}")

    return DecisionSections(
        decision_sections=decision_sections,
        verbose_sections=verbose_sections,
    )

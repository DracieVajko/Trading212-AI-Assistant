"""currency_universe.py — Currency-aware stock universe mapping.

Maps US tickers to their European/EU exchange equivalents to avoid FX conversion
fees when the account currency differs from the quote currency.

For example, if account currency is EUR:
- AAPL_US_EQ (NASDAQ, USD) → AAPL.DE (XETRA, EUR) or AAPL.F (Frankfurt, EUR)
- NVDA_US_EQ → NVDA.DE or NVDA.F
- TSLA_US_EQ → TSLA.DE or TSLA.F

This avoids unnecessary FX conversion fees on buy/sell.
"""

from __future__ import annotations

from typing import Any

# Canonical mapping: broker_symbol (US) -> list of (symbol, currency, venue)
# Ordered by preference (most liquid first)
US_TO_EU_MAP: dict[str, list[dict[str, str]]] = {
    "AAPL_US_EQ": [
        {"ticker": "AAPL.DE", "currency": "EUR", "venue": "XETRA"},
        {"ticker": "AAPL.F", "currency": "EUR", "venue": "XETRA"},
    ],
    "MSFT_US_EQ": [
        {"ticker": "MSFT.DE", "currency": "EUR", "venue": "XETRA"},
        {"ticker": "MSFT.F", "currency": "EUR", "venue": "XETRA"},
    ],
    "NVDA_US_EQ": [
        {"ticker": "NVDA.DE", "currency": "EUR", "venue": "XETRA"},
        {"ticker": "NVDA.F", "currency": "EUR", "venue": "XETRA"},
    ],
    "AMZN_US_EQ": [
        {"ticker": "AMZN.DE", "currency": "EUR", "venue": "XETRA"},
        {"ticker": "AMZN.F", "currency": "EUR", "venue": "XETRA"},
    ],
    "META_US_EQ": [
        {"ticker": "META.DE", "currency": "EUR", "venue": "XETRA"},
        {"ticker": "META.F", "currency": "EUR", "venue": "XETRA"},
    ],
    "TSLA_US_EQ": [
        {"ticker": "TSLA.DE", "currency": "EUR", "venue": "XETRA"},
        {"ticker": "TSLA.F", "currency": "EUR", "venue": "XETRA"},
    ],
    "BRK-B_US_EQ": [
        {"ticker": "BRK-B.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "AVGO_US_EQ": [
        {"ticker": "AVGO.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "JPM_US_EQ": [
        {"ticker": "JPM.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "LLY_US_EQ": [
        {"ticker": "LLY.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "V_US_EQ": [
        {"ticker": "V.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "UNH_US_EQ": [
        {"ticker": "UNH.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "XOM_US_EQ": [
        {"ticker": "XOM.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "MA_US_EQ": [
        {"ticker": "MA.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "JNJ_US_EQ": [
        {"ticker": "JNJ.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "PG_US_EQ": [
        {"ticker": "PG.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "HD_US_EQ": [
        {"ticker": "HD.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "MRK_US_EQ": [
        {"ticker": "MRK.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "COST_US_EQ": [
        {"ticker": "COST.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "ABBV_US_EQ": [
        {"ticker": "ABBV.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "CVX_US_EQ": [
        {"ticker": "CVX.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "BAC_US_EQ": [
        {"ticker": "BAC.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "KO_US_EQ": [
        {"ticker": "KO.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "PEP_US_EQ": [
        {"ticker": "PEP.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "ADBE_US_EQ": [
        {"ticker": "ADBE.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "WMT_US_EQ": [
        {"ticker": "WMT.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "CRM_US_EQ": [
        {"ticker": "CRM.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "MCD_US_EQ": [
        {"ticker": "MCD.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "NFLX_US_EQ": [
        {"ticker": "NFLX.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "TMO_US_EQ": [
        {"ticker": "TMO.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "ACN_US_EQ": [
        {"ticker": "ACN.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "ABT_US_EQ": [
        {"ticker": "ABT.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "LIN_US_EQ": [
        {"ticker": "LIN.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "DHR_US_EQ": [
        {"ticker": "DHR.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "ORCL_US_EQ": [
        {"ticker": "ORCL.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "TXN_US_EQ": [
        {"ticker": "TXN.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "NEE_US_EQ": [
        {"ticker": "NEE.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "PM_US_EQ": [
        {"ticker": "PM.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "CAT_US_EQ": [
        {"ticker": "CAT.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "RTX_US_EQ": [
        {"ticker": "RTX.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "UPS_US_EQ": [
        {"ticker": "UPS.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "LOW_US_EQ": [
        {"ticker": "LOW.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "INTU_US_EQ": [
        {"ticker": "INTU.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "AMGN_US_EQ": [
        {"ticker": "AMGN.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "IBM_US_EQ": [
        {"ticker": "IBM.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "GS_US_EQ": [
        {"ticker": "GS.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "BLK_US_EQ": [
        {"ticker": "BLK.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "ISRG_US_EQ": [
        {"ticker": "ISRG.DE", "currency": "EUR", "venue": "XETRA"},
    ],
    "MDT_US_EQ": [
        {"ticker": "MDT.DE", "currency": "EUR", "venue": "XETRA"},
    ],
}


def resolve_symbol_for_currency(
    broker_symbol: str,
    account_currency: str = "EUR",
    universe_map: dict[str, list[dict[str, str]]] | None = None,
) -> str:
    """Resolve a broker symbol to the best currency-matched ticker.

    If account currency matches the broker symbol's currency, return as-is.
    Otherwise, look up an equivalent ticker in the user's account currency.

    Args:
        broker_symbol: Original broker symbol (e.g., "AAPL_US_EQ")
        account_currency: Account currency code (e.g., "EUR", "USD", "GBP")
        universe_config: Optional custom universe mapping

    Returns:
        The best matching ticker symbol for the account currency
    """
    # Normalize broker symbol
    broker_symbol = str(broker_symbol or "").strip().upper()

    # Map common broker symbol formats
    # e.g., "AAPL_US_EQ" -> "AAPL", "NVDA_US_EQ" -> "NVDA"
    base_symbol = broker_symbol.split("_")[0] if "_" in broker_symbol else broker_symbol

    # If account currency matches broker currency, return as-is
    if account_currency == "USD":
        return broker_symbol
    if account_currency == "EUR":
        # Check if we have a EUR-denominated equivalent
        eu_options = universe_map.get(broker_symbol, []) if universe_mapping else []
        for option in eu_options:
            if option.get("currency") == "EUR":
                return option["ticker"]

    # Fallback: return original
    return broker_symbol


def build_currency_aware_universe(
    config: Any,
    portfolio_positions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a universe with currency-aware symbols.

    For each position/ticker, check if there's a EUR-denominated equivalent
    available on European exchanges. If so, use that instead of the US listing.

    Args:
        config: DayTraderConfig or similar config object
        portfolio_positions: Current portfolio positions

    Returns:
        List of universe entries with currency-aware symbols
    """
    from investment_engine.day_trader.config import DayTraderConfig

    if not isinstance(config, DayTraderConfig):
        # Legacy support
        universe_list = list(
            _FALLBACK_UNIVERSE
            + _EU_UNIVERSE
            + _CHINA_UNIVERSE
            + _ETF_UNIVERSE
        )
        return [{"ticker": s, "source": "universe"} for s in universe_list]

    universe_list: list[dict[str, Any]] = []

    # Add ETFs (usually already EUR-denominated on EU exchanges)
    for etf in config.universe.extra_symbols:
        universe_list.append(
            {
                "ticker": etf,
                "source": "universe_etf",
                "currency": "EUR",
                "region": "EU",
            }
        )

    # Add EU universe stocks
    for ticker in _EU_UNIVERSE:
        universe_list.append(
            {"ticker": ticker, "source": "universe_eu", "currency": "EUR", "region": "EU"}
        )

    # Add China universe
    for ticker in _CHINA_UNIVERSE:
        universe_list.append(
            {"ticker": ticker, "source": "universe_china", "currency": "USD", "region": "CN"}
        )

    # Add US stocks with currency-aware mapping
    sp500_tickers = [
        "AAPL_US_EQ",
        "MSFT_US_EQ",
        "NVDA_US_EQ",
        "AMZN_US_EQ",
        "GOOGL_US_EQ",
        "META_US_EQ",
        "TSLA_US_EQ",
        "BRK-B_US_EQ",
        "AVGO_US_EQ",
        "JPM_US_EQ",
        "LLY_US_EQ",
        "V_US_EQ",
        "UNH_US_EQ",
        "XOM_US_EQ",
        "MA_US_EQ",
        "JNJ_US_EQ",
        "PG_US_EQ",
        "HD_US_EQ",
        "MRK_US_EQ",
        "COST_US_EQ",
        "ABBV_US_EQ",
        "CVX_US_EQ",
        "BAC_US_EQ",
        "KO_US_EQ",
        "PEP_US_EQ",
        "ADBE_US_EQ",
        "WMT_US_EQ",
        "CRM_US_EQ",
        "MCD_US_EQ",
        "NFLX_US_EQ",
        "TMO_US_EQ",
        "ACN_US_EQ",
        "ABT_US_EQ",
        "LIN_US_EQ",
        "DHR_US_EQ",
        "ORCL_US_EQ",
        "TXN_US_EQ",
        "NEE_US_EQ",
        "PM_US_EQ",
        "CAT_US_EQ",
        "RTX_US_EQ",
        "UPS_US_EQ",
        "LOW_US_EQ",
        "INTU_US_EQ",
        "AMGN_US_EQ",
        "IBM_US_EQ",
        "GS_US_EQ",
        "BLK_US_EQ",
        "ISRG_US_EQ",
        "MDT_US_EQ",
    ]

    for ticker in sp500_tickers:
        # Check if we have a EUR equivalent
        eu_equiv = None
        for eu_entry in _EU_UNIVERSE:
            if eu_entry == ticker.replace("_US_EQ", ".DE") or eu_entry == ticker.replace(
                "_US_EQ", ".F"
            ):
                eu_equiv = eu_entry
                break

        if eu_equiv and config.universe.include_eu:
            universe_list.append(
                {
                    "ticker": eu_equiv,
                    "source": "universe_sp500_eur",
                    "currency": "EUR",
                    "region": "EU",
                    "original_ticker": ticker,
                    "currency_converted": True,
                }
            )
        else:
            universe_list.append(
                {
                    "ticker": ticker,
                    "source": "universe_sp500",
                    "currency": "USD",
                    "region": "US",
                    "original_ticker": ticker,
                    "currency_converted": False,
                }
            )

    # Remove duplicates while preserving order
    seen = set()
    unique_universe = []
    for item in universe_list:
        ticker = item["ticker"]
        if ticker not in seen:
            seen.add(ticker)
            unique_universe.append(item)

    return unique_universe[: config.universe.max_symbols]


def build_currency_aware_universe(
    config: Any,
    portfolio_positions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build universe with currency-aware mapping.

    Args:
        config: DayTraderConfig instance
        portfolio_positions: Current portfolio positions for context

    Returns:
        List of universe entries with currency-aware symbols
    """
    return build_universe_symbols(config, portfolio_symbols=portfolio_positions)
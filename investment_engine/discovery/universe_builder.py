"""universe_builder.py — Build stock universe with currency-aware mapping.

Builds a universe of stock tickers for discovery screening, with support for
currency-aware symbol mapping (e.g., AAPL_US_EQ -> AAPL.DE for EUR accounts)
to avoid unnecessary FX conversion fees.
"""

from __future__ import annotations

from typing import Any

from investment_engine.day_trader.config import DayTraderConfig


def _is_eur_ticker(ticker: str) -> bool:
    """Check if ticker is EUR-denominated (European exchange)."""
    return ticker.endswith((".DE", ".CO", ".MC", ".PA", ".AS", ".L", ".SW"))


def _is_hkd_ticker(ticker: str) -> bool:
    """Check if ticker is HKD-denominated (Hong Kong exchange)."""
    return ticker.endswith(".HK")


def _is_us_ticker(ticker: str) -> bool:
    """Check if ticker is USD-denominated (US exchange)."""
    return ticker.endswith("_US_EQ") or not any(
        ticker.endswith(suffix)
        for suffix in (".DE", ".CO", ".MC", ".PA", ".AS", ".L", ".SW", ".HK", ".T", ".SI", ".JK")
    )


def build_universe_symbols(
    config: Any,
    portfolio_symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build stock universe with currency-aware mapping.

    Args:
        config: DayTraderConfig instance with universe configuration.
        portfolio_symbols: Existing portfolio symbols to include.

    Returns:
        List of dicts with keys: ticker, source, currency, region, original_ticker,
        currency_converted.
    """
    universe_list: list[dict[str, Any]] = []

    # Get config values
    cfg = config.universe if hasattr(config, "universe") else {}

    # Add ETFs first (typically EUR-denominated on EU exchanges)
    for etf in getattr(cfg, "extra_symbols", []) or []:
        currency = "EUR" if _is_eur_ticker(etf) else ("HKD" if _is_hkd_ticker(etf) else "USD")
        region = "EU" if currency == "EUR" else ("CN" if currency == "HKD" else "US")
        universe_list.append(
            {
                "ticker": etf,
                "source": "universe_etf",
                "currency": currency,
                "region": region,
            }
        )

    # Add EU universe (already EUR-denominated)
    from investment_engine.discovery.universe import _EU_UNIVERSE as _EU_LIST

    for ticker in _EU_LIST:
        universe_list.append(
            {
                "ticker": ticker,
                "source": "universe_eu",
                "currency": "EUR",
                "region": "EU",
            }
        )

    # Add China/HK universe (HKD-denominated)
    from investment_engine.discovery.universe import _CHINA_UNIVERSE as _CHINA_UNIVERSE_LIST

    for ticker in _CHINA_UNIVERSE_LIST:
        universe_list.append(
            {
                "ticker": ticker,
                "source": "universe_china",
                "currency": "HKD",
                "region": "CN",
            }
        )

    # Add US stocks with currency-aware mapping
    _SP500_TICKERS = [
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

    for ticker in _SP500_TICKERS:
        # Check if we have a EUR-denominated equivalent on EU exchanges
        eu_equiv = None
        for eu_entry in _EU_LIST:
            if eu_entry == ticker.replace("_US_EQ", ".DE") or eu_entry == ticker.replace(
                "_US_EQ", ".F"
            ):
                eu_equiv = eu_entry
                break

        if eu_equiv:
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
            # US stock - USD currency
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
    seen: set[str] = set()
    unique_universe: list[dict[str, Any]] = []
    for item in universe_list:
        ticker = item["ticker"]
        if ticker not in seen:
            seen.add(ticker)
            unique_universe.append(item)

    # Limit to max_symbols
    max_symbols = getattr(cfg.universe, "max_symbols", 500) if hasattr(cfg, "universe") else 500
    unique_universe = unique_universe[:max_symbols]

    return unique_universe

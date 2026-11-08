"""forecast_engine.py — Scenario forecasting with pessimistic/base/optimistic outcomes.

Bootstrap-resamples historical daily returns to project price scenarios over
several horizons. Uses only data available up to the forecast date — no
look-ahead bias. Deterministic for a fixed seed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_HORIZONS: tuple[int, ...] = (30, 90, 252)
MIN_RETURNS: int = 30


@dataclass
class Scenario:
    """A single projected price outcome."""

    price: float
    return_pct: float


@dataclass
class HorizonForecast:
    """Scenario prices for one horizon."""

    horizon_days: int
    current_price: float
    pessimistic: Scenario
    base: Scenario
    optimistic: Scenario


@dataclass
class ForecastResult:
    """Forecast for one symbol across multiple horizons."""

    symbol: str
    as_of: str
    current_price: float
    horizons: list[HorizonForecast]
    warnings: list[str] = None  # type: ignore[assignment]

    # Metadata
    method: str = "bootstrap"
    n_scenarios: int = 1000
    confidence_level: float = 0.95
    lookback_returns: int = 0
    generated_at: str = ""

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "current_price": self.current_price,
            "warnings": self.warnings,
            "method": self.method,
            "n_scenarios": self.n_scenarios,
            "confidence_level": self.confidence_level,
            "generated_at": self.generated_at,
            "horizons": [
                {
                    "horizon_days": hf.horizon_days,
                    "current_price": hf.current_price,
                    "pessimistic_price": hf.pessimistic.price,
                    "base_price": hf.base.price,
                    "optimistic_price": hf.optimistic.price,
                }
                for hf in self.horizons
            ],
        }


class ForecastEngine:
    """Bootstrap-resampling forecast engine.

    Resamples historical daily returns to build pessimistic (2.5th),
    base (median) and optimistic (97.5th) cumulative-return scenarios
    for each horizon.
    """

    def __init__(self, n_scenarios: int = 1000, seed: int = 42):
        self.n_scenarios = n_scenarios
        self.seed = seed

    def forecast(
        self,
        ticker: str,
        daily: pd.DataFrame,
        horizons: int | list[int] | tuple[int, ...] = DEFAULT_HORIZONS,
        confidence_pct: float = 95.0,
        seed: int | None = None,
    ) -> ForecastResult:
        """Forecast ``ticker`` from a daily DataFrame with a ``close`` column.

        Args:
            ticker: Stock symbol.
            daily: DataFrame with daily OHLC data (requires ``close``).
            horizons: Single horizon or list of horizons in trading days.
            confidence_pct: Confidence level in percent (0-100).
            seed: Optional seed override; falls back to the engine seed.

        Returns:
            ForecastResult. On insufficient data, ``horizons`` is empty and
            ``warnings`` explains why.
        """
        engine_seed = self.seed if seed is None else seed
        if isinstance(horizons, int):
            horizons = [horizons]

        if daily is None or not isinstance(daily, pd.DataFrame) or daily.empty or "close" not in daily.columns:
            warning = "Insufficient data for forecast: no valid 'close' column"
            logger.warning("%s (%s)", warning, ticker)
            return ForecastResult(
                symbol=ticker,
                as_of=datetime.now(timezone.utc).isoformat(),
                current_price=0.0,
                horizons=[],
                warnings=[warning],
                n_scenarios=self.n_scenarios,
            )

        close = daily["close"].dropna()
        returns = close.pct_change().dropna()

        if len(returns) < MIN_RETURNS:
            warning = f"Insufficient data for forecast: {len(returns)} returns (need >= {MIN_RETURNS})"
            logger.warning("%s (%s)", warning, ticker)
            return ForecastResult(
                symbol=ticker,
                as_of=datetime.now(timezone.utc).isoformat(),
                current_price=float(close.iloc[-1]) if len(close) > 0 else 0.0,
                horizons=[],
                warnings=[warning],
                n_scenarios=self.n_scenarios,
            )

        current_price = float(close.iloc[-1])
        confidence_level = float(np.clip(confidence_pct, 0.0, 100.0)) / 100.0

        horizon_forecasts = []
        for idx, horizon_days in enumerate(sorted(int(h) for h in horizons)):
            horizon_forecasts.append(
                self._bootstrap_horizon(
                    ticker,
                    returns,
                    current_price,
                    int(horizon_days),
                    confidence_level,
                    engine_seed + idx,
                )
            )

        return ForecastResult(
            symbol=ticker,
            as_of=datetime.now(timezone.utc).isoformat(),
            current_price=current_price,
            horizons=horizon_forecasts,
            warnings=[],
            n_scenarios=self.n_scenarios,
            confidence_level=confidence_level,
            lookback_returns=len(returns),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def forecast_from_prices(
        self,
        ticker: str,
        prices: pd.Series,
        horizons: int | list[int] | tuple[int, ...] = DEFAULT_HORIZONS,
        confidence_pct: float = 95.0,
        seed: int | None = None,
    ) -> ForecastResult:
        """Forecast ``ticker`` from a Series of historical prices."""
        daily = pd.DataFrame({"close": prices})
        return self.forecast(ticker, daily, horizons, confidence_pct, seed)

    def _bootstrap_horizon(
        self,
        ticker: str,
        returns: pd.Series,
        current_price: float,
        horizon_days: int,
        confidence_level: float,
        seed: int,
    ) -> HorizonForecast:
        """Bootstrap one horizon and build its three scenarios."""
        rng = np.random.default_rng(seed)
        sample_idx = rng.integers(0, len(returns), size=(self.n_scenarios, horizon_days))
        sampled = returns.to_numpy()[sample_idx]
        cumulative = np.prod(1.0 + sampled, axis=1) - 1.0

        low_pct = (1.0 - confidence_level) * 100.0 / 2.0
        high_pct = 100.0 - low_pct
        pessimistic = float(np.percentile(cumulative, low_pct))
        base = float(np.median(cumulative))
        optimistic = float(np.percentile(cumulative, high_pct))

        return HorizonForecast(
            horizon_days=horizon_days,
            current_price=current_price,
            pessimistic=Scenario(price=current_price * (1.0 + pessimistic), return_pct=pessimistic * 100.0),
            base=Scenario(price=current_price * (1.0 + base), return_pct=base * 100.0),
            optimistic=Scenario(price=current_price * (1.0 + optimistic), return_pct=optimistic * 100.0),
        )


# Module-level convenience functions


def forecast(
    ticker: str,
    daily: pd.DataFrame,
    horizons: int | list[int] | tuple[int, ...] = DEFAULT_HORIZONS,
    confidence_pct: float = 95.0,
    seed: int = 42,
) -> ForecastResult:
    """Run a deterministic scenario forecast for one ticker."""
    engine = ForecastEngine(n_scenarios=1000, seed=seed)
    return engine.forecast(ticker, daily, horizons, confidence_pct)


def forecast_from_prices(
    ticker: str,
    prices: pd.Series,
    horizons: int | list[int] | tuple[int, ...] = DEFAULT_HORIZONS,
    confidence_pct: float = 95.0,
    seed: int = 42,
) -> ForecastResult:
    """Run a deterministic scenario forecast from a price Series."""
    engine = ForecastEngine(n_scenarios=1000, seed=seed)
    return engine.forecast_from_prices(ticker, prices, horizons, confidence_pct)


def format_forecast(result: ForecastResult) -> str:
    """Format a forecast result as a human-readable markdown table."""
    lines = [
        f"# Forecast: {result.symbol} (as of {result.as_of})",
        "",
        f"Current Price: {result.current_price:,.2f}",
        f"Method: {result.method} ({result.n_scenarios} scenarios, {result.confidence_level:.0%} confidence)",
        "",
    ]
    if result.warnings:
        for warning in result.warnings:
            lines.append(f"⚠ {warning}")
        lines.append("")
    if result.horizons:
        lines.extend(
            [
                "| Horizon | Scenario | Return | Price |",
                "|---------|----------|--------|-------|",
            ]
        )
        for hf in result.horizons:
            lines.append(f"| {hf.horizon_days}d | Pessimistic | {hf.pessimistic.return_pct:+.2f}% | {hf.pessimistic.price:,.2f} |")
            lines.append(f"| {hf.horizon_days}d | Base | {hf.base.return_pct:+.2f}% | {hf.base.price:,.2f} |")
            lines.append(f"| {hf.horizon_days}d | Optimistic | {hf.optimistic.return_pct:+.2f}% | {hf.optimistic.price:,.2f} |")
    return "\n".join(lines)


def forecast_engine_factory(n_scenarios: int = 1000, seed: int = 42) -> ForecastEngine:
    """Create a ForecastEngine instance with the given settings."""
    return ForecastEngine(n_scenarios=n_scenarios, seed=seed)

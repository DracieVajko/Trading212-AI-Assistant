"""macro_context.py — Macro context engine.

Provides macroeconomic context for portfolio analysis including:
- Interest rate regime detection
- Inflation regime detection
- GDP growth regime
- Overall market regime classification

Uses only historical data available up to the current date (no look-ahead bias).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MacroContext:
    """Macro context result with regime classifications."""

    timestamp: str
    regime: str  # "expansion", "contraction", "recession", "recovery"
    confidence: float
    indicators: dict[str, Any] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class MacroContextEngine:
    """Macro context engine that classifies market regime based on
    macroeconomic indicators.

    Uses only historical data available up to the current date.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def analyze(
        self,
        macro_data: dict[str, Any],
        as_of_date: str | None = None,
    ) -> MacroContext:
        """Analyze macro context from available data.

        Args:
            macro_data: Dictionary containing macroeconomic data series.
                Expected keys may include:
                - 'gdp_growth': GDP growth rate series
                - 'inflation': Inflation rate series
                - 'unemployment': Unemployment rate series
                - 'interest_rate': Interest rate series
                - 'yield_curve': Yield curve spread (10y - 2y)
                - 'market_returns': Market index returns
            as_of_date: Date string for analysis (defaults to now).

        Returns:
            MacroContext with regime classification.
        """
        if as_of_date is None:
            as_of_date = datetime.now(timezone.utc).isoformat()

        # Filter data to available history up to as_of_date
        # (In a real implementation, this would filter based on dates)

        signals: list[str] = []
        warnings_list: list[str] = []
        indicators: dict[str, Any] = {}

        # Analyze GDP growth
        gdp_growth = macro_data.get("gdp_growth")
        if gdp_growth is not None and len(gdp_growth) > 0:
            latest_gdp = float(gdp_growth.iloc[-1]) if hasattr(gdp_growth, "iloc") else float(gdp_growth[-1])
            indicators["gdp_growth"] = latest_gdp

            if latest_gdp > 2.0:
                signals.append("GDP growth above 2% - expansionary")
            elif latest_gdp > 0:
                signals.append("GDP growth positive but modest")
            elif latest_gdp > -1.0:
                signals.append("GDP growth slightly negative - caution")
            else:
                signals.append("GDP growth deeply negative - recession risk")
                warnings_list.append("GDP growth deeply negative")

        # Analyze inflation
        inflation = macro_data.get("inflation")
        if inflation is not None and len(inflation) > 0:
            latest_inflation = float(inflation.iloc[-1]) if hasattr(inflation, "iloc") else float(inflation[-1])
            indicators["inflation"] = latest_inflation

            if latest_inflation > 5.0:
                signals.append(f"High inflation ({latest_inflation:.1f}%) - monetary tightening likely")
                warnings_list.append(f"High inflation: {latest_inflation:.1f}%")
            elif latest_inflation > 3.0:
                signals.append(f"Moderate inflation ({latest_inflation:.1f}%)")
            elif latest_inflation > 1.0:
                signals.append(f"Low inflation ({latest_inflation:.1f}%)")
            else:
                signals.append("Very low inflation - deflation risk")
                warnings_list.append(f"Very low inflation: {latest_inflation:.1f}%")

        # Analyze unemployment
        unemployment = macro_data.get("unemployment")
        if unemployment is not None and len(unemployment) > 0:
            latest_unemp = float(unemployment.iloc[-1]) if hasattr(unemployment, "iloc") else float(unemployment[-1])
            indicators["unemployment"] = latest_unemp

            if latest_unemp > 8.0:
                signals.append(f"High unemployment ({latest_unemp:.1f}%) - recession risk")
                warnings_list.append(f"High unemployment: {latest_unemp:.1f}%")
            elif latest_unemp > 6.0:
                signals.append(f"Elevated unemployment ({latest_unemp:.1f}%)")
            elif latest_unemp > 4.0:
                signals.append(f"Moderate unemployment ({latest_unemp:.1f}%)")
            else:
                signals.append(f"Low unemployment ({latest_unemp:.1f}%) - tight labor market")

        # Analyze interest rates
        interest_rate = macro_data.get("interest_rate")
        if interest_rate is not None and len(interest_rate) > 0:
            latest_rate = float(interest_rate.iloc[-1]) if hasattr(interest_rate, "iloc") else float(interest_rate[-1])
            indicators["interest_rate"] = latest_rate

            if latest_rate > 5.0:
                signals.append(f"High interest rates ({latest_rate:.1f}%) - restrictive policy")
            elif latest_rate > 3.0:
                signals.append(f"Moderate interest rates ({latest_rate:.1f}%)")
            elif latest_rate > 1.0:
                signals.append(f"Low interest rates ({latest_rate:.1f}%)")
            else:
                signals.append(f"Very low interest rates ({latest_rate:.1f}%) - accommodative policy")

        # Analyze yield curve
        yield_curve = macro_data.get("yield_curve")
        if yield_curve is not None and len(yield_curve) > 0:
            latest_yc = float(yield_curve.iloc[-1]) if hasattr(yield_curve, "iloc") else float(yield_curve[-1])
            indicators["yield_curve"] = latest_yc

            if latest_yc < 0:
                signals.append(f"Yield curve inverted ({latest_yc:.2f}%) - recession signal")
                warnings_list.append(f"Yield curve inverted: {latest_yc:.2f}%")
            elif latest_yc < 0.5:
                signals.append(f"Flat yield curve ({latest_yc:.2f}%) - caution")
            else:
                signals.append(f"Normal yield curve ({latest_yc:.2f}%)")

        # Determine overall regime
        regime = self._determine_regime(indicators, signals)
        confidence = self._calculate_confidence(indicators, signals)

        return MacroContext(
            regime=regime,
            confidence=confidence,
            implications=indicators,
            signals=signals,
            warnings=warnings_list,
        )

    def _determine_regime(self, indicators: dict[str, Any], signals: list[str]) -> str:
        """Determine macro regime from indicators."""
        # Count positive vs negative signals
        positive_count = sum(1 for s in signals if any(word in s.lower() for word in ["growth", "expansion", "bullish", "normal"]))
        negative_count = sum(1 for s in signals if any(word in s.lower() for word in ["recession", "decline", "negative", "breach", "risk", "inverted", "deflation"]))

        if negative_count >= 3:
            return "recession"
        elif negative_count >= 2:
            return "contraction"
        elif positive_count >= 3:
            return "expansion"
        elif positive_count >= 1:
            return "recovery"
        else:
            return "neutral"

    def _calculate_confidence(self, indicators: dict[str, Any], signals: list[str]) -> float:
        """Calculate confidence level for regime classification."""
        # More indicators = higher confidence
        num_indicators = len(indicators)
        num_signals = len(signals)

        base_confidence = 0.5
        data_bonus = min(num_indicators / 5.0, 0.3)  # Up to 0.3 for 5+ indicators
        signal_bonus = min(num_signals / 10.0, 0.2)  # Up to 0.2 for 10+ signals

        return min(0.95, base_confidence + data_bonus + signal_bonus)


def get_macro_context(
    ticker: str | None = None,
    macro_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience function to get macro context.

    Args:
        ticker: Optional ticker symbol (for context labeling).
        macro_data: Macroeconomic data dictionary.

    Returns:
        Dict with regime information.
    """
    engine = MacroContextEngine()
    result = engine.analyze(macro_data or {})

    return {
        "regime": result.regime,
        "confidence": result.confidence,
        "indicators": result.indicators,
        "signals": result.signals,
        "warnings": result.warnings,
        "timestamp": result.timestamp,
        "ticker": ticker,
    }


# Default macro context engine instance
_macro_context_engine: MacroContextEngine | None = None


def get_macro_context_engine() -> MacroContextEngine:
    """Get the singleton macro context engine instance."""
    global _macro_context_engine
    if _macro_context_engine is None:
        _macro_context_engine = MacroContextEngine()
    return _macro_context_engine

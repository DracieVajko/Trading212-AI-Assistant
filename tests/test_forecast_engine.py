from __future__ import annotations

import pandas as pd
import numpy as np

from investment_engine.research.forecast_engine import forecast, format_forecast


def _make_frame(n=100):
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    close = np.clip(close, 10, 500)
    return pd.DataFrame({"close": close})


def test_forecast_basic():
    frame = _make_frame(100)
    result = forecast("AAPL", frame)
    assert result.symbol == "AAPL"
    assert len(result.horizons) > 0
    for hf in result.horizons:
        assert hf.current_price > 0
        assert hf.pessimistic.price > 0
        assert hf.base.price > 0
        assert hf.optimistic.price > 0
        assert hf.pessimistic.price <= hf.base.price <= hf.optimistic.price


def test_forecast_insufficient_data():
    frame = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
    result = forecast("AAPL", frame)
    assert len(result.horizons) == 0
    assert result.warnings


def test_forecast_empty_frame():
    result = forecast("AAPL", pd.DataFrame())
    assert len(result.horizons) == 0
    assert result.warnings


def test_format_forecast():
    frame = _make_frame(100)
    result = forecast("AAPL", frame)
    text = format_forecast(result)
    assert "AAPL" in text
    assert "Pessimistic" in text
    assert "Base" in text
    assert "Optimistic" in text


def test_forecast_deterministic():
    frame = _make_frame(100)
    r1 = forecast("AAPL", frame, seed=42)
    r2 = forecast("AAPL", frame, seed=42)
    assert r1.horizons[0].base.price == r2.horizons[0].base.price

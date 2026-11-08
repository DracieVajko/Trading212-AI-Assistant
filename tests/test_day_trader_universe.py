from __future__ import annotations

from pathlib import Path

from investment_engine.day_trader.config import DayTraderConfig
from investment_engine.day_trader.universe_builder import (
    build_universe_symbols,
    write_universe_file,
)


def test_build_universe_prioritises_extras_and_portfolio(monkeypatch):
    monkeypatch.setattr(
        "investment_engine.discovery.universe.build_universe",
        lambda **kwargs: ["AAPL", "MSFT"],
    )
    cfg = DayTraderConfig.from_mapping({
        "universe": {
            "extra_symbols": ["EXI2.DE", "0700.HK"],
            "include_portfolio": True,
            "include_sp500": True,
            "max_symbols": 10,
        }
    })
    symbols = build_universe_symbols(cfg, portfolio_symbols=["NVDA_US_EQ"])
    assert symbols[0] == "EXI2.DE"
    assert "NVDA" in symbols
    assert "AAPL" in symbols
    assert len(symbols) == len(set(symbols))


def test_build_universe_cap(monkeypatch):
    monkeypatch.setattr(
        "investment_engine.discovery.universe.build_universe",
        lambda **kwargs: ["AAPL", "MSFT", "NVDA", "AMZN", "META"],
    )
    cfg = DayTraderConfig.from_mapping({
        "universe": {"extra_symbols": ["EXI2.DE"], "max_symbols": 3}
    })
    symbols = build_universe_symbols(cfg, portfolio_symbols=None)
    assert len(symbols) == 3
    assert symbols[0] == "EXI2.DE"


def test_write_universe_file(tmp_path: Path):
    out = write_universe_file(["AAPL", "EXI2.DE"], tmp_path / "universe.txt")
    text = out.read_text(encoding="utf-8")
    assert "AAPL|AAPL" in text
    assert "EXI2.DE|EXI2.DE" in text

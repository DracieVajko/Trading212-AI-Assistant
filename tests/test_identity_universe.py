"""WP2 — Identity/universe/entity relevance.

Tests:
- research universe holdings reflect the full broker portfolio (PIE
  constituents + standalone + auto-discovered), not just config assets;
- company-name confirmation is conservative: unambiguous names confirm,
  ambiguous names ("Meta"/"AI") never confirm, missing names do not
  reactivate unsafe direct matching.
"""

from __future__ import annotations

from investment_engine.portfolio.symbols import confirm_content_entities
from investment_engine.research.universe import build_research_universe


# --------------------------------------------------------------------------
# Universe holdings
# --------------------------------------------------------------------------

def test_universe_holdings_include_broker_portfolio():
    """Holdings come from the passed universe, not a fixed config list."""
    broker_portfolio = [{"ticker": f"SYM{i}", "name": f"Company {i}"} for i in range(50)]
    universe = build_research_universe(
        broker_portfolio,
        settings_watchlist=["AAPL", "MSFT"],
        themes=["ai", "energy"],
        benchmarks=["EXI2.DE"],
        discovery=["NVDA"],
    )
    assert len(universe["holdings"]) == 50
    assert universe["watchlist"] == ["AAPL", "MSFT"]
    assert universe["themes"] == ["AI", "ENERGY"]
    assert universe["benchmarks"] == ["EXI2.DE"]
    assert universe["discovery"] == ["NVDA"]


def test_universe_holdings_dedupe():
    """Duplicate symbols across sources are deduplicated."""
    universe = build_research_universe(
        [{"ticker": "AAPL"}, {"broker_symbol": "AAPL"}, {"yahoo_symbol": "AAPL"}],
    )
    assert universe["holdings"] == ["AAPL"]


# --------------------------------------------------------------------------
# Conservative entity confirmation
# --------------------------------------------------------------------------

def test_symbol_whole_word_confirms_direct():
    confirmed, rel = confirm_content_entities(
        "Apple announces new product", "AAPL shares rose today.", "AAPL",
        names_map={"AAPL": "Apple"}, universe_symbols={"AAPL"})
    assert confirmed == ["AAPL"]
    assert rel == "direct"


def test_unambiguous_company_name_confirms():
    """An unambiguous company name maps to exactly one universe symbol."""
    confirmed, rel = confirm_content_entities(
        "Apple announces product launch event for Oct. 28",
        "Analysts expect touchscreen laptop.", "AAPL",
        names_map={"AAPL": "Apple"}, universe_symbols={"AAPL"})
    assert confirmed == ["AAPL"]
    assert rel == "direct"


def test_ambiguous_name_never_confirms():
    """A name mapping to multiple symbols must not be confirmed."""
    confirmed, rel = confirm_content_entities(
        "Meta metaverse partnership announced", "", "META",
        names_map={"META": "Meta", "METAX": "Meta"}, universe_symbols={"META", "METAX"})
    # Symbol "META" itself is confirmed by whole word; the *name* "Meta"
    # is ambiguous and must not add METAX.
    assert "METAX" not in confirmed
    assert rel in ("direct", "indirect")


def test_generic_term_not_confirmed():
    """Generic terms like 'AI'/'Meta' as names never confirm without a
    verified mapping to a single universe symbol."""
    confirmed, rel = confirm_content_entities(
        "AI and Meta lead the metaverse rally", "", "QQQ",
        names_map={"QQQ": "QQQ"}, universe_symbols={"QQQ"})
    assert confirmed == []
    assert rel == "indirect"  # queried symbol QQQ present but not in content


def test_missing_name_is_unconfirmed_not_related():
    """Content with no matching entity stays unconfirmed (never 'unrelated')."""
    confirmed, rel = confirm_content_entities(
        "Broad market rally continues", "", "AAPL",
        names_map={"AAPL": "Apple"}, universe_symbols={"AAPL"})
    assert confirmed == []
    assert rel == "indirect"


def test_no_names_map_falls_back_to_symbol_only():
    """Without a names map, only the queried symbol is confirmable."""
    confirmed, rel = confirm_content_entities(
        "Apple announces product launch", "", "AAPL",
        names_map=None, universe_symbols={"AAPL"})
    # Symbol AAPL not in content; no names map -> nothing confirmed.
    assert confirmed == []
    assert rel == "indirect"


def test_universe_symbol_name_pair_confirm():
    """When the queried symbol is absent but an unambiguous company name is
    present, the symbol is confirmed from the name."""
    confirmed, rel = confirm_content_entities(
        "Apple beats earnings estimates", "", "AAPL",
        names_map={"AAPL": "Apple"}, universe_symbols={"AAPL"})
    assert "AAPL" in confirmed
    assert rel == "direct"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
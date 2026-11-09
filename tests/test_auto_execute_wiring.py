def test_normalize_ticket_list_and_tool_input():
    from investment_engine.day_trader.execute import normalize_ticket

    norm = normalize_ticket(
        "AAPL", [{"tool_input": {"symbol": "AAPL", "side": "buy", "qty": "1"}}]
    )
    assert norm is not None
    assert norm["ticker"] == "AAPL_US_EQ"
    assert norm["side"] == "BUY"
    assert norm["quantity"] == 1.0


def test_normalize_ticket_prefers_known_instrument():
    from investment_engine.day_trader.execute import normalize_ticket

    norm = normalize_ticket(
        "AAOI",
        {"symbol": "AAOI", "side": "buy", "qty": "2"},
        {"AAOI": "AAOI_US_EQ"},
    )
    assert norm is not None
    assert norm["ticker"] == "AAOI_US_EQ"
    assert norm["quantity"] == 2.0


def test_normalize_ticket_rejects_eu_suffix_without_mapping():
    from investment_engine.day_trader.execute import normalize_ticket

    assert normalize_ticket("EXI2.DE", {"symbol": "EXI2.DE", "side": "buy", "qty": "1"}) is None


def test_normalize_ticket_invalid_qty():
    from investment_engine.day_trader.execute import normalize_ticket

    assert normalize_ticket("AAPL", {"symbol": "AAPL", "side": "buy", "qty": "nope"}) is None

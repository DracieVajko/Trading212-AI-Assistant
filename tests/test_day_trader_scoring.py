def test_scoring_short_term_profitable_trade():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "AAPL",
        "side": "BUY",
        "entry_price": 150.0,
        "exit_price": 155.0,
        "executed_at": "2026-11-09T09:30:00Z",
        "closed_at": "2026-11-09T10:00:00Z",
        "pnl_eur": 45.0,
        "fx_fee_eur": 0.50,
        "stop_loss_adhered": True,
        "risk_reward_ratio": 2.0,
    }
    result = score_demo_trade(trade)
    assert result.horizon == "short"
    assert result.score > 0
    assert result.breakdown["pnl_component"] > 0
    assert result.breakdown["stop_loss_component"] > 0


def test_scoring_medium_term_trade():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "MSFT", "side": "BUY",
        "executed_at": "2026-11-01T09:30:00Z",
        "closed_at": "2026-11-10T09:30:00Z",
        "pnl_eur": 20.0, "fx_fee_eur": 1.0,
        "stop_loss_adhered": True, "risk_reward_ratio": 1.5,
    }
    result = score_demo_trade(trade)
    assert result.horizon == "medium"


def test_scoring_long_term_trade():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "NVDA", "side": "BUY",
        "executed_at": "2026-09-01T09:30:00Z",
        "closed_at": "2026-11-09T09:30:00Z",
        "pnl_eur": 120.0, "fx_fee_eur": 2.0,
        "stop_loss_adhered": True, "risk_reward_ratio": 2.5,
    }
    result = score_demo_trade(trade)
    assert result.horizon == "long"


def test_scoring_stop_loss_violation_penalty():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "TSLA", "side": "BUY",
        "executed_at": "2026-11-09T09:30:00Z",
        "closed_at": "2026-11-09T15:00:00Z",
        "pnl_eur": -50.0, "fx_fee_eur": 1.0,
        "stop_loss_adhered": False, "risk_reward_ratio": 1.0,
    }
    result = score_demo_trade(trade)
    assert result.breakdown["stop_loss_component"] < 0
    assert result.score < 0


def test_scoring_fx_fee_reduces_net_pnl():
    from investment_engine.day_trader.scoring import score_demo_trade
    trade = {
        "symbol": "AAPL", "side": "BUY",
        "executed_at": "2026-11-09T09:30:00Z",
        "closed_at": "2026-11-09T10:00:00Z",
        "pnl_eur": 10.0, "fx_fee_eur": 3.0,
        "stop_loss_adhered": True, "risk_reward_ratio": 2.0,
    }
    result = score_demo_trade(trade)
    assert result.breakdown["net_pnl_eur"] == 7.0

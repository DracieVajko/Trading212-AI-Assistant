def test_score_closed_trades_appends_jsonl(tmp_path, monkeypatch):
    from investment_engine.day_trader import score_closed_trades as sct
    monkeypatch.setattr(sct, "SCORES_PATH", tmp_path / "scores.jsonl")
    trades = [
        {"symbol": "AAPL", "side": "BUY", "executed_at": "2026-11-09T09:30:00Z",
         "closed_at": "2026-11-09T10:00:00Z", "pnl_eur": 45.0, "fx_fee_eur": 0.5,
         "stop_loss_adhered": True, "risk_reward_ratio": 2.0},
    ]
    out = sct.score_closed_demo_trades(trades)
    assert len(out) == 1
    assert out[0]["horizon"] == "short"
    lines = (tmp_path / "scores.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_score_closed_trades_empty_returns_empty(tmp_path, monkeypatch):
    from investment_engine.day_trader import score_closed_trades as sct
    monkeypatch.setattr(sct, "SCORES_PATH", tmp_path / "scores.jsonl")
    assert sct.score_closed_demo_trades([]) == []
    assert not (tmp_path / "scores.jsonl").exists()

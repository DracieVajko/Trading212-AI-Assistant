import json


def _trade(symbol="AAPL", **overrides):
    trade = {"symbol": symbol, "side": "BUY", "executed_at": "2026-11-09T09:30:00Z",
             "closed_at": "2026-11-09T10:00:00Z", "pnl_eur": 45.0, "fx_fee_eur": 0.5,
             "stop_loss_adhered": True, "risk_reward_ratio": 2.0}
    trade.update(overrides)
    return trade


def test_score_closed_trades_appends_jsonl(tmp_path, monkeypatch):
    from investment_engine.day_trader import score_closed_trades as sct
    monkeypatch.setattr(sct, "SCORES_PATH", tmp_path / "scores.jsonl")
    out = sct.score_closed_demo_trades([_trade()])
    assert len(out) == 1
    assert out[0]["demo_score"]["horizon"] == "short"
    lines = (tmp_path / "scores.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_score_closed_trades_empty_returns_empty(tmp_path, monkeypatch):
    from investment_engine.day_trader import score_closed_trades as sct
    monkeypatch.setattr(sct, "SCORES_PATH", tmp_path / "scores.jsonl")
    assert sct.score_closed_demo_trades([]) == []
    assert not (tmp_path / "scores.jsonl").exists()


def test_score_fields_are_namespaced_under_demo_score(tmp_path, monkeypatch):
    from investment_engine.day_trader import score_closed_trades as sct
    monkeypatch.setattr(sct, "SCORES_PATH", tmp_path / "scores.jsonl")
    out = sct.score_closed_demo_trades([_trade(score=87.5, horizon="swing")])
    row = out[0]
    # Trade provenance is preserved at the top level.
    assert row["score"] == 87.5
    assert row["horizon"] == "swing"
    # Computed score data lives under its own namespace.
    assert row["demo_score"]["horizon"] == "short"
    assert isinstance(row["demo_score"]["score"], float)
    assert row["demo_score"]["score"] != 87.5


def test_same_trade_is_not_persisted_twice(tmp_path, monkeypatch):
    from investment_engine.day_trader import score_closed_trades as sct
    monkeypatch.setattr(sct, "SCORES_PATH", tmp_path / "scores.jsonl")
    trade = _trade()
    sct.score_closed_demo_trades([trade])
    sct.score_closed_demo_trades([trade])
    lines = (tmp_path / "scores.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    sct.score_closed_demo_trades([_trade(symbol="MSFT")])
    lines = (tmp_path / "scores.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_persisted_line_is_parseable_and_kwarg_path(tmp_path):
    from investment_engine.day_trader import score_closed_trades as sct
    path = tmp_path / "nested" / "scores.jsonl"
    sct.score_closed_demo_trades([_trade()], scores_path=path)
    assert path.exists()
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert isinstance(row["demo_score"]["score"], (int, float))
    assert row["demo_score"]["horizon"] == "short"
    # Appending a distinct trade to an existing file yields two lines.
    sct.score_closed_demo_trades([_trade(symbol="MSFT")], scores_path=path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_malformed_existing_lines_are_ignored(tmp_path):
    from investment_engine.day_trader import score_closed_trades as sct
    path = tmp_path / "scores.jsonl"
    path.write_text("not json at all\n{broken\n", encoding="utf-8")
    sct.score_closed_demo_trades([_trade()], scores_path=path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    row = json.loads(lines[-1])
    assert row["demo_score"]["horizon"] == "short"

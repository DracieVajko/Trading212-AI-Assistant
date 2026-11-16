"""Demo trade feedback: closed-trade pairing, scoring, prompt block."""
from __future__ import annotations

import json

from investment_engine.day_trader import demo_feedback as fb


def _order(side, qty, price, when, otype="market", ticker="CMCSA_US_EQ", oid=1):
    return {
        "id": oid,
        "ticker": ticker,
        "side": side,
        "filledQuantity": qty,
        "price": price,
        "type": otype,
        "dateExecuted": when,
    }


def test_normalize_orders_handles_signed_quantity():
    rows = fb.normalize_orders([_order("", -2, 10.0, "2026-11-16T15:00:00Z")])
    assert rows[0]["side"] == "SELL"
    assert rows[0]["quantity"] == 2


def test_fifo_pairing_closes_a_stopped_trade():
    orders = fb.normalize_orders([
        _order("BUY", 35, 30.00, "2026-11-16T15:01:00Z", oid=1),
        _order("SELL", 35, 29.70, "2026-11-16T16:30:00Z", otype="stop", oid=2),
    ])
    closed = fb.closed_trades_from_orders(orders)

    assert len(closed) == 1
    row = closed[0]
    assert row["symbol"] == "CMCSA_US_EQ"
    assert row["stop_loss_adhered"] is True
    assert row["pnl_eur"] < 0


def test_partial_sell_keeps_remainder_open():
    orders = fb.normalize_orders([
        _order("BUY", 10, 20.0, "2026-11-16T15:00:00Z", oid=1),
        _order("SELL", 4, 21.0, "2026-11-16T16:00:00Z", oid=2),
    ])
    closed = fb.closed_trades_from_orders(orders)

    assert len(closed) == 1
    assert closed[0]["quantity"] == 4
    assert closed[0]["pnl_eur"] == 4.0


def test_scores_are_persisted_and_feedback_block_mentions_loss(tmp_path):
    path = tmp_path / "scores.jsonl"
    orders = fb.normalize_orders([
        _order("BUY", 35, 30.00, "2026-11-16T15:01:00Z", oid=1),
        _order("SELL", 35, 29.70, "2026-11-16T16:30:00Z", otype="stop", oid=2),
    ])
    closed = fb.closed_trades_from_orders(orders)
    fb.score_closed_demo_trades(closed, scores_path=path)

    assert path.exists()
    block = fb.feedback_block(limit=5, path=path)
    assert "CMCSA_US_EQ" in block
    assert "negative" in block.lower()
    assert "score" in block.lower()


def test_feedback_block_empty_without_file(tmp_path):
    assert fb.feedback_block(limit=5, path=tmp_path / "missing.jsonl") == ""


def test_collect_never_raises_on_broken_client():
    class _Broken:
        def get_order_history(self, limit=50):
            raise RuntimeError("boom")

    assert fb.collect_and_score_demo_trades(_Broken()) == []


def test_scores_file_is_deduplicated(tmp_path):
    path = tmp_path / "scores.jsonl"
    orders = fb.normalize_orders([
        _order("BUY", 1, 10.0, "2026-11-16T15:00:00Z", oid=1),
        _order("SELL", 1, 11.0, "2026-11-16T16:00:00Z", oid=2),
    ])
    closed = fb.closed_trades_from_orders(orders)
    fb.score_closed_demo_trades(closed, scores_path=path)
    first = path.read_text(encoding="utf-8")
    fb.score_closed_demo_trades(closed, scores_path=path)
    second = path.read_text(encoding="utf-8")

    assert first == second
    assert len([l for l in second.splitlines() if l.strip()]) == 1

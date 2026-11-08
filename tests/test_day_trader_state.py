from __future__ import annotations

import json
from pathlib import Path

from investment_engine.day_trader.state import read_json, write_json


def test_state_recovers_corrupt(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert read_json(p, {"x": 1}) == {"x": 1}


def test_state_roundtrip(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"y": 2})
    assert read_json(p, None) == {"y": 2}

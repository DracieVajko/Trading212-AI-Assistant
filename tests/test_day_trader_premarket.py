from __future__ import annotations

from pathlib import Path

from investment_engine.day_trader.config import DayTraderConfig
from investment_engine.day_trader.premarket import run_premarket


def test_premarket_empty_watchlist(tmp_path: Path):
    class R:
        ok = True
        payload = {"hits": []}
        exit_code = 0
        stdout = ""
        stderr = ""
        duration_s = 0.0

    def fake_runner(script, args, timeout, json_mode, cwd, env):
        return R()

    cfg = DayTraderConfig()
    out = run_premarket(cfg, fake_runner, tmp_path)
    assert out["status"] in ("OK", "DEGRADED")
    assert out["watchlist"].get("hits") == []

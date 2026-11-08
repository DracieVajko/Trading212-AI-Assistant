from __future__ import annotations

from pathlib import Path

from investment_engine.day_trader.runner import run_tool


def test_runner_parses_json(tmp_path: Path):
    script = tmp_path / "tool.py"
    script.write_text("import json; print(json.dumps({'a': 42}))", encoding="utf-8")
    res = run_tool(script, [], 30, True, cwd=tmp_path)
    assert res.ok and res.payload == {"a": 42}


def test_runner_missing_script(tmp_path: Path):
    res = run_tool(tmp_path / "missing.py", [], 30, True, cwd=tmp_path)
    assert not res.ok and "not found" in res.stderr.lower()


def test_runner_offline_degraded(tmp_path: Path):
    script = tmp_path / "tool.py"
    script.write_text("import sys; sys.exit(1)", encoding="utf-8")
    res = run_tool(script, [], 30, True, cwd=tmp_path)
    assert not res.ok and res.exit_code == 1

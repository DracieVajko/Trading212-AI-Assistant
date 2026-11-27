"""Tests must never write into the operator's real stores.

Regression guard for the 2026-11-27 incident: a pytest run appended a fake
AAPL intent to data/day_trader/audit.db and fake PORTFOLIO decisions to
history/history.db + history/{demo,live}/decisions.jsonl.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_HISTORY_ROOT = PROJECT_ROOT / "history"
REAL_HISTORY_DB = REAL_HISTORY_ROOT / "history.db"
REAL_AUDIT_DB = PROJECT_ROOT / "data" / "day_trader" / "audit.db"


def test_run_branch_never_uses_production_history(monkeypatch):
    import sqlite3

    from investment_engine import branches, history
    from investment_engine.config.settings import EngineSettings

    violations: list[str] = []
    real_db = REAL_HISTORY_DB.resolve()
    real_root = REAL_HISTORY_ROOT.resolve()

    original_sqlite_connect = sqlite3.connect

    def spy_connect(database, *args, **kwargs):
        try:
            if Path(database).resolve() == real_db:
                violations.append("history.db")
        except (TypeError, ValueError):
            pass
        return original_sqlite_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy_connect)

    original_append = history._append_jsonl

    def spy_append(path, payload):
        if Path(path).resolve().is_relative_to(real_root):
            violations.append("decisions.jsonl")
            raise AssertionError("production decisions.jsonl used from a test")
        return original_append(path, payload)

    monkeypatch.setattr(history, "_append_jsonl", spy_append)
    monkeypatch.setattr(
        "investment_engine.main.run_engine",
        lambda *args, **kwargs: {"status": "OK"},
        raising=True,
    )
    monkeypatch.setattr(
        branches, "demo_snapshot", lambda: {"status": "ok", "source": "t212_demo"}
    )

    branches.run_branch("demo", [], EngineSettings(), run_id="isolation-test")

    assert violations == []


def test_production_audit_db_is_forbidden_from_tests():
    import sqlite3

    # conftest's guard must reject this before any file handle is opened.
    with pytest.raises(AssertionError, match="production audit.db"):
        sqlite3.connect(str(REAL_AUDIT_DB))

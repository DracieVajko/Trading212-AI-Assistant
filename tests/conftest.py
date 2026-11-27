"""pytest bootstrap: make the project root importable (entry point + v4_hardening)."""
import sqlite3
import sys
from pathlib import Path

import pytest

# Never collect auto-backup copies (*_V2415_*): they duplicate old tests and
# can write to the permanent history store.
collect_ignore_glob = ["*_V2415_*.py"]

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolated_order_ledger(tmp_path, monkeypatch):
    """Keep the order ledger away from the real history store.

    The ledger blocks an order when the same symbol+side was already traded
    today. Tests must never be blocked (or silently unblocked) by what the
    operator traded on this machine, so each test gets an empty history root.
    """
    from investment_engine import order_ledger

    root = tmp_path / "ledger_history"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(order_ledger, "HISTORY_ROOT", root)
    yield root


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    """Redirect every history write to a per-test directory.

    ``history.DB_PATH`` is bound as a default argument at import time, so
    monkeypatching the constant alone is not enough: wrap ``_connect`` and
    redirect the real default path. JSONL files use ``HISTORY_ROOT``.
    """
    from investment_engine import history

    root = tmp_path / "history"
    root.mkdir(parents=True, exist_ok=True)
    real_db = history.DB_PATH.resolve()
    original_connect = history._connect

    def _connect(db_path=history.DB_PATH):
        if Path(db_path).resolve() == real_db:
            db_path = root / "history.db"
        return original_connect(db_path)

    monkeypatch.setattr(history, "HISTORY_ROOT", root)
    monkeypatch.setattr(history, "_connect", _connect)
    yield root


@pytest.fixture(autouse=True)
def _forbid_real_dbs(monkeypatch):
    """Fail loudly if a test tries to open any of the operator's real DBs."""
    protected = {
        (ROOT / "data" / "day_trader" / "audit.db").resolve(): "audit.db",
        (ROOT / "history" / "history.db").resolve(): "history.db",
    }
    original_connect = sqlite3.connect

    def _connect(database, *args, **kwargs):
        try:
            name = protected.get(Path(database).resolve())
        except (TypeError, ValueError):
            name = None
        if name:
            raise AssertionError(
                f"production {name} must not be used in tests; "
                "pass a tmp_path-based db_path"
            )
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _connect)

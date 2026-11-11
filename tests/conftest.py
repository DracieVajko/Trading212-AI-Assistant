"""pytest bootstrap: make the project root importable (entry point + v4_hardening)."""
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

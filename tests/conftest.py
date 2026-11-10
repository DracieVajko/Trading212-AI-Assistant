"""pytest bootstrap: make the project root importable (entry point + v4_hardening)."""
import sys
from pathlib import Path

# Never collect auto-backup copies (*_V2415_*): they duplicate old tests and
# can write to the permanent history store.
collect_ignore_glob = ["*_V2415_*.py"]

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

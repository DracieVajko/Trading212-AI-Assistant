"""State management for the day-trader pack."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def ensure_state_root(root: str | Path) -> Path:
    """Create the state root and the external tools' trader/ folder."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "trader").mkdir(parents=True, exist_ok=True)
    (root / "trader" / "state").mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    return root


def read_json(path: str | Path, default: Any = None) -> Any:
    """Read JSON; return default on missing or corrupt (after quarantining)."""
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        try:
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            path.rename(path.with_suffix(path.suffix + f".corrupt-{stamp}"))
        except OSError:
            pass
        return default


def write_json(path: str | Path, payload: Any) -> None:
    """Write JSON, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def archive_session(root: str | Path, run_id: str) -> None:
    """Copy the current trader/ state into sessions/<run_id>/."""
    root = Path(root)
    src = root / "trader"
    dst = root / "sessions" / run_id
    if not src.is_dir():
        return
    try:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    except OSError:
        pass

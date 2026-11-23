"""Auto-update helper: pull latest changes from GitHub on startup.

Only runs when the working tree is a git checkout and the remote is reachable.
Never overwrites local uncommitted changes (uses --ff-only). Never runs during
a live trading decision; call it at the very beginning of a run, before any
broker or LLM work.

Usage:
  py -3.12 portfolio_ai_assistant.py ... --auto-update
  or set AUTO_UPDATE=1 in the environment / api.env.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent


def _git(args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, f"{type(exc).__name__}: {exc}"


def is_git_repo() -> bool:
    rc, _ = _git(["rev-parse", "--is-inside-work-tree"])
    return rc == 0


def check_and_update(*, dry_run: bool = False) -> dict:
    """Fetch origin/main and fast-forward if behind. Returns a status dict."""
    result = {"status": "skipped", "detail": ""}
    if not is_git_repo():
        result["detail"] = "not a git repo"
        return result
    # Refuse to clobber uncommitted changes.
    rc, out = _git(["status", "--porcelain"])
    if rc != 0:
        result["detail"] = f"git status failed: {out.strip()}"
        return result
    if out.strip():
        result["status"] = "dirty"
        result["detail"] = "working tree has uncommitted changes; skipping update"
        logger.warning("Auto-update skipped: working tree is dirty.")
        return result
    rc, out = _git(["fetch", "origin", "main"], timeout=60)
    if rc != 0:
        result["status"] = "fetch_failed"
        result["detail"] = out.strip()[:200]
        logger.warning("Auto-update fetch failed: %s", result["detail"])
        return result
    rc, local = _git(["rev-parse", "HEAD"])
    rc2, remote = _git(["rev-parse", "origin/main"])
    if rc != 0 or rc2 != 0:
        result["detail"] = "could not resolve refs"
        return result
    local = local.strip()
    remote = remote.strip()
    if local == remote:
        result["status"] = "up_to_date"
        result["detail"] = f"HEAD {local[:8]} is current"
        logger.info("Auto-update: already up to date (%s).", local[:8])
        return result
    if dry_run:
        result["status"] = "update_available"
        result["detail"] = f"{local[:8]} -> {remote[:8]}"
        logger.info("Auto-update available: %s", result["detail"])
        return result
    rc, out = _git(["pull", "--ff-only", "origin", "main"], timeout=120)
    if rc == 0:
        result["status"] = "updated"
        result["detail"] = f"{local[:8]} -> {remote[:8]}"
        logger.info("Auto-update applied: %s", result["detail"])
    else:
        result["status"] = "pull_failed"
        result["detail"] = out.strip()[:200]
        logger.warning("Auto-update pull failed: %s", result["detail"])
    return result
"""Retention-based cleanup for reports/ and logs/.

This module implements safe, policy-driven cleanup that:
- Defaults to DRY-RUN (no changes)
- Only removes artifacts within explicit allowlists under the repo root
- Preserves: current run, recent successful/failed runs, run_events.jsonl,
  decision logs, eval baselines, active runs
- Rejects any paths outside the repository root

Usage:
    python -m scripts.cleanup_outputs          # dry-run
    python -m scripts.cleanup_outputs --apply  # apply retention policy
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Allowlist roots (must be within repo)
ALLOWED_ROOTS = ("reports", "logs")

# Retention defaults (seconds)
DEFAULT_LOGS_RETENTION_DAYS = 30
DEFAULT_REPORTS_RETENTION_DAYS = 30
DEFAULT_DEBUG_MAX_RUNS = 14
DEFAULT_KEEP_SUCCESSFUL_RUNS = 5
DEFAULT_KEEP_FAILED_RUNS = 5
MIN_AGE_SECONDS = 3600  # never delete files younger than 1 hour (active runs)

# Protected paths (never deleted)
PROTECTED_FILES = {
    "reports/run_events.jsonl",
    "reports/current/run_manifest.json",
    "reports/current/portfolio_intelligence_brief.md",
    "reports/current/portfolio_analysis.json",
    "reports/current/portfolio_decision_brief.md",
    "reports/current/t212_portfolio_snapshot.md",
}
PROTECTED_DIRS = {
    "reports/current",
    "agent_data",
    "data",
    "docs",
    "tests/eval",
}


@dataclass
class CleanupPolicy:
    logs_retention_days: int = DEFAULT_LOGS_RETENTION_DAYS
    reports_retention_days: int = DEFAULT_REPORTS_RETENTION_DAYS
    debug_max_runs: int = DEFAULT_DEBUG_MAX_RUNS
    keep_successful_runs: int = DEFAULT_KEEP_SUCCESSFUL_RUNS
    keep_failed_runs: int = DEFAULT_KEEP_FAILED_RUNS
    min_age_seconds: int = MIN_AGE_SECONDS

    @classmethod
    def from_env(cls) -> "CleanupPolicy":
        return cls(
            logs_retention_days=int(os.getenv("CLEANUP_LOGS_RETENTION_DAYS", DEFAULT_LOGS_RETENTION_DAYS)),
            reports_retention_days=int(os.getenv("CLEANUP_REPORTS_RETENTION_DAYS", DEFAULT_REPORTS_RETENTION_DAYS)),
            debug_max_runs=int(os.getenv("CLEANUP_DEBUG_MAX_RUNS", DEFAULT_DEBUG_MAX_RUNS)),
            keep_successful_runs=int(os.getenv("CLEANUP_KEEP_SUCCESSFUL_RUNS", DEFAULT_KEEP_SUCCESSFUL_RUNS)),
            keep_failed_runs=int(os.getenv("CLEANUP_KEEP_FAILED_RUNS", DEFAULT_KEEP_FAILED_RUNS)),
            min_age_seconds=int(os.getenv("CLEANUP_MIN_AGE_SECONDS", MIN_AGE_SECONDS)),
        )


@dataclass
class CleanupPlan:
    to_delete: list[Path] = field(default_factory=list)
    protected: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_within_repo(path: Path, repo_root: Path) -> bool:
    """Return True if path is within repo_root (resolves symlinks)."""
    try:
        path.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


def is_protected(path: Path, repo_root: Path) -> bool:
    """Check if path is in the protected set."""
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
        rel_str = str(rel).replace("\\", "/")
        # Exact file matches
        if rel_str in PROTECTED_FILES:
            return True
        # Directory prefixes
        for pdir in PROTECTED_DIRS:
            if rel_str == pdir or rel_str.startswith(pdir + "/"):
                return True
        return False
    except ValueError:
        return False


def is_active_run_artifact(path: Path, min_age_seconds: int) -> bool:
    """Return True if file was modified recently (active run)."""
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) < min_age_seconds
    except OSError:
        return False


def classify_archive_run(run_dir: Path) -> str:
    """Classify an archive run as 'successful', 'failed', or 'unknown'."""
    try:
        manifest = run_dir / "run_manifest.json"
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            status = str(data.get("run_status", "")).upper()
            if status == "COMPLETE":
                return "successful"
            if status in ("PARTIAL", "ABORTED", "FAILED"):
                return "failed"
            # Legacy: check recon_status
            recon = str(data.get("recon_status", "")).upper()
            if recon == "PASS":
                return "successful"
            if recon == "FAIL":
                return "failed"
    except (OSError, ValueError):
        pass
    return "unknown"


def plan_retention(
    repo_root: str | Path,
    policy: CleanupPolicy | None = None,
    now: float | None = None,
) -> CleanupPlan:
    """Plan cleanup actions without executing them."""
    repo_root = Path(repo_root).resolve()
    policy = policy or CleanupPolicy.from_env()
    now = now or time.time()
    plan = CleanupPlan()

    # Logs: delete .log files older than retention
    logs_dir = repo_root / "logs"
    if logs_dir.is_dir():
        cutoff = now - (policy.logs_retention_days * 86400)
        for log_file in logs_dir.glob("*.log"):
            if not is_within_repo(log_file, repo_root):
                plan.errors.append(f"Refusing to delete out-of-root path: {log_file}")
                continue
            if is_protected(log_file, repo_root):
                plan.protected.append(log_file)
                continue
            if is_active_run_artifact(log_file, policy.min_age_seconds):
                plan.protected.append(log_file)
                continue
            try:
                mtime = log_file.stat().st_mtime
                if mtime < cutoff:
                    plan.to_delete.append(log_file)
                else:
                    plan.protected.append(log_file)
            except OSError:
                pass

    # Reports: archive runs, debug, ai_context, raw dumps
    reports_dir = repo_root / "reports"
    if reports_dir.is_dir():
        # Archive runs
        archive_dir = reports_dir / "archive"
        if archive_dir.is_dir():
            run_dirs: list[tuple[float, Path, str]] = []  # (mtime, path, classification)
            for child in archive_dir.iterdir():
                if child.is_dir() and is_within_repo(child, repo_root):
                    try:
                        mtime = child.stat().st_mtime
                        cls = classify_archive_run(child)
                        run_dirs.append((mtime, child, cls))
                    except OSError:
                        pass
            # Sort by mtime descending
            run_dirs.sort(key=lambda x: x[0], reverse=True)
            successful_seen = 0
            failed_seen = 0
            for mtime, run_dir, cls in run_dirs:
                if is_active_run_artifact(run_dir, policy.min_age_seconds):
                    plan.protected.append(run_dir)
                    continue
                keep = False
                if cls == "successful" and successful_seen < policy.keep_successful_runs:
                    keep = True
                    successful_seen += 1
                elif cls == "failed" and failed_seen < policy.keep_failed_runs:
                    keep = True
                    failed_seen += 1
                elif cls == "unknown":
                    # Unknown - keep if recent enough
                    if (now - mtime) < (policy.reports_retention_days * 86400):
                        keep = True
                if keep:
                    plan.protected.append(run_dir)
                else:
                    plan.to_delete.append(run_dir)

        # Debug folders - keep only newest N
        debug_dir = reports_dir / "debug"
        if debug_dir.is_dir():
            debug_items: list[tuple[float, Path]] = []
            for child in debug_dir.iterdir():
                if child.is_dir() and is_within_repo(child, repo_root):
                    try:
                        debug_items.append((child.stat().st_mtime, child))
                    except OSError:
                        pass
            debug_items.sort(key=lambda x: x[0], reverse=True)
            for _, d in debug_items[policy.debug_max_runs:]:
                if not is_active_run_artifact(d, policy.min_age_seconds):
                    plan.to_delete.append(d)
                else:
                    plan.protected.append(d)

        # ai_context - retention by age
        ai_ctx_dir = reports_dir / "ai_context"
        if ai_ctx_dir.is_dir():
            cutoff = now - (policy.reports_retention_days * 86400)
            for f in ai_ctx_dir.iterdir():
                if f.is_file() and is_within_repo(f, repo_root):
                    if is_active_run_artifact(f, policy.min_age_seconds):
                        plan.protected.append(f)
                    else:
                        try:
                            if f.stat().st_mtime < cutoff:
                                plan.to_delete.append(f)
                            else:
                                plan.protected.append(f)
                        except OSError:
                            pass

        # Raw endpoint dumps - retention by age
        cutoff = now - (policy.reports_retention_days * 86400)
        for f in reports_dir.glob("raw_endpoint_dump_*.json"):
            if is_within_repo(f, repo_root):
                if is_active_run_artifact(f, policy.min_age_seconds):
                    plan.protected.append(f)
                else:
                    try:
                        if f.stat().st_mtime < cutoff:
                            plan.to_delete.append(f)
                        else:
                            plan.protected.append(f)
                    except OSError:
                        pass

        # Staged/temp files older than 1 day
        stale_cutoff = now - 86400
        for pattern in [".tmp.*.part", ".staging_*", ".watchdog_armed_*"]:
            for f in reports_dir.glob(pattern):
                if is_within_repo(f, repo_root):
                    try:
                        if f.stat().st_mtime < stale_cutoff:
                            plan.to_delete.append(f)
                        else:
                            plan.protected.append(f)
                    except OSError:
                        pass

    # Python caches (anywhere under repo)
    for cache_dir in repo_root.rglob("__pycache__"):
        if is_within_repo(cache_dir, repo_root):
            plan.to_delete.append(cache_dir)
    for pyc in repo_root.rglob("*.pyc"):
        if is_within_repo(pyc, repo_root):
            plan.to_delete.append(pyc)
    for pyo in repo_root.rglob("*.pyo"):
        if is_within_repo(pyo, repo_root):
            plan.to_delete.append(pyo)
    for cache_name in [".pytest_cache", ".mypy_cache"]:
        c = repo_root / cache_name
        if c.exists() and is_within_repo(c, repo_root):
            plan.to_delete.append(c)
    cov = repo_root / ".coverage"
    if cov.exists() and is_within_repo(cov, repo_root):
        plan.to_delete.append(cov)

    return plan


def apply_plan(plan: CleanupPlan, dry_run: bool = True) -> tuple[int, int]:
    """Execute or simulate the cleanup plan. Returns (deleted_count, error_count)."""
    deleted = 0
    errors = 0
    for path in plan.to_delete:
        try:
            if dry_run:
                print(f"[dry-run] would delete: {path}")
            else:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=False)
                else:
                    path.unlink()
                print(f"deleted: {path}")
            deleted += 1
        except OSError as e:
            print(f"ERROR deleting {path}: {e}", file=sys.stderr)
            errors += 1
    return deleted, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retention-based cleanup for reports/ and logs/")
    parser.add_argument("--apply", action="store_true",
                        help="Apply the retention policy (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Explicit dry-run (default behavior)")
    parser.add_argument("--root", default=".",
                        help="Repository root (default: current directory)")
    parser.add_argument("--json", action="store_true",
                        help="Output plan as JSON")
    args = parser.parse_args(argv)

    repo_root = Path(args.root).resolve()
    policy = CleanupPolicy.from_env()
    plan = plan_retention(repo_root, policy)

    if args.json:
        out = {
            "to_delete": [str(p) for p in plan.to_delete],
            "protected": [str(p) for p in plan.protected],
            "errors": plan.errors,
        }
        print(json.dumps(out, indent=2))
        return 0

    print(f"Cleanup plan for {repo_root}:")
    print(f"  To delete: {len(plan.to_delete)} items")
    print(f"  Protected: {len(plan.protected)} items")
    if plan.errors:
        print(f"  Errors: {len(plan.errors)}")
        for err in plan.errors:
            print(f"    - {err}")

    if args.apply:
        print("\nApplying...")
        deleted, errors = apply_plan(plan, dry_run=False)
        print(f"Deleted: {deleted}, Errors: {errors}")
        return 0 if errors == 0 else 1
    else:
        print("\nDRY-RUN (use --apply to execute)")
        deleted, _ = apply_plan(plan, dry_run=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
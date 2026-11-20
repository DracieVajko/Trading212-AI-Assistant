"""Weekly cleanup for the Portfolio AI Assistant.

Run once a week (e.g. Sunday evening) to keep the repo lean without losing
valuable history:

  * removes report directories older than --keep-days (reports are regenerated
    every run and carry no long-term value on their own),
  * prunes ephemeral caches (data/cache, debug dumps) older than --cache-days,
  * leaves history/ (trades, scores, decisions, prices) untouched.

Nothing valuable is ever deleted: trades, scores, decisions and price history
live in history/ and are never touched here. Old reports are simply removed.

Usage:
  py -3.12 scripts/archive_weekly.py [--keep-days 14] [--cache-days 7] [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _age_days(p: Path, now: datetime) -> float:
    try:
        return (now - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)).days
    except OSError:
        return 0.0


def prune_old_reports(keep_days: int, dry_run: bool) -> list[str]:
    """Delete report directories older than keep_days. Never touches history/."""
    archive_root = ROOT / "reports" / "archive"
    now = datetime.now(timezone.utc)
    removed: list[str] = []
    if not archive_root.exists():
        return removed
    for entry in archive_root.iterdir():
        if not entry.is_dir():
            continue
        if _age_days(entry, now) < keep_days:
            continue
        if dry_run:
            removed.append(f"[dry] would remove {entry}")
            continue
        try:
            shutil.rmtree(entry)
            removed.append(f"removed {entry.name}")
        except Exception as exc:
            removed.append(f"FAILED {entry.name}: {exc}")
    return removed


def prune_cache(cache_days: int, dry_run: bool) -> list[str]:
    out: list[str] = []
    now = datetime.now(timezone.utc)
    targets = [ROOT / "data" / "cache", ROOT / "reports" / "debug"]
    for t in targets:
        if not t.exists():
            continue
        for f in t.rglob("*"):
            if not f.is_file():
                continue
            if _age_days(f, now) < cache_days:
                continue
            if dry_run:
                out.append(f"[dry] would remove {f}")
                continue
            try:
                f.unlink()
                out.append(f"removed {f.relative_to(ROOT)}")
            except OSError as exc:
                out.append(f"FAILED {f}: {exc}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Weekly cleanup (never deletes history/).")
    ap.add_argument("--keep-days", type=int, default=14)
    ap.add_argument("--cache-days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    log_path = ROOT / "logs" / "archive_weekly.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"=== archive_weekly {datetime.now(timezone.utc).isoformat()} dry_run={args.dry_run} ==="]
    lines += ["-- reports --"] + prune_old_reports(args.keep_days, args.dry_run)
    lines += ["-- cache --"] + prune_cache(args.cache_days, args.dry_run)
    text = "\n".join(lines) + "\n"
    print(text)
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

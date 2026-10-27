"""Full output purge - explicit, named operation with strong confirmation.

This is a SEPARATE operation from cleanup_outputs.py.
It deletes ALL artifacts under allowlisted roots with explicit confirmation.

Usage:
    python -m scripts.purge_outputs              # interactive (type PURGE)
    python -m scripts.purge_outputs --confirm PURGE  # scripted
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ALLOWED_ROOTS = ("reports", "logs")


def purge_all(repo_root: Path, confirm: str | None = None) -> int:
    """Delete everything under allowlisted roots. Requires explicit confirmation."""
    repo_root = Path(repo_root).resolve()

    if confirm is None:
        print("=" * 60)
        print("FULL OUTPUT PURGE - IRREVERSIBLE")
        print("=" * 60)
        print(f"This will DELETE ALL FILES AND FOLDERS under:")
        for root in ALLOWED_ROOTS:
            print(f"  {repo_root / root}")
        print()
        print("Protected (NOT deleted):")
        print("  - Source code (*.py)")
        print("  - portfolio_config.json")
        print("  - agent_data/")
        print("  - data/")
        print("  - docs/")
        print()
        confirm = input("Type exactly 'PURGE' to confirm: ").strip()

    if confirm != "PURGE":
        print("Aborted - confirmation did not match 'PURGE'")
        return 1

    deleted_roots = 0
    for root_name in ALLOWED_ROOTS:
        root_path = repo_root / root_name
        if root_path.is_dir():
            print(f"Removing {root_path}...")
            try:
                shutil.rmtree(root_path, ignore_errors=False)
                root_path.mkdir(parents=True, exist_ok=True)
                print(f"  recreated empty {root_name}/")
                deleted_roots += 1
            except OSError as e:
                print(f"  ERROR: {e}", file=sys.stderr)
                return 1

    print(f"\nPurge complete. {deleted_roots} root folders cleared.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full output purge (explicit operation)")
    parser.add_argument("--confirm", default=None,
                        help="Confirmation token (must be 'PURGE')")
    parser.add_argument("--root", default=".",
                        help="Repository root (default: current directory)")
    args = parser.parse_args(argv)

    return purge_all(Path(args.root), args.confirm)


if __name__ == "__main__":
    raise SystemExit(main())
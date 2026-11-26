"""Central secret loading.

Secrets live OUTSIDE the project workspace (default:
``~/.portfolio-secrets/api.env``) and are never stored in git or read by the
agent. Override the location with ``PORTFOLIO_SECRETS_FILE``.

Only the Python process needs these values; the agent (OpenCode) is blocked by
permission rules in ``opencode.json`` from reading *.env files, so it cannot
see them even though they live on the same machine.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SECRETS_PATH = Path.home() / ".portfolio-secrets" / "api.env"


def secrets_path() -> Path:
    return Path(os.getenv("PORTFOLIO_SECRETS_FILE", str(DEFAULT_SECRETS_PATH))).expanduser()


def load_secrets() -> bool:
    """Load secrets into os.environ. Returns True if the file was found."""
    from dotenv import load_dotenv
    p = secrets_path()
    if not p.is_file():
        return False
    load_dotenv(str(p), override=False)
    return True

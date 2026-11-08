"""Subprocess runner for vendored day-trader tools."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


@dataclass
class ToolResult:
    ok: bool
    exit_code: int
    payload: Any = None
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0


def run_tool(
    script_path: str | Path,
    args: Sequence[str] = (),
    timeout_s: int = 120,
    json_mode: bool = True,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> ToolResult:
    """Run a vendored tool and return a structured result. Never raises."""
    path = Path(script_path)
    if not path.is_file():
        return ToolResult(ok=False, exit_code=127, stderr=f"script not found: {path}")

    cmd = [sys.executable, str(path), *list(args)]
    if json_mode and "--json" not in cmd:
        cmd.append("--json")

    run_env = dict(os.environ)
    run_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        run_env.update(env)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=run_env,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False,
            exit_code=-1,
            stderr=f"timeout after {timeout_s}s",
            duration_s=time.monotonic() - started,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return ToolResult(
            ok=False,
            exit_code=-2,
            stderr=f"{type(exc).__name__}: {exc}",
            duration_s=time.monotonic() - started,
        )

    duration = time.monotonic() - started
    payload = None
    if json_mode:
        text = (proc.stdout or "").strip()
        if text:
            # The tool may print non-JSON noise before the payload; take the
            # last complete JSON object/array.
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                for line in reversed(text.splitlines()):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

    ok = proc.returncode == 0
    return ToolResult(
        ok=ok,
        exit_code=proc.returncode,
        payload=payload,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        duration_s=round(duration, 3),
    )

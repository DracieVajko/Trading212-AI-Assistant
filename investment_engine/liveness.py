"""Run liveness primitives: bounded execution, watchdog, budgets, error
classification, and crash checkpoints.

Design rules (offline-verifiable, no live services needed):

- Bounded calls run in *daemon* threads and are abandoned on deadline. A
  blocked worker then cannot prevent interpreter exit (concurrent.futures
  worker threads are non-daemon and are joined by an atexit hook, which is
  why a stuck ThreadPoolExecutor task hangs the whole process).
- ``faulthandler.dump_traceback_later(..., exit=True)`` is the last-resort
  hard stop: it dumps every thread's stack and terminates the process, even
  when the main thread is blocked in a C-level call.
- Budgets use ``time.monotonic`` only. A check between calls is cooperative;
  the daemon-thread abandonment is the enforced bound for a single call.
- Provider failures are classified (unreachable vs rate limit vs busy ...)
  so the fallback chain can skip wasted attempts and record why.
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

DEFAULT_RUN_DEADLINE_S = 900.0
DEFAULT_ATTEMPT_MAX_S = 90.0
WATCHDOG_GRACE_S = 300.0


class ChainBudgetExceeded(TimeoutError):
    """Provider chain budget exhausted (subclass of TimeoutError for compat)."""


# --------------------------------------------------------------------------
# Event emission (best-effort, sanitized by run_history.record_run_event)
# --------------------------------------------------------------------------

def emit_event(event: dict) -> None:
    """Append a run event to the JSONL log. Never raises."""
    try:
        from investment_engine.reporting.run_history import record_run_event
        path = os.getenv("RUN_EVENTS_PATH", "reports/run_events.jsonl")
        record_run_event(path, dict(event))
    except Exception:
        pass


def new_invocation_id() -> str:
    """Unique id for one bounded operation invocation."""
    return f"inv_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------
# Bounded execution
# --------------------------------------------------------------------------

@dataclass
class BoundedResult:
    ok: bool = False
    value: Any = None
    error: BaseException | None = None
    timed_out: bool = False
    duration_s: float = 0.0


def run_bounded(
    fn: Callable[[], Any],
    timeout_s: float,
    *,
    stage: str = "operation",
    event_name: str | None = None,
    detail: str = "",
) -> BoundedResult:
    """Run ``fn`` in a daemon thread, wait at most ``timeout_s`` seconds.

    A timed-out worker is abandoned (it is a daemon thread and dies with the
    process); it is never joined by shutdown hooks. Callers must not rely on
    a timed-out worker's side effects. No operation is started when the
    timeout is already exhausted.
    """
    try:
        timeout_s = float(timeout_s)
    except (TypeError, ValueError):
        timeout_s = 0.0
    if timeout_s <= 0.0:
        res = BoundedResult(ok=False, timed_out=True, duration_s=0.0)
        if event_name:
            emit_event({"event": event_name, "stage": stage, "detail": detail,
                        "outcome": "budget_exhausted", "duration_s": 0.0,
                        "note": "no attempt started: deadline already exhausted"})
        return res
    holder: dict[str, Any] = {}

    def _target() -> None:
        try:
            holder["value"] = fn()
            holder["ok"] = True
        except BaseException as exc:  # noqa: BLE001 - captured for the caller
            holder["error"] = exc
            holder["ok"] = False

    t = threading.Thread(target=_target, daemon=True, name=f"bounded-{stage}")
    start = time.monotonic()
    t.start()
    t.join(timeout_s)
    dur = round(time.monotonic() - start, 3)
    if t.is_alive():
        res = BoundedResult(ok=False, timed_out=True, duration_s=dur)
        if event_name:
            emit_event({"event": event_name, "stage": stage, "detail": detail,
                        "outcome": "timed_out", "duration_s": dur,
                        "supervisor_terminated": True, "terminal_synthesized": True,
                        "note": "worker thread abandoned at deadline; it produced no terminal event"})
        return res
    if holder.get("ok"):
        res = BoundedResult(ok=True, value=holder.get("value"), duration_s=dur)
        if event_name:
            emit_event({"event": event_name, "stage": stage, "detail": detail,
                        "outcome": "success", "duration_s": dur})
        return res
    res = BoundedResult(ok=False, error=holder.get("error"), duration_s=dur)
    if event_name:
        exc = holder.get("error")
        emit_event({"event": event_name, "stage": stage, "detail": detail,
                    "outcome": "error", "duration_s": dur,
                    "error_class": type(exc).__name__ if exc else "Unknown",
                    "error": str(exc)[:200] if exc else ""})
    return res


def run_parallel(
    tasks: Mapping[str, Callable[[], Any]],
    timeout_s: float,
    *,
    stage: str = "batch",
    event_name: str | None = "stage_operations",
) -> dict[str, BoundedResult]:
    """Run ``tasks`` concurrently in daemon threads with ONE shared deadline.

    Returns ``{key: BoundedResult}`` for every task. Timed-out workers are
    abandoned; the batch never blocks longer than ``timeout_s`` (+ epsilon).
    """
    results: dict[str, BoundedResult] = {}
    if not tasks:
        return results
    try:
        timeout_s = float(timeout_s)
    except (TypeError, ValueError):
        timeout_s = 0.0
    if timeout_s <= 0.0:
        for key in tasks:
            results[key] = BoundedResult(ok=False, timed_out=True)
        if event_name:
            emit_event({"event": event_name, "stage": stage, "tasks": len(tasks),
                        "ok": 0, "failed": 0, "timed_out": len(tasks),
                        "note": "no attempt started: deadline already exhausted"})
        return results

    start = time.monotonic()
    deadline = start + timeout_s
    threads: dict[str, tuple[threading.Thread, dict]] = {}
    for key, fn in tasks.items():
        holder: dict[str, Any] = {}

        def _target(_fn: Callable[[], Any] = fn, _h: dict = holder) -> None:
            try:
                _h["value"] = _fn()
                _h["ok"] = True
            except BaseException as exc:  # noqa: BLE001
                _h["error"] = exc
                _h["ok"] = False

        t = threading.Thread(target=_target, daemon=True, name=f"bounded-{stage}-{key}")
        threads[str(key)] = (t, holder)
        t.start()

    for key, (t, _h) in threads.items():
        t.join(max(0.0, deadline - time.monotonic()))

    n_ok = n_err = n_to = 0
    timed_out_keys: list[str] = []
    for key, (t, holder) in threads.items():
        dur = round(time.monotonic() - start, 3)
        if t.is_alive():
            results[key] = BoundedResult(ok=False, timed_out=True, duration_s=dur)
            n_to += 1
            timed_out_keys.append(key)
        elif holder.get("ok"):
            results[key] = BoundedResult(ok=True, value=holder.get("value"), duration_s=dur)
            n_ok += 1
        else:
            results[key] = BoundedResult(ok=False, error=holder.get("error"), duration_s=dur)
            n_err += 1
    if event_name:
        emit_event({"event": event_name, "stage": stage, "tasks": len(tasks),
                    "ok": n_ok, "failed": n_err, "timed_out": n_to,
                    "duration_s": round(time.monotonic() - start, 3),
                    "timed_out_keys": timed_out_keys[:20]})
    return results


# --------------------------------------------------------------------------
# Run budget (monotonic)
# --------------------------------------------------------------------------

class RunBudget:
    """Cooperative run deadline on a monotonic clock."""

    def __init__(self) -> None:
        self._deadline: float | None = None
        self._seconds: float = 0.0
        self._started: float | None = None

    def start(self, seconds: float) -> None:
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = DEFAULT_RUN_DEADLINE_S
        if seconds <= 0:
            self._deadline = None
            self._seconds = 0.0
            self._started = None
            return
        self._seconds = seconds
        self._started = time.monotonic()
        self._deadline = self._started + seconds

    def reset(self) -> None:
        self._deadline = None
        self._seconds = 0.0
        self._started = None

    def armed(self) -> bool:
        return self._deadline is not None

    def exceeded(self) -> bool:
        return self._deadline is not None and time.monotonic() > self._deadline

    def remaining_seconds(self) -> float:
        if self._deadline is None:
            return float("inf")
        return max(0.0, self._deadline - time.monotonic())

    @property
    def seconds(self) -> float:
        return self._seconds


RUN_BUDGET = RunBudget()


def resolve_run_deadline_seconds() -> float:
    try:
        v = float(os.getenv("RUN_DEADLINE_SECONDS", "") or DEFAULT_RUN_DEADLINE_S)
    except (TypeError, ValueError):
        v = DEFAULT_RUN_DEADLINE_S
    return v if v > 0 else DEFAULT_RUN_DEADLINE_S


def resolve_attempt_max_seconds() -> float:
    try:
        v = float(os.getenv("PROVIDER_ATTEMPT_MAX_S", "") or DEFAULT_ATTEMPT_MAX_S)
    except (TypeError, ValueError):
        v = DEFAULT_ATTEMPT_MAX_S
    return v if v > 0 else DEFAULT_ATTEMPT_MAX_S


def resolve_watchdog_seconds(deadline_s: float | None = None) -> float:
    """Watchdog deadline: env RUN_WATCHDOG_SECONDS; <=0 disables; default
    run deadline + grace."""
    raw = os.getenv("RUN_WATCHDOG_SECONDS", "")
    if raw.strip():
        try:
            v = float(raw)
        except (TypeError, ValueError):
            v = 0.0
        return v if v > 0 else 0.0
    base = deadline_s if isinstance(deadline_s, (int, float)) and deadline_s > 0 else DEFAULT_RUN_DEADLINE_S
    return float(base) + WATCHDOG_GRACE_S


# --------------------------------------------------------------------------
# Degraded-stage registry (feeds PARTIAL run status)
# --------------------------------------------------------------------------

_DEGRADED_STAGES: dict[str, str] = {}


def reset_degraded() -> None:
    _DEGRADED_STAGES.clear()


def note_degraded(stage: str, reason: str) -> None:
    try:
        key = str(stage or "").strip() or "unknown"
        reason_s = str(reason or "")[:200]
        if key not in _DEGRADED_STAGES:
            _DEGRADED_STAGES[key] = reason_s
            emit_event({"event": "stage_degraded", "stage": key, "reason": reason_s})
    except Exception:
        pass


def degraded_stages() -> dict[str, str]:
    return dict(_DEGRADED_STAGES)


# --------------------------------------------------------------------------
# Provider failure classification
# --------------------------------------------------------------------------

_RETRY_AFTER_RE = re.compile(
    r"(?:retry[\s_-]*after|retry\s+in|reset\s+after)\D{0,10}([\d.]+)\s*s?", re.IGNORECASE)
_STATUS_RE = re.compile(r"(?:http|status(?:_code)?|code)[\s\":=]{1,4}(\d{3})", re.IGNORECASE)


@dataclass
class FailureInfo:
    kind: str = "unknown"
    retryable: bool = False
    http_status: int | None = None
    retry_after_s: float | None = None
    message: str = ""


def _retry_after_seconds(text: str) -> float | None:
    m = _RETRY_AFTER_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def _extract_http_status(text: str) -> int | None:
    m = _STATUS_RE.search(text or "")
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            pass
    tl = (text or "").lower()
    if "429" in tl or "too many requests" in tl:
        return 429
    if "402" in tl or ("insufficient" in tl and "credit" in tl):
        return 402
    if "503" in tl or "502" in tl or "504" in tl:
        return 503
    return None


def classify_failure(exc: BaseException | None = None, text: str | None = None) -> FailureInfo:
    """Classify a provider failure into a stable kind.

    Distinguishes request/unreachable failures from rate limits, quota
    exhaustion and busy/overloaded backends so the chain can react and the
    run event log can say WHY a provider was skipped.
    """
    tl = str(text or "")
    if exc is not None:
        tl = f"{type(exc).__name__}: {exc}" + (f"\n{tl}" if tl else "")
    low = tl.lower()
    status = _extract_http_status(tl)
    retry_after = _retry_after_seconds(tl)

    def _fin(kind: str, retryable: bool) -> FailureInfo:
        return FailureInfo(kind=kind, retryable=retryable, http_status=status,
                           retry_after_s=retry_after, message=tl[:300])

    # Network / transport classes first (exception-flavoured messages).
    if any(sig in low for sig in ("getaddrinfo", "name resolution", "name or service not known",
                                  "nodename nor servname", "temporary failure in name resolution")):
        return _fin("dns", True)
    if any(sig in low for sig in ("certificate", "ssl", "tls")):
        return _fin("tls", True)
    if "read timed out" in low or "readtimeout" in low or "read timeout" in low:
        return _fin("read_timeout", True)
    if "connecttimeout" in low or "connect timed out" in low or "connection timed out" in low:
        return _fin("connect_timeout", True)
    if "timed out" in low or "timeout" in low:
        return _fin("timeout", True)
    if any(sig in low for sig in ("connection refused", "connection reset", "connection aborted",
                                  "failed to establish", "newconnectionerror", "max retries exceeded",
                                  "network is unreachable", "host unreachable")):
        return _fin("unreachable", True)

    # Application-level classes.
    if status == 429 or "rate limit" in low or "rate-limit" in low or "rate_limited" in low \
            or "resource_exhausted" in low or "too many requests" in low:
        return _fin("rate_limited", True)
    if status == 402 or "quota" in low or ("insufficient" in low and ("credit" in low or "quota" in low)) \
            or "payment required" in low:
        return _fin("quota_exceeded", False)
    if status in (401, 403) or "unauthorized" in low or "invalid api key" in low \
            or "authentication" in low or "permission denied" in low:
        return _fin("auth_error", False)
    if "not configured" in low or "no api key" in low or "no key" in low or "api key is not set" in low \
            or "not configured" in low:
        return _fin("not_configured", False)
    if status in (500, 502, 503, 504) or "overloaded" in low or "server busy" in low \
            or "capacity" in low or ("busy" in low and "model" in low) or "unavailable" in low:
        return _fin("server_busy", True)
    if status in (400, 404) or ("model" in low and ("not found" in low or "not available" in low
                                                    or "no endpoints" in low)):
        return _fin("model_unavailable", False)
    if any(sig in low for sig in ("no choices", "no candidates", "empty response",
                                  "no content", "returned no")):
        return _fin("invalid_response", False)
    if status is not None and status >= 500:
        return _fin("server_error", True)
    return _fin("unknown", False)


def cooldown_for_failure(fi: FailureInfo) -> tuple[str, float] | None:
    """Cooldown policy: ("run", 0) = skip for the rest of the run,
    ("timed", seconds) = skip until now+seconds, None = no cooldown."""
    kind = (fi.kind or "unknown").lower()
    if kind == "rate_limited":
        ra = fi.retry_after_s
        if ra is None:
            return ("timed", 300.0)
        if ra > 900:
            return ("run", 0.0)
        return ("timed", min(ra + 5.0, 900.0))
    if kind in ("quota_exceeded", "auth_error"):
        return ("run", 0.0)
    if kind in ("server_busy", "server_error", "unreachable", "dns", "tls",
                "connect_timeout", "timeout", "read_timeout"):
        return ("timed", 120.0)
    if kind == "model_unavailable":
        return ("timed", 300.0)
    return None


# --------------------------------------------------------------------------
# Watchdog (faulthandler hard stop + stack dump)
# --------------------------------------------------------------------------

_WATCHDOG: dict[str, Any] = {"armed": False, "seconds": 0.0, "dump": None,
                             "sentinel": None, "file": None}


def arm_watchdog(seconds: float, dump_path: str | Path, sentinel_path: str | Path | None = None,
                 label: str = "") -> float:
    """Arm the hard-stop watchdog. Returns the armed timeout (0 = disabled).

    Uses ``faulthandler.dump_traceback_later(..., exit=True)``: after the
    timeout every thread's stack is dumped (file/line/function only, no
    locals, no secrets) and the process exits even if the main thread is
    blocked in an uninterruptible call.
    """
    try:
        seconds = float(seconds or 0.0)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0.0:
        return 0.0
    try:
        import faulthandler
        dump_path = Path(dump_path)
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(dump_path, "a", encoding="utf-8")
        fh.write(f"\n=== watchdog armed {datetime.now(timezone.utc).isoformat()} "
                 f"timeout={seconds:.0f}s pid={os.getpid()} label={label} ===\n")
        fh.flush()
        faulthandler.enable(file=fh, all_threads=True)
        faulthandler.dump_traceback_later(seconds, repeat=False, exit=True, file=fh)
        sentinel = Path(sentinel_path) if sentinel_path else None
        if sentinel is not None:
            try:
                sentinel.write_text(
                    f"armed_at={datetime.now(timezone.utc).isoformat()}\n"
                    f"timeout_s={seconds:.0f}\npid={os.getpid()}\nlabel={label}\n",
                    encoding="utf-8")
            except OSError:
                sentinel = None
        _WATCHDOG.update({"armed": True, "seconds": seconds, "dump": dump_path,
                          "sentinel": sentinel, "file": fh})
        emit_event({"event": "watchdog_armed", "timeout_s": seconds,
                    "dump": str(dump_path), "pid": os.getpid(), "label": label})
        return seconds
    except Exception:
        return 0.0


def disarm_watchdog() -> None:
    """Cancel the watchdog (called on every clean exit path)."""
    if not _WATCHDOG.get("armed"):
        return
    try:
        import faulthandler
        faulthandler.cancel_dump_traceback_later()
        faulthandler.disable()
    except Exception:
        pass
    try:
        fh = _WATCHDOG.get("file")
        if fh is not None:
            fh.close()
    except Exception:
        pass
    try:
        sentinel = _WATCHDOG.get("sentinel")
        if sentinel is not None:
            Path(sentinel).unlink(missing_ok=True)
    except Exception:
        pass
    _WATCHDOG.update({"armed": False, "seconds": 0.0, "dump": None,
                      "sentinel": None, "file": None})
    emit_event({"event": "watchdog_disarmed"})


def watchdog_status() -> dict:
    return {"armed": bool(_WATCHDOG.get("armed")), "seconds": _WATCHDOG.get("seconds", 0.0),
            "dump": str(_WATCHDOG.get("dump")) if _WATCHDOG.get("dump") else ""}


# --------------------------------------------------------------------------
# Crash checkpoints (partial-publication material)
# --------------------------------------------------------------------------

def checkpoint_file(base_dir: str | Path, run_id: str) -> Path:
    return Path(base_dir) / "checkpoints" / f"{run_id}.json"


def write_checkpoint(base_dir: str | Path, run_id: str, kind: str, payload: dict) -> Path | None:
    """Merge-write one stage checkpoint. Never raises, never blocks the run."""
    try:
        run_id = str(run_id or "").strip()
        if not run_id:
            return None
        import json as _json
        path = checkpoint_file(base_dir, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        try:
            data = _json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            data = {}
        data.setdefault("run_id", run_id)
        data.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        stages = data.setdefault("stages", {})
        stages[str(kind)] = {"ts": datetime.now(timezone.utc).isoformat(), **(payload or {})}
        data["closed"] = False
        tmp = path.parent / f".tmp.{path.name}.part"
        tmp.write_text(_json.dumps(data, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        emit_event({"event": "checkpoint_written", "run_id": run_id, "kind": str(kind)})
        return path
    except Exception:
        return None


def load_checkpoints(base_dir: str | Path, run_id: str) -> dict | None:
    try:
        import json as _json
        path = checkpoint_file(base_dir, run_id)
        if not path.is_file():
            return None
        return _json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None


def close_checkpoint(base_dir: str | Path, run_id: str, status: str, extra: dict | None = None) -> None:
    """Mark a run's checkpoint as closed with a final status. Never raises."""
    try:
        import json as _json
        run_id = str(run_id or "").strip()
        if not run_id:
            return
        path = checkpoint_file(base_dir, run_id)
        if not path.is_file():
            return
        data = _json.loads(path.read_text(encoding="utf-8")) or {}
        data["closed"] = str(status)
        data["closed_at"] = datetime.now(timezone.utc).isoformat()
        if extra:
            data["close_extra"] = extra
        tmp = path.parent / f".tmp.{path.name}.part"
        tmp.write_text(_json.dumps(data, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        emit_event({"event": "checkpoint_closed", "run_id": run_id, "status": str(status)})
    except Exception:
        pass

"""Run history linkage + decision-log writer (Phase 9).

Previous-run linkage: find the latest completed archived run (different
run_id) and extract a comparable summary. Never raises; missing archive or
unreadable files yield None ("no comparable previous run").

Decision-log writer: one ticker-level record per ADVISORY plan fits the
existing Appendix-C schema exactly (mode/verdict/confidence/asset).
Runs without plans write nothing. Gated by DECISION_LOG_ENABLED=1 so
offline tests never touch the real log.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|access[_-]?token|secret)\s*[:=]?\s*[\"']?([A-Za-z0-9\-_./+]{12,})"
)


def _sanitize_text(value: str, limit: int = 500) -> str:
    try:
        s = _SECRET_RE.sub(r"\1=[redacted]", value)
    except Exception:
        s = value
    if len(s) > limit:
        s = s[:limit] + "…(truncated)"
    return s


def _sanitize_event(obj: Any, _depth: int = 0) -> Any:
    """Bound event sizes and redact credential-shaped values. No prompts."""
    if _depth > 4:
        return obj
    if isinstance(obj, str):
        return _sanitize_text(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_event(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_event(v, _depth + 1) for v in obj]
    return obj


def _heal_legacy_separators(p: Path) -> None:
    """One-time self-heal for JSONL files written with literal backslash-n
    separators instead of real newlines (writer bug fixed 2026-10-17)."""
    try:
        if not p.is_file() or p.stat().st_size > 2_000_000:
            return
        raw = p.read_text(encoding="utf-8")
        if "}\\n{" not in raw:
            return
        fixed = raw.replace("}\\n{", "}\n{")
        for line in fixed.splitlines():
            if line.strip():
                json.loads(line)
        p.write_text(fixed if fixed.endswith("\n") else fixed + "\n",
                     encoding="utf-8", newline="\n")
    except Exception:
        return


def record_run_event(event_path: str | Path, event: dict[str, Any]) -> None:
    """Append one JSONL event to the run event log (crash-resilient,
    sanitized, bounded). Never raises. Skipped entirely when
    RUN_EVENTS_DISABLED is set (tests isolate the real evidence file)."""
    try:
        if os.getenv("RUN_EVENTS_DISABLED", "").strip().lower() in ("1", "true", "yes", "on"):
            return
        p = Path(event_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        _heal_legacy_separators(p)
        payload = {"ts": datetime.now(timezone.utc).isoformat(), **_sanitize_event(event or {})}
        with p.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            f.flush()
            try:
                import os as _os
                _os.fsync(f.fileno())
            except Exception:
                pass
    except Exception:
        pass


def _parse_ts(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def load_previous_run(archive_dir: str | Path, current_run_id: str) -> dict | None:
    """Return the latest completed archived run comparable to the current one.

    Result: {run_id, generated_at, stance, news_count, signals, comparison_status}.
    Returns None when no comparable previous run exists.
    """
    try:
        base = Path(archive_dir)
        if not base.is_dir():
            return None
        best: dict | None = None
        best_ts: datetime | None = None
        for child in base.iterdir():
            if not child.is_dir() or child.name == current_run_id:
                continue
            manifest_path = child / "run_manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            ts = _parse_ts(manifest.get("generated_at"))
            if ts is None:
                continue
            if best_ts is None or ts > best_ts:
                best_ts = ts
                best = {"dir": child, "manifest": manifest}
        if best is None:
            return None
        manifest = best["manifest"]
        signals: dict[str, str] = {}
        try:
            analysis_path = best["dir"] / "portfolio_analysis.json"
            if analysis_path.is_file() and analysis_path.stat().st_size < 10_000_000:
                analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
                for row in analysis.get("portfolio_rows", []) or []:
                    if isinstance(row, dict):
                        disp = str(row.get("display_symbol") or row.get("ticker") or "").strip().upper()
                        if disp:
                            signals[disp] = str(row.get("signal", "")).upper()
        except (OSError, ValueError):
            pass
        stance = str(manifest.get("stance", "unknown"))
        return {
            "run_id": best["dir"].name,
            "generated_at": manifest.get("generated_at", ""),
            "stance": stance,
            "news_count": int(((manifest.get("counts", {}) or {}).get("decision_news", 0)) or 0),
            "signals": signals,
            "comparison_status": "previous run found",
        }
    except Exception:
        return None


def decision_log_enabled() -> bool:
    """Opt-in switch: DECISION_LOG_ENABLED=1 writes run decisions to the log."""
    return os.getenv("DECISION_LOG_ENABLED", "0").strip() in ("1", "true", "yes", "on")


def write_run_decisions(result: dict, run_id: str, log_dir: str | Path | None = None) -> list[str]:
    """Write one Appendix-C record per advisory plan. Returns written file names.

    No-op ([]) unless DECISION_LOG_ENABLED=1. Never raises; validation
    failures are skipped per plan. Never writes credentials.
    """
    written: list[str] = []
    if not decision_log_enabled():
        return written
    try:
        from scripts import decision_log as dl
    except Exception:
        return written
    plans = ((result.get("order_plans", {}) or {}).get("plans", []) or [])
    providers = result.get("providers_per_stage", {}) or {}
    served = sorted({str((v or {}).get("model_served", "")) for v in providers.values() if isinstance(v, dict) and v.get("model_served")})
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        ticker = str(plan.get("ticker", "") or "?").upper()
        direction = str(plan.get("direction", "") or "HOLD").upper()
        verdict = {"BUY": "BUY", "ACCUMULATE": "ADD", "TRIM": "TRIM", "SELL": "SELL"}.get(direction, "HOLD")
        try:
            record = dl.build_record({
                "asset": {"ticker": ticker},
                "mode": "M1",
                "verdict": verdict,
                "confidence": "medium",
                "notes": [
                    f"run {run_id}: {direction} {ticker} "
                    f"~EUR {float(plan.get('indicative_notional_eur', 0) or 0):,.2f} "
                    f"({plan.get('binding_constraint', '')}); advisory only, not executed",
                    f"basis: {', '.join(str(x) for x in (plan.get('rationale_ids', []) or [])[:4])}",
                    f"models: {', '.join(served[:3]) or 'deterministic'}",
                ],
            })
            dest = dl.append_record(record, Path(log_dir) if log_dir else None)
            written.append(dest.name)
        except Exception:
            continue
    return written

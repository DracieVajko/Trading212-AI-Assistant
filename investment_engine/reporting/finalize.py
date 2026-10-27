"""Finalization layer: run statuses, honest PARTIAL/ABORTED status documents,
status-report publication, and aborted-run recovery.

Statuses:
- COMPLETE  all validated stages produced real AI output, broker+recon ok.
- PARTIAL   broker data available, but one or more AI stages fell back to
            deterministic content because providers were unavailable/timeout
            or the run deadline was exceeded. No recommendations are invented.
- ABORTED   no trustworthy broker snapshot: diagnostic-only status document,
            no account values presented as current.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

RUN_STATUS_COMPLETE = "COMPLETE"
RUN_STATUS_PARTIAL = "PARTIAL"
RUN_STATUS_ABORTED = "ABORTED"


def atomic_write_text(dest: Path, text: str) -> None:
    """Write fully to a temp sibling, fsync, then atomically replace dest.

    newline="" is load-bearing: text-mode "\\n"->CRLF translation on Windows
    used to make every manifest sha256/bytes mismatch the file on disk
    (finding 16 — deterministic on all 5 files, every run). Artifacts stay LF.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".tmp.{dest.name}.{os.getpid()}.part"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, dest)


def compute_run_status(*, broker_ok: bool, degraded: dict | None,
                       deadline_exceeded: bool = False) -> tuple[str, list[str]]:
    """Map pipeline facts to (status, reasons). Pure function."""
    if not broker_ok:
        return RUN_STATUS_ABORTED, ["broker data unavailable"]
    reasons: list[str] = []
    for stage, reason in sorted((degraded or {}).items()):
        reasons.append(f"AI stage '{stage}' degraded: {reason}")
    if deadline_exceeded:
        reasons.append("run deadline exceeded")
    if reasons:
        return RUN_STATUS_PARTIAL, reasons
    return RUN_STATUS_COMPLETE, []


def _fmt_eur(value) -> str:
    try:
        return f"€{float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def build_status_document(*, run_id: str, status: str, reasons: Iterable[str],
                          checkpoints: dict | None) -> str:
    """Honest status document for PARTIAL/ABORTED runs (no invented content)."""
    stages = (checkpoints or {}).get("stages", {}) if isinstance(checkpoints, dict) else {}
    broker = stages.get("broker") or {}
    research = stages.get("research") or {}
    analysis = stages.get("analysis") or {}
    broker_ok = str(broker.get("t212_status", "")).lower() == "ok"
    lines: list[str] = [
        f"# Portfolio Intelligence Brief — RUN {status}",
        "",
        f"- Run status: **{status}**",
        f"- Run id: `{run_id}`",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
    ]
    reason_list = [str(r) for r in (reasons or []) if str(r).strip()]
    if reason_list:
        lines.append("- Reason: " + "; ".join(reason_list[:5]))
    lines += ["", "## Status overview", ""]
    if broker_ok:
        lines.append(
            "- Broker data: AVAILABLE (from completed checkpoint) — "
            f"equity {_fmt_eur(broker.get('total_equity'))}, "
            f"reported cash {_fmt_eur(broker.get('reported_cash'))}, "
            f"positions {broker.get('positions', '?')}")
        lines.append(f"- Accounting audit: {broker.get('recon_status', 'UNKNOWN')}")
    else:
        lines.append("- Broker data: UNAVAILABLE — no account values are shown")
        lines.append("- Accounting audit: NOT RUN — no broker snapshot")
    if stages.get("research"):
        counts = research.get("corpus_counts", {}) or {}
        lines.append(f"- Research: AVAILABLE — corpus items: {counts.get('total', '?')} "
                     f"(decision {counts.get('decision', '?')})")
    else:
        lines.append("- Research: NOT REACHED")
    if stages.get("analysis"):
        skills = analysis.get("skill_statuses", {}) or {}
        lines.append("- AI analysis: PARTIAL — skills " +
                     ", ".join(f"{k}={v}" for k, v in sorted(skills.items())) or "- AI analysis: PARTIAL")
        lines.append(f"- Advisory: NOT GENERATED — insufficient validated analysis "
                     f"(advisory plans built: {analysis.get('plans', 0)})")
    else:
        lines.append("- AI analysis: NOT REACHED / UNAVAILABLE — provider deadline or budget limit")
        lines.append("- Advisory: NOT GENERATED — insufficient validated analysis")
    lines += [
        "",
        "---",
        "",
        "_This is a status document. It contains no recommendations and nothing was executed._",
    ]
    if broker_ok:
        lines.append("_Checkpoint values are from a completed stage of the interrupted run; "
                     "they are not a current account valuation._")
    return "\n".join(lines) + "\n"


def partial_status_header(run_id: str, reasons: Iterable[str], degraded: dict | None) -> str:
    """Short header prepended to a full brief when the run status is PARTIAL."""
    lines = [
        "# STATUS: PARTIAL RUN",
        "",
        f"Run `{run_id}` completed, but one or more AI stages were degraded:",
    ]
    for stage, reason in sorted((degraded or {}).items()):
        lines.append(f"- **{stage}**: {reason}")
    if not degraded:
        for r in list(reasons or [])[:5]:
            lines.append(f"- {r}")
    lines.append("Affected sections may contain deterministic fallback content. "
                 "No recommendations were invented.")
    return "\n".join(lines)


def _carry_last_complete(current_dir: Path) -> str:
    """Best-effort previous last-complete pointer from current/run_manifest.json."""
    try:
        prev = json.loads((current_dir / "run_manifest.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return ""
    status = str(prev.get("run_status") or RUN_STATUS_COMPLETE)
    if prev.get("last_complete_run_id"):
        return str(prev["last_complete_run_id"])
    if status == RUN_STATUS_COMPLETE:
        return str(prev.get("run_id") or "")
    return ""


_KNOWN_ARTIFACTS = (
    "portfolio_decision_brief.md",
    "t212_portfolio_snapshot.md",
    "portfolio_analysis.json",
    "failed_tickers.md",
    "portfolio_intelligence_brief.md",
    "portfolio_deep_dive.md",
)


def publish_status_report(*, run_id: str, status: str, reasons: Iterable[str],
                          checkpoints: dict | None, reports_dir: str | Path,
                          archive_dir: str | Path, label: str = "",
                          local_ai_stats: dict | None = None,
                          social_platform_status: list[dict] | None = None) -> dict[str, Path]:
    """Publish a PARTIAL/ABORTED status document set (atomic, no mixing).

    Writes the standard artifact names with explicit status content so
    downstream tooling without partial-aware readers still finds a truthful
    run. Never touches a previous COMPLETE run's archive copy; carries the
    ``last_complete_run_id`` pointer forward.

    Idempotent: if current/ already has a finalized manifest for this run_id,
    subsequent calls return the existing published paths without changes.
    """
    import hashlib as _hashlib

    reports_dir = Path(reports_dir)
    current_dir = reports_dir / "current"
    run_archive_dir = Path(archive_dir) / run_id

    # Idempotency: if already finalized for this run_id, return existing
    try:
        manifest_path = current_dir / "run_manifest.json"
        if manifest_path.is_file():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("run_id") == run_id and existing.get("finalized") is True:
                # Return existing published paths
                return {name: current_dir / name for name in _KNOWN_ARTIFACTS if (current_dir / name).exists()}
    except (OSError, ValueError):
        pass

    current_dir.mkdir(parents=True, exist_ok=True)
    run_archive_dir.mkdir(parents=True, exist_ok=True)

    status = str(status or RUN_STATUS_PARTIAL).upper()
    reason_list = [str(r) for r in (reasons or [])]

    doc = build_status_document(run_id=run_id, status=status, reasons=reason_list,
                                checkpoints=checkpoints or {})
    snapshot_doc = (f"# T212 Snapshot — RUN {status}\n\n"
                    f"Run `{run_id}` did not reach final snapshot rendering ({status}).\n"
                    "No account values are presented as current.\n")
    analysis = {
        "run_id": run_id,
        "run_status": status,
        "reasons": reason_list,
        "checkpoints": (checkpoints or {}).get("stages", {}) if isinstance(checkpoints, dict) else {},
        "advisory": "NOT GENERATED — insufficient validated analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    payloads: dict[str, str] = {
        "portfolio_intelligence_brief.md": doc,
        "portfolio_decision_brief.md": doc,
        "t212_portfolio_snapshot.md": snapshot_doc,
        "portfolio_analysis.json": json.dumps(analysis, indent=2, ensure_ascii=False, default=str),
    }
    for stale in set(_KNOWN_ARTIFACTS) - set(payloads):
        for base in (current_dir, run_archive_dir):
            try:
                (base / stale).unlink(missing_ok=True)
            except OSError:
                pass

    published: dict[str, Path] = {}
    manifest_files: dict[str, dict] = {}
    for name, text in payloads.items():
        digest = _hashlib.sha256(text.encode("utf-8")).hexdigest()
        atomic_write_text(current_dir / name, text)
        try:
            shutil.copy2(current_dir / name, run_archive_dir / name)
        except OSError:
            logger.warning("Archive copy failed for %s", name)
        published[name] = current_dir / name
        manifest_files[name] = {"sha256": digest, "bytes": len(text.encode("utf-8"))}

    last_complete = _carry_last_complete(current_dir)
    _local_ai_stats = dict(local_ai_stats or {})
    _social_platform_status = list(social_platform_status or [])
    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now().astimezone().isoformat(),
        "run_status": status,
        "partial": True,
        "finalized": True,
        "reasons": reason_list,
        "last_complete_run_id": last_complete,
        "label": str(label or ""),
        "recon_status": None,
        "stance": "unavailable",
        "files": manifest_files,
        "counts": {},
        "local_ai_stats": _local_ai_stats or {},
        "social_platform_status": _social_platform_status,
    }
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False, default=str)
    atomic_write_text(current_dir / "run_manifest.json", manifest_text)
    try:
        shutil.copy2(current_dir / "run_manifest.json", run_archive_dir / "run_manifest.json")
    except OSError:
        logger.warning("Archive copy failed for run_manifest.json")
    published["run_manifest.json"] = current_dir / "run_manifest.json"
    logger.warning("Status report published (%s): %s", status, current_dir)
    return published


def recover_aborted_runs(reports_dir: str | Path) -> list[str]:
    """Recover runs whose checkpoints were never closed (killed/aborted).

    Writes ``reports/aborted/<run_id>.md`` status documents, closes the
    checkpoints, and emits one event per recovered run. Never raises.
    Returns the recovered run ids.
    """
    from investment_engine import liveness as _lv

    recovered: list[str] = []
    reports_dir = Path(reports_dir)
    ckpt_dir = reports_dir / "checkpoints"
    if not ckpt_dir.is_dir():
        return recovered
    aborted_dir = reports_dir / "aborted"
    for path in sorted(ckpt_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
            if data.get("closed"):
                continue
            run_id = str(data.get("run_id") or path.stem)
            doc = build_status_document(
                run_id=run_id, status=RUN_STATUS_ABORTED,
                reasons=["run never reached finalization (process aborted or watchdog termination)"],
                checkpoints=data)
            aborted_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(aborted_dir / f"{run_id}.md", doc)
            stages = list((data.get("stages") or {}).keys())
            _lv.close_checkpoint(reports_dir, run_id, "recovered_aborted",
                                 extra={"recovered_at": datetime.now(timezone.utc).isoformat()})
            _lv.emit_event({"event": "run_recovered_aborted", "run_id": run_id,
                            "stages_completed": stages})
            recovered.append(run_id)
        except Exception:
            continue
    return recovered


def scan_stale_watchdog_markers(logs_dir: str | Path) -> list[str]:
    """Return leftover watchdog sentinel files (evidence a watchdog fired)."""
    try:
        logs_dir = Path(logs_dir)
        if not logs_dir.is_dir():
            return []
        return [p.name for p in sorted(logs_dir.glob(".watchdog_armed_*"))]
    except Exception:
        return []

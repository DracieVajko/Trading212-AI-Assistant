"""Provider load-guard probes: decide whether a local LLM endpoint's host is
too busy to serve a request now (Spec: docs/specs/2026-10-28-provider-busy-guard-design.md).

Design rules:
- Pure, side-effect-free, never raises: every failure path degrades to a
  not-busy Verdict (the guard must never make decisions worse than without it).
- Loudness: a busy verdict carries a human-readable reason; the caller logs it
  at INFO. Degradations log at DEBUG here.
- Localhost-only OS metrics: psutil / nvidia-smi are meaningful only when the
  endpoint runs on this very machine; remote hosts get HTTP-level signals only.
"""
from __future__ import annotations

import logging
import shutil
import socket
import subprocess
from dataclasses import dataclass, field

import requests
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

try:  # optional dependency: guard degrades to HTTP-only signals without it
    import psutil  # type: ignore
except Exception:  # pragma: no cover - environment without psutil
    psutil = None  # type: ignore


@dataclass(frozen=True)
class Verdict:
    """Probe outcome. ``busy`` = do not ask this endpoint for work right now."""
    busy: bool
    reason: str
    evidence: dict[str, str] = field(default_factory=dict)


_LOCAL_HOST_NAMES = {"127.0.0.1", "localhost", "::1"}


def _host_of(base_url: str) -> str:
    """Hostname part of a URL, tolerating sloppy input like http://::1:1234.

    Unbracketed-IPv6 netlocs ("::1", "::1:1234", "fe80::1") are ambiguous per
    RFC 3986 (a bare IPv6 has no portable host:port split). Used only for
    localhost detection of curated local endpoints, so: a trailing all-digit
    segment is taken as a port only when the remainder still looks like an
    address ("::1:1234" -> "::1"); otherwise the netloc parses as-is.
    A non-matching exotic form simply fails the localhost check -> HTTP-only
    guard (safe direction), never a crash.
    """
    raw = str(base_url or "").strip()
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/", 1)[0]
    raw = raw.rsplit("@", 1)[-1]  # drop userinfo
    if raw.startswith("[") and "]" in raw:
        return raw[1:raw.index("]")].strip().lower()
    if raw.count(":") > 1:
        head, _, tail = raw.rpartition(":")
        if tail.isdigit() and head not in ("", ":"):
            return head.strip().lower()
    else:
        raw = raw.split(":", 1)[0]
    return raw.strip().lower()


def is_localhost(base_url: str) -> bool:
    """True when the endpoint host is this very machine."""
    host = _host_of(base_url)
    if not host:
        return False
    if host in _LOCAL_HOST_NAMES:
        return True
    try:
        return host == socket.gethostname().strip().lower()
    except Exception:
        return False


def _not_busy(reason: str = "") -> Verdict:
    return Verdict(busy=False, reason=reason or "not busy", evidence={})


def _cfg(settings, key: str, default):
    """Read a knob from EngineSettings or a dict, with a default. Never raises."""
    try:
        if isinstance(settings, dict):
            return settings.get(key, default)
        return getattr(settings, key, default)
    except Exception:
        return default


# ---------------------------------------------------------------------------
#_signal helpers (evidence in "[signal] observed vs limit" strings)
# ---------------------------------------------------------------------------

def _latency_signal(latencies, settings, evidence: dict) -> str | None:
    """Busy text when every measured attempt exceeds the latency knob.

    LM Studio: preflight gives >=2 attempts; BOTH must be slow (a single
    Tailscale spike must not exile the primary). Empty list = no verdict.
    """
    thr = int(_cfg(settings, "load_guard_latency_ms", 2500) or 2500)
    lat = [float(x) for x in (latencies or []) if x is not None and float(x) >= 0]
    if not lat:
        return None
    if all(x * 1000.0 > thr for x in lat):
        evidence["latency_ms"] = ",".join(str(round(x * 1000)) for x in lat)
        return f"probe latency {round(max(lat) * 1000)}ms > {thr}ms"
    return None


def _lmstudio_loading_state(base_url: str, evidence: dict) -> str | None:
    """Model state via lmstudio.v1_models (v0 data-payload fallback). Unknown
    API variant scores not busy (graceful degradation, feature-detect)."""
    state_text = None
    try:
        from investment_engine.providers.lmstudio import v1_models
        entries = v1_models(base_url) or {}
        for key, entry in entries.items():
            if isinstance(entry, dict) and str(entry.get("state", "")).lower() == "loading":
                state_text = str(key)
                break
    except Exception as exc:
        logger.debug("load guard: v1 state probe unavailable on %s: %s", base_url, exc)
    if state_text is None:
        state_text = _v0_loading_state(base_url)  # half-implemented provider APIs
    if state_text:
        evidence["loading_state"] = state_text
        return "model state=loading"
    return None


def _v0_loading_state(base_url: str) -> str | None:
    """Older servers: /api/v0/models payload carries data[].state."""
    try:
        root = _root_of(base_url)
        r = requests.get(f"{root}/api/v0/models", timeout=(3, 5))
        if r.status_code == 200:
            for d in (r.json().get("data") or []):
                if isinstance(d, dict) and str(d.get("state", "")).lower() == "loading":
                    return str(d.get("id") or d.get("model") or "")
    except Exception as exc:
        logger.debug("load guard: v0 state probe unavailable on %s: %s", base_url, exc)
    return None


def _root_of(base_url: str) -> str:
    base = str(base_url or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base.rstrip("/")


def _local_metrics(settings, evidence: dict) -> list[str]:
    """OS/GPU breaches on THIS machine only. Missing tools degrade to []+DEBUG."""
    breaches: list[str] = []
    if psutil is None:
        logger.debug("load guard: psutil absent, CPU/RAM signals skipped")
    else:
        try:
            cpu_pct = float(psutil.cpu_percent(interval=None))
            ram_pct = float(psutil.virtual_memory().percent)
            cpu_thr = float(_cfg(settings, "load_guard_cpu_pct", 85) or 85)
            ram_thr = float(_cfg(settings, "load_guard_ram_pct", 90) or 90)
            if cpu_pct >= cpu_thr:
                breaches.append(f"cpu {cpu_pct:.0f}%>={cpu_thr:.0f}%")
                evidence["cpu_pct"] = f"{cpu_pct:.0f}"
            if ram_pct >= ram_thr:
                breaches.append(f"ram {ram_pct:.0f}%>={ram_thr:.0f}%")
                evidence["ram_pct"] = f"{ram_pct:.0f}"
        except Exception as exc:
            logger.debug("load guard: psutil metrics unavailable: %s", exc)
    if bool(_cfg(settings, "load_guard_use_nvidia_smi", True)):
        exe = shutil.which("nvidia-smi")
        if not exe:
            logger.debug("load guard: nvidia-smi absent, GPU signals skipped")
        else:
            try:
                out = subprocess.run(
                    [exe, "--query-gpu=utilization.gpu,memory.free",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, check=False)
                first = (out.stdout or "").strip().splitlines()
                if first:
                    parts = [p.strip() for p in first[0].split(",")]
                    if len(parts) >= 2:
                        gpu_util = float(parts[0])
                        vram_free = float(parts[1])
                        gpu_thr = float(_cfg(settings, "load_guard_gpu_max_util_pct", 85) or 85)
                        vram_thr = float(_cfg(settings, "load_guard_vram_min_free_mib", 1500) or 1500)
                        if gpu_util >= gpu_thr:
                            breaches.append(f"gpu {gpu_util:.0f}%>={gpu_thr:.0f}%")
                            evidence["gpu_util_pct"] = f"{gpu_util:.0f}"
                        if vram_free < vram_thr:
                            breaches.append(f"vram free {vram_free:.0f}MiB<{vram_thr:.0f}MiB")
                            evidence["vram_free_mib"] = f"{vram_free:.0f}"
            except Exception as exc:
                logger.debug("load guard: nvidia-smi probe failed: %s", exc)
    return breaches


def _aggregate(parts: list[str], evidence: dict) -> Verdict:
    if parts:
        return Verdict(busy=True, reason=f"host busy: {'; '.join(parts)}", evidence=evidence)
    return _not_busy("idle")


def _norm_model_name(model: str) -> str:
    """Ollama registry-normalized name: lowercase, ":latest" tag stripped."""
    t = str(model or "").strip().lower()
    return t[: -len(":latest")] if t.endswith(":latest") else t


def _ollama_resident(base_url: str, model: str, evidence: dict) -> bool | None:
    """Is the configured model loaded in Ollama? True/False when /api/ps answers,
    None when endpoint absent/unknown (graceful degradation -> not busy)."""
    root = str(base_url or "").rstrip("/")
    try:
        r = requests.get(f"{root}/api/ps", timeout=3)
        if r.status_code != 200:
            logger.debug("load guard: /api/ps HTTP %s on %s", r.status_code, root)
            return None
        payload = r.json() or {}
        names: list[str] = []
        for m in (payload.get("models") or payload.get("data") or []):
            if isinstance(m, dict):
                names.append(str(m.get("name") or m.get("Name") or m.get("model") or ""))
        evidence["api_ps_names"] = ",".join(n for n in names if n) or "-"
        pin = _norm_model_name(model)
        for n in names:
            if _norm_model_name(n) == pin:
                return True
        return False
    except Exception as exc:
        logger.debug("load guard: /api/ps unavailable on %s: %s", root, exc)
        return None


def _single_latency(base_url: str, path: str, settings, evidence: dict, tag: str) -> str | None:
    """One timed GETPi probe (single attempt, ~2-3 s cap); any reply slower
    than the latency knob counts as busy (b-found link is genuinely slow)."""
    import time as _t
    thr = int(_cfg(settings, "load_guard_latency_ms", 2500) or 2500)
    url = str(base_url or "").rstrip("/") + path
    try:
        t0 = _t.monotonic()
        r = requests.get(url, timeout=(3, max(3.0, thr / 1000.0 + 1.0)))
        elapsed_ms = (_t.monotonic() - t0) * 1000.0
        if r.status_code == 200 and elapsed_ms > thr:
            evidence[tag] = f"{round(elapsed_ms)}ms"
            return f"probe latency {round(elapsed_ms)}ms > {thr}ms"
        return None
    except Exception as exc:
        logger.debug("load guard: latency probe unreachable %s%s: %s", base_url, path, exc)
        return None


def _probe_latency_only(base_url: str, settings) -> Verdict:
    if not bool(_cfg(settings, "load_guard_enabled", True)):
        return _not_busy("load guard disabled")
    evidence: dict[str, str] = {}
    slow = _single_latency(base_url, "/models", settings, evidence, "latency")
    return _aggregate([slow] if slow else [], evidence)


def _probe_ollama(base_url: str, settings) -> Verdict:
    if not bool(_cfg(settings, "load_guard_enabled", True)):
        return _not_busy("load guard disabled")
    evidence: dict[str, str] = {}
    parts: list[str] = []
    if bool(_cfg(settings, "load_guard_ollama_require_loaded", True)):
        model = str(_cfg(settings, "ollama_model", "") or "")
        resident = _ollama_resident(base_url, model, evidence)
        if resident is False:
            parts.append(f"model_cold: {model} not loaded in /api/ps")
    slow = _single_latency(base_url, "/api/tags", settings, evidence, "ollama")
    if slow:
        parts.append(slow)
    return _aggregate(parts, evidence)


def _probe_lmstudio(base_url: str, settings, latencies) -> Verdict:
    if not bool(_cfg(settings, "load_guard_enabled", True)):
        return _not_busy("load guard disabled")
    evidence: dict[str, str] = {}
    parts: list[str] = []
    lat_busy = _latency_signal(latencies, settings, evidence)
    if lat_busy:
        parts.append(lat_busy.replace("probe latency", "latency"))
    state_busy = _lmstudio_loading_state(base_url, evidence)
    if state_busy:
        parts.append(state_busy)
    if is_localhost(base_url):
        parts.extend(_local_metrics(settings, evidence))
    return _aggregate(parts, evidence)


def probe_provider_busy(
    name: str,
    base_url: str,
    settings,
    latencies: list[float] | None = None,
) -> Verdict:
    """Dispatch a busy-check for one local provider link. Never raises."""
    try:
        n = str(name or "")
        if n == "LM Studio":
            return _probe_lmstudio(base_url, settings, latencies or [])
        if n == "llama.cpp":
            return _probe_latency_only(base_url, settings)
        if n == "Ollama":
            return _probe_ollama(base_url, settings)
        return Verdict(busy=False, reason=f"unknown provider {n!r}", evidence={})
    except Exception as exc:  # absolute safety net for preflight callers
        logger.debug("load guard probe failed for %s: %s", name, exc)
        return _not_busy("probe error; treated as idle")

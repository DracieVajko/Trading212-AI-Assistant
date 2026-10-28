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
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


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

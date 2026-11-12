"""Sanitize raw LLM output into structured JSON.

Pure helpers: never raise, never execute model output.
"""
from __future__ import annotations

import json
import re
from typing import Any


_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)
_BRACE_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _extract_block(text: str) -> str:
    text = text.strip()
    # <answer>...</answer>
    if text.startswith("<answer>") and text.endswith("</answer>"):
        text = text[len("<answer>"): -len("</answer>")].strip()
    # fenced
    text = _strip_fences(text)
    # if still surrounded by prose, grab first {...} or [...]
    if not (text.startswith("{") or text.startswith("[")):
        m = _BRACE_RE.search(text)
        if m:
            text = m.group(1).strip()
    return text


def _repair(text: str) -> str:
    # remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # best-effort single -> double quotes (only outside strings is hard; do simple)
    return text


def sanitize_llm_json(raw: Any) -> Any:
    """Return a parsed dict/list from raw LLM output, or None on failure.

    Strips markdown fences and <answer> tags, extracts the first JSON block,
    attempts a single trailing-comma repair. Never raises.
    """
    if raw is None:
        return None
    text = raw if isinstance(raw, str) else str(raw)
    text = text.strip()
    if not text:
        return None
    text = _extract_block(text)
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        repaired = _repair(text)
        if repaired == text:
            return None
        try:
            return json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            return None
    except Exception:
        return None

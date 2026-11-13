"""LM Studio eviction of disallowed models (reload loop)."""
from __future__ import annotations

from investment_engine.providers import lmstudio as lms


def _entries(*loaded):
    out = {}
    for key in loaded:
        out[key] = {"type": "llm", "loaded_instances": [{"id": f"{key}-inst"}]}
    return out


def test_evicts_reloaded_model_until_clean(monkeypatch):
    seq = [_entries("big-27b"), _entries("big-27b"), _entries()]
    calls = []
    monkeypatch.setattr(lms, "v1_models", lambda base: seq.pop(0) if seq else {})
    monkeypatch.setattr(lms, "unload_model_v1", lambda base, uid, **k: calls.append(uid) or True)
    monkeypatch.setattr(lms.time, "sleep", lambda s: None)

    res = lms.evict_disallowed_models("http://x:1234/v1", allowed={"small"}, timeout_s=10, poll_s=0)

    assert res["status"] == "clean"
    assert "big-27b" in res["evicted"]
    assert len(calls) >= 2


def test_timeout_when_model_keeps_reloading(monkeypatch):
    monkeypatch.setattr(lms, "v1_models", lambda base: _entries("big-27b"))
    monkeypatch.setattr(lms, "unload_model_v1", lambda *a, **k: True)
    monkeypatch.setattr(lms.time, "sleep", lambda s: None)

    res = lms.evict_disallowed_models("http://x:1234/v1", allowed={"small"}, timeout_s=0, poll_s=0)

    assert res["status"] == "timeout"
    assert "big-27b" in res["remaining"]


def test_noop_when_only_allowed_loaded(monkeypatch):
    monkeypatch.setattr(lms, "v1_models", lambda base: _entries("small"))

    res = lms.evict_disallowed_models("http://x:1234/v1", allowed={"small"}, timeout_s=5)

    assert res["status"] == "clean"
    assert res["evicted"] == []


def test_unavailable_when_v1_missing(monkeypatch):
    monkeypatch.setattr(lms, "v1_models", lambda base: None)

    res = lms.evict_disallowed_models("http://x:1234/v1", allowed={"small"})

    assert res["status"] == "unavailable"


def test_banned_pattern_matches_family():
    assert lms.is_banned_model("qwen3.8-27b-twin-turbo", ["27b"]) is True
    assert lms.is_banned_model("nvidia-nemotron-3.5-bolt-e4b", ["27b"]) is False
    assert lms.is_banned_model("anything", []) is False

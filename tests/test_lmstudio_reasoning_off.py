"""LM Studio: opt-in reasoning suppression.

Qwen3.5-family models on LM Studio default to thinking mode: every token goes
to ``reasoning_content`` and ``content`` stays empty, which the provider
correctly rejects. LM Studio honors ``reasoning_effort: "none"`` to answer
directly. It is opt-in (config), so non-thinking models keep the old payload.
"""
from __future__ import annotations

from types import SimpleNamespace

from investment_engine.providers import lmstudio as mod
from investment_engine.providers.lmstudio import LMStudioProvider


class _Resp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "local answer"}}]}


def _provider(monkeypatch, captured: dict, **kw) -> LMStudioProvider:
    def fake_post(url, json=None, timeout=None):
        captured.clear()
        captured.update(json or {})
        return _Resp()

    monkeypatch.setattr(mod.requests, "post", fake_post)
    monkeypatch.setattr(mod.LMStudioProvider, "_warmup_model", lambda self, model, **kw: None)
    return LMStudioProvider(model="qwen3.8-9b-distill", **kw)


def test_reasoning_effort_sent_when_configured(monkeypatch):
    captured: dict = {}
    provider = _provider(monkeypatch, captured, reasoning_effort="none")

    out = provider.generate("hi", stage="summary", context={"max_output_tokens": 8})

    assert out == "local answer"
    assert captured["reasoning_effort"] == "none"


def test_reasoning_effort_absent_by_default(monkeypatch):
    captured: dict = {}
    provider = _provider(monkeypatch, captured)

    assert provider.generate("hi", stage="summary", context={"max_output_tokens": 8}) == "local answer"
    assert "reasoning_effort" not in captured


def test_factory_wires_reasoning_effort_from_settings(monkeypatch):
    from investment_engine.providers.factory import ProviderFactory

    settings = SimpleNamespace(
        lmstudio_enabled=True,
        lm_studio_base_url="http://127.0.0.1:9/v1",
        lm_studio_model="qwen3.8-9b-distill",
        lm_studio_context_tokens=32768,
        lm_studio_max_output_tokens=8192,
        lm_studio_reasoning_effort="none",
        request_timeout_seconds=60,
        llamacpp_base_url="http://127.0.0.1:9/v1",
        llamacpp_model="qwen3.8-9b",
        llamacpp_context_tokens=4096,
        ollama_base_url="http://127.0.0.1:9",
        ollama_model="qwen3.8-9b-pi",
        ollama_context_tokens=128000,
    )

    chain = ProviderFactory.locals_chain(settings)

    assert chain.providers[0].reasoning_effort == "none"


def test_generate_tracks_local_ai_attempt(monkeypatch):
    """LOCALS runs must not report local_ai_requests_sent=0."""
    from investment_engine import main as main_mod

    captured: dict = {}
    provider = _provider(monkeypatch, captured)
    main_mod._reset_local_ai_tracker()
    try:
        assert provider.generate("hi", stage="summary", context={"max_output_tokens": 8}) == "local answer"
        assert main_mod._LOCAL_AI_TRACKER["attempts"] == 1
        assert main_mod._LOCAL_AI_TRACKER["requests_sent"] == 1
    finally:
        main_mod._reset_local_ai_tracker()

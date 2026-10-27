"""Ollama provider: usable with a plain Ollama endpoint (no LM Studio).

Ollama loads/evicts models itself, so the provider must send the per-request
budget correctly: ``num_ctx`` (prompt + completion, incl. thinking) and
``num_predict`` (output budget). ``max_tokens`` is an OpenAI field Ollama
ignores. Strictly offline: transport is faked.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from investment_engine.providers import ollama as mod
from investment_engine.providers.context_budget import context_target
from investment_engine.providers.ollama import OllamaProvider


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def _clean_cache():
    mod.reset_tags_cache()
    yield
    mod.reset_tags_cache()


def _wire(monkeypatch, post, tags=("test-model",)):
    monkeypatch.setattr(mod.requests, "post", post)
    monkeypatch.setattr(
        mod.requests, "get",
        lambda url, timeout=None: _Resp({"models": [{"name": t} for t in tags]}),
    )


def test_sends_num_ctx_and_num_predict(monkeypatch):
    captured: dict = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        return _Resp({"message": {"content": "ok"}})

    _wire(monkeypatch, fake_post)
    provider = OllamaProvider(
        base_url="http://fake:11434", model="test-model",
        max_context_tokens=32000, max_output_tokens=4096)

    out = provider.generate("x" * 32000, stage="summary", context={"max_output_tokens": 512})

    assert out == "ok"
    assert captured["options"]["num_predict"] == 512
    assert "max_tokens" not in captured["options"]
    assert captured["options"]["num_ctx"] == context_target(8000, 512, 32000)


def test_think_false_is_sent_when_configured(monkeypatch):
    captured: dict = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        return _Resp({"message": {"content": "ok"}})

    _wire(monkeypatch, fake_post)
    OllamaProvider(base_url="http://fake:11434", model="test-model", think=False).generate(
        "hi", stage="summary")

    assert captured["think"] is False


def test_think_is_absent_by_default(monkeypatch):
    captured: dict = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        return _Resp({"message": {"content": "ok"}})

    _wire(monkeypatch, fake_post)
    OllamaProvider(base_url="http://fake:11434", model="test-model").generate("hi", stage="summary")

    assert "think" not in captured


def test_unknown_model_lists_available_models(monkeypatch):
    calls: list[str] = []

    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        return _Resp({"message": {"content": "must not be called"}})

    _wire(monkeypatch, fake_post, tags=("qwen3:8b", "llama3:latest"))
    out = OllamaProvider(base_url="http://fake:11434", model="qwen3.8-9b-pi").generate(
        "hi", stage="decision")

    assert "not found" in out
    assert "qwen3:8b" in out
    assert calls == []


def test_thinking_only_response_is_an_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _Resp({"message": {"content": "", "thinking": "very long internal monologue"}})

    _wire(monkeypatch, fake_post)
    out = OllamaProvider(base_url="http://fake:11434", model="test-model").generate(
        "hi", stage="summary")

    assert "thinking only" in out
    assert "internal monologue" not in out


def test_tags_include_latest_alias(monkeypatch):
    _wire(monkeypatch, lambda *a, **k: None, tags=("qwen3:8b:latest",))

    ids = mod.ollama_model_ids("http://fake:11434")

    assert "qwen3:8b:latest" in ids
    assert "qwen3:8b" in ids


def test_factory_wires_ollama_settings(monkeypatch):
    from investment_engine.providers.factory import ProviderFactory

    settings = SimpleNamespace(
        ollama_base_url="http://fake:11434",
        ollama_model="test-model",
        ollama_context_tokens=32000,
        ollama_think="false",
        ollama_keep_alive="10m",
        ollama_auto_context=True,
        request_timeout_seconds=1800,
        lm_studio_max_output_tokens=4096,
        openrouter_api_key="",
    )

    provider = ProviderFactory._ollama(settings)

    assert provider.think is False
    assert provider.keep_alive == "10m"
    assert provider.max_context_tokens == 32000

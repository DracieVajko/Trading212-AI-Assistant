"""LM Studio model loading with an explicit, minimal context.

The server may keep a model loaded at its maximum context (observed
262144), which tanks throughput. The engine loads the model itself with
``context_length = prompt budget + completion budget`` (the completion
budget covers reasoning/thinking tokens), rounded up and capped by
``LM_STUDIO_CONTEXT_TOKENS``.

Loading is exclusive by default (like Ollama): the previously loaded LLM is
unloaded first, so 9B and 26B never sit in VRAM together.

Endpoints (LM Studio v1 REST): GET /api/v1/models, POST /api/v1/models/load,
POST /api/v1/models/unload. Strictly offline: transport is faked.
"""
from __future__ import annotations

import json

import pytest

from investment_engine.providers import lmstudio as mod
from investment_engine.providers.lmstudio import LMStudioProvider


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


def _model(key: str, *, loaded_context=None, max_context=262144, type_="llm") -> dict:
    return {
        "key": key,
        "type": type_,
        "max_context_length": max_context,
        "loaded_instances": (
            [{"id": key, "config": {"context_length": loaded_context}}]
            if loaded_context is not None
            else []
        ),
    }


class _FakeHTTP:
    def __init__(self, models, *, load_ok=True):
        self.models = {m["key"]: m for m in models}
        self.load_ok = load_ok
        self.calls: list[tuple[str, str, dict | None]] = []

    def get(self, url, timeout=None):
        self.calls.append(("GET", url, None))
        if url.endswith("/api/v1/models"):
            return _Resp({"models": list(self.models.values())})
        if url.endswith("/v1/models"):
            return _Resp({"data": [{"id": k} for k in self.models]})
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        if url.endswith("/api/v1/models/load"):
            if not self.load_ok:
                return _Resp({"error": "cannot load"}, status_code=500)
            self.models[json["model"]]["loaded_instances"] = [
                {"id": json["model"], "config": {"context_length": json["context_length"]}}
            ]
            return _Resp({"instance_id": json["model"], "status": "loaded"})
        if url.endswith("/api/v1/models/unload"):
            iid = json["instance_id"]
            for key, m in self.models.items():
                m["loaded_instances"] = [
                    i for i in (m.get("loaded_instances") or [])
                    if (i.get("id") or key) != iid
                ]
            return _Resp({"instance_id": iid})
        if url.endswith("/chat/completions"):
            return _Resp({"choices": [{"message": {"content": "ok"}}]})
        raise AssertionError(f"unexpected POST {url}")

    def load_calls(self):
        return [c for c in self.calls if c[1].endswith("/api/v1/models/load")]

    def unload_calls(self):
        return [c for c in self.calls if c[1].endswith("/api/v1/models/unload")]


@pytest.fixture(autouse=True)
def _clean_state():
    mod.reset_server_models_cache()
    mod.reset_v1_models_cache()
    mod._model_warmed.clear()
    mod._model_failed.clear()
    yield
    mod.reset_server_models_cache()
    mod.reset_v1_models_cache()
    mod._model_warmed.clear()
    mod._model_failed.clear()


def _provider(**kw) -> LMStudioProvider:
    kw.setdefault("model", "test-model")
    kw.setdefault("max_context_tokens", 32000)
    kw.setdefault("max_output_tokens", 8192)
    return LMStudioProvider(base_url="http://fake:1234/v1", **kw)


def _wire(monkeypatch, fake: _FakeHTTP) -> None:
    monkeypatch.setattr(mod.requests, "get", fake.get)
    monkeypatch.setattr(mod.requests, "post", fake.post)


def test_context_target_reserves_completion_budget():
    target = mod._context_target(prompt_tokens=8000, output_tokens=512, cap=32000)

    assert target >= int(8000 * 1.15) + 512
    assert target % 2048 == 0


def test_context_target_is_capped_by_settings():
    assert mod._context_target(prompt_tokens=200000, output_tokens=8192, cap=32000) == 32000


def test_loads_model_with_computed_context(monkeypatch):
    fake = _FakeHTTP([_model("test-model")])
    _wire(monkeypatch, fake)
    provider = _provider()
    prompt = "x" * 32000  # ~8000 tokens

    out = provider.generate(prompt, stage="summary", context={"max_output_tokens": 512})

    assert out == "ok"
    loads = fake.load_calls()
    assert len(loads) == 1
    body = loads[0][2]
    assert body["model"] == "test-model"
    assert body["context_length"] == mod._context_target(8000, 512, 32000)


def test_keeps_model_when_loaded_context_covers_requirement(monkeypatch):
    fake = _FakeHTTP([_model("test-model", loaded_context=12000)])
    _wire(monkeypatch, fake)
    provider = _provider()

    assert provider.generate("x" * 32000, stage="summary", context={"max_output_tokens": 512}) == "ok"
    assert fake.load_calls() == []


def test_reloads_grossly_oversized_context(monkeypatch):
    fake = _FakeHTTP([_model("test-model", loaded_context=262144)])
    _wire(monkeypatch, fake)
    provider = _provider()

    assert provider.generate("x" * 32000, stage="summary", context={"max_output_tokens": 512}) == "ok"
    assert len(fake.unload_calls()) == 1
    loads = fake.load_calls()
    assert len(loads) == 1
    assert loads[0][2]["context_length"] == mod._context_target(8000, 512, 32000)


def test_load_failure_falls_back_to_server_default(monkeypatch):
    fake = _FakeHTTP([_model("test-model")], load_ok=False)
    _wire(monkeypatch, fake)
    provider = _provider()

    # A failed load must not abort generation; the server may still serve it.
    assert provider.generate("x" * 32000, stage="summary", context={"max_output_tokens": 512}) == "ok"


def test_unloads_other_llm_instances_before_loading(monkeypatch):
    fake = _FakeHTTP([
        _model("qwen", loaded_context=12000),
        _model("gemma"),
    ])
    _wire(monkeypatch, fake)

    result = mod.ensure_model_context("http://fake:1234/v1", "gemma", 8192, exclusive=True)

    assert result["status"] == "loaded"
    unloads = fake.unload_calls()
    assert [u[2]["instance_id"] for u in unloads] == ["qwen"]
    assert fake.models["qwen"]["loaded_instances"] == []
    assert len(fake.load_calls()) == 1


def test_keeps_other_models_when_target_already_loaded(monkeypatch):
    fake = _FakeHTTP([
        _model("qwen", loaded_context=12000),
        _model("gemma", loaded_context=12000),
    ])
    _wire(monkeypatch, fake)

    result = mod.ensure_model_context("http://fake:1234/v1", "gemma", 8192, exclusive=True)

    assert result["status"] == "already_loaded"
    assert fake.unload_calls() == []


def test_exclusive_load_can_be_disabled(monkeypatch):
    fake = _FakeHTTP([
        _model("qwen", loaded_context=12000),
        _model("gemma"),
    ])
    _wire(monkeypatch, fake)

    result = mod.ensure_model_context("http://fake:1234/v1", "gemma", 8192, exclusive=False)

    assert result["status"] == "loaded"
    assert fake.unload_calls() == []
    assert fake.models["qwen"]["loaded_instances"] != []


def test_unload_already_unloaded_is_success(monkeypatch):
    fake = _FakeHTTP([_model("qwen")])

    def post(url, json=None, timeout=None):
        if url.endswith("/api/v1/models/unload"):
            return _Resp(
                {"error": {"type": "model_not_found",
                           "message": "Model with instance identifier 'qwen' is not loaded."}},
                status_code=404,
            )
        return fake.post(url, json=json, timeout=timeout)

    monkeypatch.setattr(mod.requests, "post", post)

    assert mod.unload_model_v1("http://fake:1234/v1", "qwen") is True


def test_unload_api_uses_v1_instance_id(monkeypatch):
    fake = _FakeHTTP([_model("qwen", loaded_context=12000)])
    _wire(monkeypatch, fake)

    assert mod._unload_via_api("http://fake:1234/v1", "qwen") is True

    unloads = fake.unload_calls()
    assert len(unloads) == 1
    assert unloads[0][2] == {"instance_id": "qwen"}
    assert fake.models["qwen"]["loaded_instances"] == []

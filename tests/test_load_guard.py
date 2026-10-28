"""Load-guard (provider busy detection) — settings knobs, health probes, wiring.

Strictly offline: no HTTP to real endpoints (monkeypatched), no local inference.
(User rule: tests use API/offline only.)
"""
from __future__ import annotations

import socket
from types import SimpleNamespace


def _settings(**kw):
    from investment_engine.config.settings import EngineSettings
    base = dict(
        provider="auto", api_only=False, execution_mode="auto",
        lmstudio_enabled=False,
        lm_studio_base_url="http://127.0.0.1:9/v1",
        lm_studio_model="qwen3.8-9b-distill",
        request_timeout_seconds=60,
        llamacpp_base_url="http://127.0.0.1:9/v1",
        ollama_base_url="http://127.0.0.1:9", ollama_model="ministral-3b-top",
        gemini_api_key="", mistral_api_key="", openrouter_api_key="",
        opencode_zen_api_key="",
    )
    base.update(kw)
    return EngineSettings(**{k: v for k, v in base.items()
                             if k in EngineSettings.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Task 1: settings knobs
# ---------------------------------------------------------------------------

def test_load_guard_settings_defaults():
    from investment_engine.config.settings import EngineSettings
    s = EngineSettings.from_defaults()
    assert s.load_guard_enabled is True
    assert s.load_guard_cooldown_s == 120
    assert s.load_guard_latency_ms == 2500
    assert s.local_timeout_cooldown_s == 300
    assert s.load_guard_cpu_pct == 85
    assert s.load_guard_ram_pct == 90
    assert s.load_guard_gpu_max_util_pct == 85
    assert s.load_guard_vram_min_free_mib == 1500
    assert s.load_guard_use_nvidia_smi is True
    assert s.load_guard_ollama_require_loaded is True


def test_load_guard_kill_switch_flag():
    s = _settings(load_guard_enabled=False)
    assert s.load_guard_enabled is False


# ---------------------------------------------------------------------------
# Task 2: health.py — Verdict, localhost detection, dispatch skeleton
# ---------------------------------------------------------------------------

def test_verdict_default_not_busy():
    from investment_engine.providers.health import Verdict
    v = Verdict(busy=False, reason="", evidence={})
    assert v.busy is False


def test_is_localhost_matches():
    from investment_engine.providers.health import is_localhost
    for u in ("http://127.0.0.1:1234/v1", "http://localhost:1234",
              "http://::1:1234", f"http://{socket.gethostname()}:1234"):
        assert is_localhost(u) is True, u


def test_is_localhost_remote():
    from investment_engine.providers.health import is_localhost
    assert is_localhost("http://100.88.219.120:1234") is False


def test_unknown_provider_not_busy():
    from investment_engine.providers.health import probe_provider_busy
    v = probe_provider_busy("Mystery", "http://127.0.0.1:9", _settings())
    assert v.busy is False and "unknown provider" in v.reason


# ---------------------------------------------------------------------------
# Task 3: LM Studio guard — latency, loading-state, localhost metrics
# ---------------------------------------------------------------------------

def test_lmstudio_latency_requires_both_attempts_slow(monkeypatch):
    from investment_engine.providers import health
    monkeypatch.setattr(health, "psutil", None, raising=False)
    monkeypatch.setattr(health.shutil, "which", lambda exe: None)
    v = health.probe_provider_busy("LM Studio", "http://127.0.0.1:1234/v1",
                                   _settings(), latencies=[0.05, 2.6])
    assert v.busy is False


def test_lmstudio_both_attempts_slow_is_busy():
    from investment_engine.providers.health import probe_provider_busy
    v = probe_provider_busy("LM Studio", "http://127.0.0.1:1234/v1",
                            _settings(), latencies=[2.6, 2.7])
    assert v.busy is True
    assert "latency" in v.reason.lower()


def test_lmstudio_loading_state_is_busy(monkeypatch):
    from investment_engine.providers import lmstudio as lm, health
    monkeypatch.setattr(lm, "v1_models", lambda url: {"openai/gpt-oss-20b": {"state": "loading"}})
    v = health.probe_provider_busy("LM Studio", "http://127.0.0.1:1234/v1", _settings())
    assert v.busy is True
    assert "loading" in v.reason.lower()


def test_lmstudio_unknown_api_not_busy(monkeypatch):
    from investment_engine.providers import lmstudio as lm, health
    monkeypatch.setattr(health, "psutil", None, raising=False)
    monkeypatch.setattr(health.shutil, "which", lambda exe: None)

    def _fail_get(url, **kw):
        raise AssertionError("no HTTP expected when v1 known")

    monkeypatch.setattr(lm, "v1_models", lambda url: None)  # unknown variant
    monkeypatch.setattr(health.requests, "get", _fail_get)
    v = health.probe_provider_busy("LM Studio", "http://127.0.0.1:1234/v1", _settings())
    assert v.busy is False


def test_lmstudio_v0_loading_state_is_busy(monkeypatch):
    from investment_engine.providers import lmstudio as lm, health
    monkeypatch.setattr(lm, "v1_models", lambda url: None)  # v0-era server

    class _R:
        status_code = 200
        def json(self):
            return {"data": [{"id": "m", "state": "loading"}]}

    monkeypatch.setattr(health.requests, "get", lambda url, **kw: _R())
    v = health.probe_provider_busy("LM Studio", "http://127.0.0.1:1234/v1", _settings())
    assert v.busy is True


def test_metrics_missing_degrades(monkeypatch):
    from investment_engine.providers import health

    monkeypatch.setattr(health, "psutil", None, raising=False)
    monkeypatch.setattr(health.shutil, "which", lambda exe: None)
    v = health.probe_provider_busy("LM Studio", "http://100.88.219.120:1234",
                                   _settings(), latencies=[0.1, 0.2])
    assert v.busy is False


def test_localhost_metrics_breach_busy(monkeypatch):
    from investment_engine.providers import health
    import types as _t

    fake_psutil = _t.SimpleNamespace(cpu_percent=lambda interval=None: 95.0,
                                     virtual_memory=lambda: _t.SimpleNamespace(percent=60.0))
    monkeypatch.setattr(health, "psutil", fake_psutil, raising=False)
    monkeypatch.setattr(health.shutil, "which", lambda exe: None)
    v = health.probe_provider_busy("LM Studio", "http://127.0.0.1:1234", _settings())
    assert v.busy is True
    assert "cpu" in v.reason.lower() or "cpu" in " ".join(v.evidence)


def test_remote_host_no_metric_signals(monkeypatch):
    from investment_engine.providers import health

    import types as _t
    fake_psutil = _t.SimpleNamespace(cpu_percent=lambda interval=None: 99.0,
                                     virtual_memory=lambda: _t.SimpleNamespace(percent=99.0))
    monkeypatch.setattr(health, "psutil", fake_psutil, raising=False)
    v = health.probe_provider_busy("LM Studio", "http://100.88.219.120:1234", _settings())
    assert v.busy is False  # remote metrics must never decide for another machine


def test_kill_switch_no_probe(monkeypatch):
    from investment_engine.providers import health, lmstudio as lm

    lm.reset_v1_models_cache()

    def _boom(url, **kw):
        raise AssertionError("no HTTP expected when load guard disabled")

    monkeypatch.setattr(health.requests, "get", _boom)
    monkeypatch.setattr(lm, "v1_models", _boom)
    s = _settings(load_guard_enabled=False)
    v = health.probe_provider_busy("LM Studio", "http://127.0.0.1:1234/v1", s)
    assert v.busy is False


# ---------------------------------------------------------------------------
# Task 4: Pi guards — llama.cpp latency, Ollama resident-model check
# ---------------------------------------------------------------------------

_PI = "http://100.125.47.31:11434"


def _router(routes: dict, sleep_s: float = 0.0):
    """Fake health.requests.get routing by URL suffix; raises on unknown."""
    import time as _t

    def _get(url, **kw):
        if sleep_s:
            _t.sleep(sleep_s)
        if url not in routes:
            raise AssertionError(f"unexpected URL {url}")
        return routes[url]


    return _get


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_ollama_model_cold_is_busy(monkeypatch):
    from investment_engine.providers import health
    s = _settings(ollama_base_url=_PI, ollama_model="ministral-3b-top")
    routes = {f"{_PI}/api/ps": _Resp({"models": []})}
    monkeypatch.setattr(health.requests, "get", _router(routes))
    v = health.probe_provider_busy("Ollama", _PI, s)
    assert v.busy is True
    assert "model_cold" in v.reason


def test_ollama_resident_not_busy(monkeypatch):
    from investment_engine.providers import health
    s = _settings(ollama_base_url=_PI, ollama_model="ministral-3b-top")
    routes = {f"{_PI}/api/ps": _Resp({"models": [{"name": "ministral-3b-top:latest"}]})}
    monkeypatch.setattr(health.requests, "get", _router(routes))
    v = health.probe_provider_busy("Ollama", _PI, s)
    assert v.busy is False


def test_ollama_ps_absent_not_busy(monkeypatch):
    from investment_engine.providers import health
    s = _settings(ollama_base_url=_PI, ollama_model="ministral-3b-top")
    routes = {f"{_PI}/api/ps": _Resp({}, status=404)}
    monkeypatch.setattr(health.requests, "get", _router(routes))
    v = health.probe_provider_busy("Ollama", _PI, s)
    assert v.busy is False


def test_ollama_require_loaded_off(monkeypatch):
    from investment_engine.providers import health
    s = _settings(ollama_base_url=_PI, ollama_model="ministral-3b-top",
                  load_guard_ollama_require_loaded=False)
    routes = {f"{_PI}/api/ps": _Resp({"models": []})}
    monkeypatch.setattr(health.requests, "get", _router(routes))
    v = health.probe_provider_busy("Ollama", _PI, s)
    assert v.busy is False


def test_ollama_latest_suffix_matches(monkeypatch):
    from investment_engine.providers import health
    # model pinned WITHOUT suffix, resident WITH :latest -> must count resident
    s = _settings(ollama_base_url=_PI, ollama_model="ministral-3b-top")
    routes = {f"{_PI}/api/ps": _Resp({"models": [{"name": "ministral-3b-top:latest"}]})}
    monkeypatch.setattr(health.requests, "get", _router(routes))
    assert health.probe_provider_busy("Ollama", _PI, s).busy is False


def test_ollama_latency_slow_is_busy(monkeypatch):
    from investment_engine.providers import health
    s = _settings(ollama_base_url=_PI, ollama_model="ministral-3b-top",
                  load_guard_latency_ms=10)
    routes = {f"{_PI}/api/ps": _Resp({"models": [{"name": "ministral-3b-top"}]}),
              f"{_PI}/api/tags": _Resp({"models": []})}
    monkeypatch.setattr(health.requests, "get", _router(routes, sleep_s=0.05))
    v = health.probe_provider_busy("Ollama", _PI, s)
    assert v.busy is True
    assert "latency" in v.reason.lower()


def test_llamacpp_slow_busy(monkeypatch):
    from investment_engine.providers import health

    base = "http://100.125.47.31:11435/v1"
    s = _settings(llamacpp_base_url=base, load_guard_latency_ms=10)
    routes = {f"{base}/models": _Resp({"data": [{"id": "qwen3.8-9b"}]})}
    monkeypatch.setattr(health.requests, "get", _router(routes, sleep_s=0.05))
    v = health.probe_provider_busy("llama.cpp", base, s)
    assert v.busy is True
    assert "latency" in v.reason.lower()

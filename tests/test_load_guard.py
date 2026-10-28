"""Load-guard (provider busy detection) — settings knobs, health probes, wiring.

Strictly offline: no HTTP to real endpoints (monkeypatched), no local inference.
(User rule: tests use API/offline only.)
"""
from __future__ import annotations

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

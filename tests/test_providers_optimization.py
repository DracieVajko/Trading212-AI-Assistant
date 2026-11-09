"""Validated AI model optimization configs (Task 2).

Strictly offline: pure data mapping, no HTTP, no local endpoints.
"""
from __future__ import annotations


def test_lmstudio_config_has_validated_keys():
    from investment_engine.providers.optimization import get_best_config
    cfg = get_best_config("qwen3.8-9b-distill", "lmstudio", vram_gb=6)
    assert cfg.context_length in (8192, 16384, 32768)
    assert cfg.flash_attention is True
    assert cfg.offload_kv_cache_to_gpu is True
    assert cfg.eval_batch_size in (128, 256, 512, 1024, 2048)


def test_save_and_load_config_roundtrip(tmp_path):
    from investment_engine.providers.optimization import (
        AIModelConfig, load_config, save_config,
    )
    cfg = AIModelConfig(
        model="test-model", backend="ollama", context_length=16384,
        flash_attention=True, offload_kv_cache_to_gpu=False,
        eval_batch_size=256, tokens_per_sec=12.5, quality_score=0.9,
        validated_at="2026-11-09",
    )
    path = tmp_path / "opt.json"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded["test-model"]["context_length"] == 16384
    assert loaded["test-model"]["backend"] == "ollama"


def test_unknown_model_falls_back_to_safe_defaults():
    from investment_engine.providers.optimization import get_best_config
    cfg = get_best_config("some-unknown-model")
    assert cfg.context_length == 8192
    assert cfg.flash_attention is False

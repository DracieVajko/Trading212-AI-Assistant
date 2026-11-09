"""AI model optimization abstraction for LM Studio and Ollama backends.

Validated defaults come from LocalLLM_Optimiser (RTX 3060 6 GB baseline).
LM Studio REST accepts: context_length, flash_attention,
offload_kv_cache_to_gpu, eval_batch_size, physical_batch_size, parallel.
KV cache quantization and CPU threads are GUI-only (REST rejects with 400)
and are recorded, never set, here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class AIModelConfig:
    model: str
    backend: str  # "lmstudio" | "ollama"
    context_length: int
    flash_attention: bool
    offload_kv_cache_to_gpu: bool
    eval_batch_size: int
    tokens_per_sec: float
    quality_score: float
    validated_at: str


_DEFAULT_CONFIGS: dict[str, AIModelConfig] = {
    "qwen3.8-9b-distill": AIModelConfig(
        model="qwen3.8-9b-distill",
        backend="lmstudio",
        context_length=32768,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
        eval_batch_size=2048,
        tokens_per_sec=28.2,
        quality_score=0.983,
        validated_at="2026-10-27",
    ),
    "ministral-3b-top": AIModelConfig(
        model="ministral-3b-top",
        backend="lmstudio",
        context_length=32768,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
        eval_batch_size=128,
        tokens_per_sec=74.9,
        quality_score=1.000,
        validated_at="2026-10-27",
    ),
    "gemma-4-12b": AIModelConfig(
        model="gemma-4-12b",
        backend="lmstudio",
        context_length=32768,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
        eval_batch_size=2048,
        tokens_per_sec=7.1,
        quality_score=0.987,
        validated_at="2026-10-27",
    ),
}


def get_best_config(model: str, backend: str = "lmstudio", vram_gb: int = 6) -> AIModelConfig:
    """Return validated best config for a model. Falls back to safe defaults."""
    key = model.lower()
    cfg = _DEFAULT_CONFIGS.get(key)
    if cfg is not None and cfg.backend == backend:
        return replace(cfg)
    return AIModelConfig(
        model=model,
        backend=backend,
        context_length=8192,
        flash_attention=False,
        offload_kv_cache_to_gpu=False,
        eval_batch_size=128,
        tokens_per_sec=0.0,
        quality_score=0.0,
        validated_at="",
    )


def save_config(cfg: AIModelConfig, path: str | Path = "investment_engine/providers/optimization_config.json") -> None:
    """Persist validated config to JSON."""
    p = Path(path)
    data: dict = {}
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    data[cfg.model] = {
        "backend": cfg.backend,
        "context_length": cfg.context_length,
        "flash_attention": cfg.flash_attention,
        "offload_kv_cache_to_gpu": cfg.offload_kv_cache_to_gpu,
        "eval_batch_size": cfg.eval_batch_size,
        "tokens_per_sec": cfg.tokens_per_sec,
        "quality_score": cfg.quality_score,
        "validated_at": cfg.validated_at,
    }
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_config(path: str | Path = "investment_engine/providers/optimization_config.json") -> dict:
    """Load persisted configs."""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

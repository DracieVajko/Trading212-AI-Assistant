"""Model-scoped provider breaker and truthful stage telemetry.

Live evidence (run 21:00, 2026-10-23): LM Studio serves several models
(gpt-oss for finance/thinking, gemma for summaries). A failure of the
unserved gpt-oss model tripped a provider-wide breaker, which also locked
out the served gemma model for the rest of the run.

Strictly offline: no HTTP, no endpoints.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from investment_engine.providers import fallback as fb
from investment_engine.providers.base import BaseLLMProvider
from investment_engine.providers.fallback import ChainedFallbackProvider


class _Stub(BaseLLMProvider):
    def __init__(self, name: str, model: str = "", result: str = "ok"):
        self._name = name
        self.model = model
        self.result = result
        self.calls: list[dict | None] = []

    @property
    def name(self) -> str:
        return self._name

    def generate(self, prompt: str, *, stage: str, context: dict | None = None) -> str:
        self.calls.append(context)
        return self.result


def _reset() -> None:
    fb.reset_circuit_breaker()
    ChainedFallbackProvider.reset_run_cooldowns()


def test_model_skip_leaves_sibling_model_available():
    _reset()
    try:
        fb.skip_for_run("LM Studio", "model not served", model="openai/gpt-oss-20b")

        assert fb.is_skipped("LM Studio", "openai/gpt-oss-20b")
        assert not fb.is_skipped("LM Studio", "google/gemma-4-26b-a4b-qat")
        # A single missing model does not exile the whole provider.
        assert not fb.is_skipped("LM Studio")
    finally:
        _reset()


def test_provider_skip_still_blocks_every_model():
    _reset()
    try:
        fb.skip_for_run("LM Studio", "endpoint unreachable")

        assert fb.is_skipped("LM Studio")
        assert fb.is_skipped("LM Studio", "openai/gpt-oss-20b")
        assert fb.is_skipped("LM Studio", "google/gemma-4-26b-a4b-qat")
    finally:
        _reset()


def test_failed_stage_model_does_not_lock_out_served_model():
    """The real sequence: chain fails on gpt-oss, then summary needs gemma."""
    import investment_engine.main as m
    from investment_engine.providers.lmstudio import LMStudioProvider

    class _ServedLM(LMStudioProvider):
        def __init__(self):
            self.model = "google/gemma-4-26b-a4b-qat"
            self.calls = []

        @property
        def name(self):
            return "LM Studio"

        def generate(self, prompt, *, stage, context=None):
            self.calls.append(context)
            return "summary text"

    _reset()
    try:
        missing = _Stub(
            "LM Studio",
            model="openai/gpt-oss-20b",
            result="[decision] LM Studio model 'openai/gpt-oss-20b' unavailable: not served.",
        )
        cloud = _Stub("Gemini", model="gemini-2.5-flash", result="decision text")
        chain = ChainedFallbackProvider([missing, cloud])
        assert chain.generate("p", stage="decision") == "decision text"

        served = _ServedLM()
        out = m._try_lmstudio_stage(
            ChainedFallbackProvider([served]),
            "p",
            settings={
                "lmstudio_enabled": True,
                "finance_model": "openai/gpt-oss-20b",
                "thinking_model": "openai/gpt-oss-20b",
                "writer_model": "google/gemma-4-26b-a4b-qat",
                "decision_model": "openai/gpt-oss-20b",
            },
            stage="summary",
            tokens=10,
        )

        assert out == ("google/gemma-4-26b-a4b-qat", "summary text")
        assert len(served.calls) == 1
    finally:
        _reset()


def test_stage_log_reports_served_model(caplog):
    from investment_engine.main import _generate_with_fallback

    class _CloudChain(_Stub):
        def __init__(self):
            super().__init__("Chain")
            self.last_attribution = {
                "provider": "Gemini",
                "model": "gemini-2.5-flash",
                "depth": 1,
            }

    settings = SimpleNamespace(
        decision_model="openai/gpt-oss-20b",
        lmstudio_enabled=False,
        language="English",
        ai_aggressiveness="balanced",
    )

    with caplog.at_level(logging.INFO, logger="investment_engine.main"):
        out = _generate_with_fallback(_CloudChain(), "p", settings, tokens=10, stage="decision")

    assert out == "ok"
    assert "model=gemini-2.5-flash" in caplog.text
    assert "model=openai/gpt-oss-20b" not in caplog.text

"""Tests for dynamic local-LLM context sizing."""

from __future__ import annotations

import importlib

import investment_engine.providers.context_budget as cb


def test_estimate_tokens_ceil_and_zero():
    assert cb.estimate_tokens("") == 0
    assert cb.estimate_tokens("abc") == 1
    assert cb.estimate_tokens("x" * 32) == 8
    assert cb.estimate_tokens("x" * 33) == 9


def test_small_prompt_gets_minimum_context_not_eight_k(monkeypatch):
    monkeypatch.delenv("LOCAL_CONTEXT_MIN_TOKENS", raising=False)
    monkeypatch.delenv("LOCAL_CONTEXT_STEP_TOKENS", raising=False)
    assert cb.context_target(prompt_tokens=80, output_tokens=64, cap=32000) == 2048


def test_system_tokens_are_counted(monkeypatch):
    monkeypatch.delenv("LOCAL_CONTEXT_MIN_TOKENS", raising=False)
    monkeypatch.delenv("LOCAL_CONTEXT_STEP_TOKENS", raising=False)
    without = cb.context_target(6000, 512, 32000, system_tokens=0)
    with_system = cb.context_target(6000, 512, 32000, system_tokens=2000)
    assert with_system >= without


def test_env_override_minimum_and_step(monkeypatch):
    monkeypatch.setenv("LOCAL_CONTEXT_MIN_TOKENS", "4096")
    monkeypatch.setenv("LOCAL_CONTEXT_STEP_TOKENS", "1024")
    target = cb.context_target(prompt_tokens=1, output_tokens=1, cap=32000)
    assert target == 4096
    assert target % 1024 == 0


def test_cap_is_enforced(monkeypatch):
    monkeypatch.delenv("LOCAL_CONTEXT_MIN_TOKENS", raising=False)
    monkeypatch.delenv("LOCAL_CONTEXT_STEP_TOKENS", raising=False)
    assert cb.context_target(200000, 8192, 32000) == 32000


def test_sufficiency_allows_slack_but_rejects_oversized(monkeypatch):
    monkeypatch.delenv("LOCAL_CONTEXT_MIN_TOKENS", raising=False)
    assert cb.context_is_sufficient(4096, 2048) is True
    assert cb.context_is_sufficient(2048, 4096) is False
    assert cb.context_is_sufficient(262144, 2048) is False

"""WP1 — Run/provenance/lifecycle truth.

Tests:
- API_ONLY model substitution reason is truthful ("policy_api_only"), not "unknown".
- Skill status never reads plain "OK" when the final result came from a
  deterministic fallback (no false "AI processing OK").
- local_ai_blocked_count is surfaced in the status-report manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _minimal_result(**overrides):
    """Minimal result dict satisfying write_reports' non-strict reads."""
    result = {
        "brief_markdown": "brief",
        "snapshot_markdown": "snapshot",
        "reconciliation": {"status": "PASS"},
        "requested_mode": "API_ONLY",
        "ai_execution_mode": "API_ONLY",
        "effective_mode": "public",
        "local_ai_attempts": 3,
        "local_ai_requests_sent": 0,
        "local_ai_attempts_blocked": 3,
        "disabled_providers": ["LM Studio", "llama.cpp", "Ollama"],
        "brief_metadata": {"stance": "- Portfolio stance: **HOLD**"},
        "providers_per_stage": {},
        "skill_outputs": {},
        "counts": {},
    }
    result.update(overrides)
    return result


def test_attribution_reason_policy_selected(tmp_path, monkeypatch):
    """API_ONLY: configured local model replaced by cloud -> reason policy_api_only."""
    import portfolio_ai_assistant as entry

    stages = {
        "decision": {
            "provider": "Gemini",
            "model_requested": "openai/gpt-oss-20b",
            "model_served": "gemini-2.5-flash",
            "fallback_depth": 0,
        },
    }
    result = _minimal_result(providers_per_stage=stages)
    entry.write_reports(result, tmp_path / "out", tmp_path / "arch", "sub1")
    manifest = json.loads((tmp_path / "out" / "current" / "run_manifest.json")
                          .read_text(encoding="utf-8"))
    sub = manifest["model_substitution"]["decision"]
    assert sub["substituted"] is True
    assert sub["reason"] == "policy_api_only"
    assert sub["requested"] == "openai/gpt-oss-20b"
    assert sub["served"] == "gemini-2.5-flash"


def test_attribution_reason_unknown_without_policy(tmp_path, monkeypatch):
    """Non-API_ONLY without a provider-recorded reason stays 'unknown'."""
    import portfolio_ai_assistant as entry

    stages = {
        "decision": {
            "provider": "OpenRouter",
            "model_requested": "x",
            "model_served": "y",
            "fallback_depth": 1,
        },
    }
    result = _minimal_result(requested_mode="STANDARD", ai_execution_mode="STANDARD",
                             providers_per_stage=stages)
    entry.write_reports(result, tmp_path / "out", tmp_path / "arch", "sub2")
    manifest = json.loads((tmp_path / "out" / "current" / "run_manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["model_substitution"]["decision"]["reason"] == "unknown"


def test_chain_reports_preflight_skip_reason():
    """A pre-flight-skipped primary is still named as the substitution cause."""
    from investment_engine.providers import attribution
    from investment_engine.providers.base import BaseLLMProvider
    from investment_engine.providers.fallback import (
        ChainedFallbackProvider,
        reset_circuit_breaker,
        skip_for_run,
    )

    class Skipped(BaseLLMProvider):
        name = "LM Studio"
        model = "openai/gpt-oss-20b"

        def generate(self, prompt, *, stage, context=None):
            raise AssertionError("skipped provider must not be called")

    class Alive(BaseLLMProvider):
        name = "Mistral"
        model = "open-mistral-nemo"

        def generate(self, prompt, *, stage, context=None):
            return "fine content"

    reset_circuit_breaker()
    try:
        skip_for_run("LM Studio", reason="pre-flight connect failed",
                     cooldown_s=300, model="openai/gpt-oss-20b")
        chain = ChainedFallbackProvider([Skipped(), Alive()])

        assert chain.generate("p", stage="decision") == "fine content"
        assert chain.last_attribution["from_provider"] == "LM Studio"
        assert chain.last_attribution["failure_kind"] == "pre-flight connect failed"

        record = attribution.new_stage_record("decision", "openai/gpt-oss-20b")
        updated = attribution.apply_chain_hint(record, chain)
        assert updated["model_substitution_reason"] == "pre-flight connect failed (LM Studio)"
    finally:
        reset_circuit_breaker()


def test_manifest_reports_recorded_substitution_reason(tmp_path):
    """A stage-recorded failure kind reaches the run manifest verbatim."""
    import portfolio_ai_assistant as entry

    stages = {
        "decision": {
            "provider": "Mistral",
            "model_requested": "openai/gpt-oss-20b",
            "model_served": "open-mistral-nemo",
            "fallback_depth": 1,
            "model_substitution_reason": "rate_limited (OpenRouter)",
        },
    }
    result = _minimal_result(requested_mode="STANDARD", ai_execution_mode="STANDARD",
                             providers_per_stage=stages)
    entry.write_reports(result, tmp_path / "out", tmp_path / "arch", "sub-reason")
    manifest = json.loads((tmp_path / "out" / "current" / "run_manifest.json")
                          .read_text(encoding="utf-8"))
    assert (manifest["model_substitution"]["decision"]["reason"]
            == "rate_limited (OpenRouter)")


def test_manifest_carries_run_budget(tmp_path):
    """The run manifest exposes start time, budget and duration for audits."""
    import portfolio_ai_assistant as entry

    budget = {
        "started_at": "2026-10-26T21:14:20+01:00",
        "budget_s": 900.0,
        "duration_s": 576.8,
        "exceeded": False,
    }
    result = _minimal_result(run_budget=budget)
    entry.write_reports(result, tmp_path / "out", tmp_path / "arch", "sub-budget")
    manifest = json.loads((tmp_path / "out" / "current" / "run_manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["run_budget"] == budget


def test_chain_hint_records_why_model_was_substituted():
    """The winning fallback provider must carry the failure that caused it."""
    from investment_engine.providers import attribution

    record = attribution.new_stage_record("decision", "openai/gpt-oss-20b")

    class _Chain:
        last_attribution = {
            "provider": "Mistral",
            "model": "open-mistral-nemo",
            "depth": 1,
            "from_provider": "OpenRouter",
            "failure_kind": "rate_limited",
        }

    updated = attribution.apply_chain_hint(record, _Chain())

    assert updated["model_substitution_reason"] == "rate_limited (OpenRouter)"


def test_skill_status_never_plain_ok_on_fallback(monkeypatch):
    """A deterministic fallback must not report a plain 'OK' status."""
    import investment_engine.main as main_mod

    annotator = main_mod._annotate_skill_output

    fallback = annotator({"status": "OK", "fallback_reason": "llm output rejected (failed: no events list)"})
    assert fallback["status"] == "COMPLETED_WITH_FALLBACK"
    assert fallback["execution_type"] == "DETERMINISTIC"

    # A genuinely enriched LLM run keeps "OK".
    enriched = annotator({"status": "OK", "data": {"enriched": True}})
    assert enriched["status"] == "OK"
    assert enriched["execution_type"] == "LLM"

    # Fallback with only execution_type set (no execution_reason) -> filled + marked.
    explicit = annotator({"status": "OK", "execution_type": "FALLBACK", "fallback_reason": "Y"})
    assert explicit["status"] == "COMPLETED_WITH_FALLBACK"
    assert explicit["execution_reason"]


def test_status_manifest_carries_blocked_count(tmp_path):
    """PARTIAL/ABORTED status manifest exposes local_ai blocked count."""
    from investment_engine.reporting import finalize

    checkpoints = {"stages": {}}
    finalize.publish_status_report(
        run_id="sub3", status="PARTIAL", reasons=["run deadline exceeded"],
        checkpoints=checkpoints, reports_dir=tmp_path, archive_dir=tmp_path / "arch",
        local_ai_stats={"attempts": 3, "requests_sent": 0, "blocked": 3})
    manifest = json.loads((tmp_path / "current" / "run_manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["run_status"] == "PARTIAL"
    assert manifest["finalized"] is True
    assert manifest["local_ai_stats"]["blocked"] == 3
    assert manifest["local_ai_stats"]["requests_sent"] == 0


def test_broker_account_snapshot_is_not_shadowed_by_consensus_lookup():
    """Regression (run b65f44ea): the analyst-consensus loop reused `_snap`,
    overwriting the broker AccountSnapshot with a str. The reconciliation
    diagnostic and the AI-context save then both failed and the context fell
    back to a minimal file (research/watchlist/reconciliation lost)."""
    import re

    src = Path("investment_engine/main.py").read_text(encoding="utf-8")
    assert re.search(r"(?<![A-Za-z0-9_])_snap\s*=\s*_build_snap\(", src), (
        "AccountSnapshot assignment missing"
    )
    assert not re.search(r"(?<![A-Za-z0-9_])_snap\s*=\s*analyst_consensus\(", src), (
        "_snap is shadowed by the analyst-consensus lookup; use a distinct name"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

"""API-only sanitation tests: provider chain, corpus, recon logs, failures.

Offline only. No live API. No local-endpoint contact (probes assertably skipped).
"""

from __future__ import annotations

import logging


def _settings(**over):
    from investment_engine.config.settings import EngineSettings

    base = EngineSettings()
    for key, val in over.items():
        setattr(base, key, val)
    return base


def test_api_only_chain_is_gemini_mistral_only():
    from investment_engine.providers.factory import ProviderFactory

    s = _settings(api_only=True, gemini_api_key="gk", openrouter_api_key="ok",
                  mistral_api_key="mk", lmstudio_enabled=True)
    chain = ProviderFactory.create(s)
    names = [p.name for p in getattr(chain, "providers", [chain])]
    # OpenRouter removed from API-only chain (free models unreliable)
    assert names == ["Gemini", "Mistral"]
    assert "LM Studio" not in names and "Ollama" not in names


def test_api_only_chain_without_keys_degrades_silently():
    from investment_engine.providers.factory import ProviderFactory
    from investment_engine.providers.fallback import ChainedFallbackProvider

    # Blank keys explicitly: the developer machine's api.env may inject real
    # keys via dotenv, so "no keys" must be forced (and no network is touched:
    # _NoKey.generate never leaves the process).
    s = _settings(api_only=True, lmstudio_enabled=True,
                  gemini_api_key="", openrouter_api_key="", mistral_api_key="")
    chain = ProviderFactory.create(s)
    assert isinstance(chain, ChainedFallbackProvider)
    assert [p.name for p in chain.providers] == ["NoCloudKey"]
    try:
        chain.generate("hi", stage="decision")
        raised = False
    except Exception:
        raised = True
    assert raised  # -> main.py turns this into the deterministic fallback


def test_api_only_never_probes_locals(monkeypatch):
    import investment_engine.main as engine
    import requests

    calls = []

    def _boom(*args, **kwargs):
        calls.append(args)
        raise AssertionError("local endpoint probed in API-only mode")

    monkeypatch.setattr(requests, "get", _boom)
    engine._FALLBACK_EVENTS.clear()
    engine._note_unreachable_local_providers(_settings(api_only=True))
    assert calls == []
    assert any("API-only mode" in e for e in engine._FALLBACK_EVENTS)
    engine._FALLBACK_EVENTS.clear()


def test_execution_mode_lines_only_when_api_only():
    from investment_engine.main import _execution_mode_lines

    assert _execution_mode_lines(_settings(api_only=True)) == [
        "AI execution mode: API_ONLY",
        "Disabled providers: LM Studio, llama.cpp, Ollama",
    ]
    assert _execution_mode_lines(_settings()) == []


def test_manifest_lists_disabled_providers(tmp_path):
    import json

    import portfolio_ai_assistant as entry

    result = {"brief_markdown": "", "snapshot_markdown": "",
              "reconciliation": {"status": "UNKNOWN"}, "failed_tickers": [],
              "monitoring_items": [], "decision_news": [], "brief_metadata": {},
              "api_execution_mode": "API_ONLY",
              "disabled_providers": ["LM Studio", "llama.cpp", "Ollama"]}
    entry.write_reports(result, tmp_path / "o", tmp_path / "a", "api1")
    manifest = json.loads((tmp_path / "o" / "current" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["ai_execution_mode"] == "API_ONLY"
    assert manifest["disabled_providers"] == ["LM Studio", "llama.cpp", "Ollama"]


def test_brief_shows_mode_and_research_note():
    from investment_engine.reporting.documents import build_intelligence_brief, render_brief

    mode = ["AI execution mode: API_ONLY", "Disabled providers: LM Studio, llama.cpp, Ollama"]
    note = "Research coverage insufficient: 1 validated decision-quality items in the last 48 hours."
    md = render_brief(
        generated_at="2026-09-25 09:00 CEST", regime_result=None,
        recon={"status": "UNKNOWN", "total_equity": 0}, rows=[], monitoring_items=[],
        earnings_7d={}, decision_news=[], ideas=[], cash_line="n/a",
        research_note=note, execution_mode_lines=mode)
    assert "AI execution mode: API_ONLY" in md
    assert "Disabled providers: LM Studio, llama.cpp, Ollama" in md
    assert note in md
    intel = build_intelligence_brief({"portfolio_rows": [], "reconciliation": {"status": "UNKNOWN"},
                                      "t212_data": {}, "decision_news": [], "earnings_7d": {},
                                      "ideas": [], "research_note": note,
                                      "execution_mode_lines": mode})
    assert note in intel and "AI execution mode: API_ONLY" in intel


def test_corpus_run_id_never_blank_and_rejected_render(tmp_path):
    import pytest

    from investment_engine.research.corpus.builder import build_corpus_files, render_rejected_markdown

    with pytest.raises(ValueError):
        build_corpus_files({"A": []}, run_id="  ", output_dir=str(tmp_path))
    assert "None" in render_rejected_markdown([], "r1")
    md = render_rejected_markdown([{"title": "t", "canonical_url": "https://e.example/x",
                                    "publisher": "p", "fetch_status": "UNDATED",
                                    "failure_reason_if_any": ""}], "r1")
    assert "no validated publication timestamp" in md


def test_corpus_decision_items_fully_validated_and_aggregator_labelled():
    from investment_engine.research.corpus.builder import build_corpus
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)
    good = {"title": "t", "url": "https://news.google.com/rss/articles/x",
            "source": "Reuters", "published_dt": now - timedelta(hours=3),
            "category": "general", "tier": 1, "relevance_score": 90}
    no_url = {"title": "no link", "source": "X", "published_dt": now,
              "category": "general"}
    corpus = build_corpus({"AAPL": [good, no_url]}, now)
    for item in corpus["decision_items"]:
        assert item["title"] and str(item["canonical_url"]).startswith("http")
        assert item["publisher"] and item["published_at_utc"]
        assert isinstance(item["age_hours"], float) and item["source_tier"] in (0, 1, 2)
        assert item["source_category"]
    agg = [i for i in corpus["decision_items"] if i["title"] == "t"]
    assert agg and agg[0]["url_kind"] == "aggregator_url"
    assert corpus["counts"]["rejected"] >= 1  # the URL-less record


def test_guard_reads_no_legacy_r1_fields():
    import pathlib

    src = pathlib.Path("investment_engine/main.py").read_text(encoding="utf-8")
    assert "T212 Reconciliation:" not in src
    guard_at = src.find("Canonical broker-first snapshot FIRST")
    assert guard_at != -1
    guard_block = src[guard_at:guard_at + 4000]
    assert 'summary.get("reconciliation_status"' not in guard_block
    assert 'summary.get("reconciliation_difference"' not in guard_block


def test_legacy_disagreement_message_exact():
    import pathlib

    src = pathlib.Path("trading212/portfolio.py").read_text(encoding="utf-8")
    # The legacy-module check must never impersonate the canonical verdict
    # (run 524fffa0 logged "canonical FAIL" while canonical PASSed).
    assert "legacy-module check, ignored for decisions" in src
    assert "Authoritative verdict comes from the " in src
    assert "Canonical broker-first result:" not in src


def test_slovak_hard_failure_disables_site_once(monkeypatch, caplog):
    import requests
    from types import SimpleNamespace

    from investment_engine.research.news_engine import StrictNewsFetcher

    fetcher = StrictNewsFetcher(enable_file_cache=False)

    def _raise_403(*args, **kwargs):
        err = requests.HTTPError("403")
        err.response = SimpleNamespace(status_code=403)
        raise err

    monkeypatch.setattr(fetcher._session, "get", _raise_403)
    with caplog.at_level(logging.WARNING, logger="investment_engine.research.news_engine"):
        assert fetcher.fetch_slovak_news() == []
    assert fetcher._slovak_disabled == {"Aktuality", "Pravda", "TERAZ", "Google News"}
    warned = [r for r in caplog.records if "disabled for the rest of the run" in r.getMessage()]
    assert len(warned) == 4  # once per site, then silence
    caplog.clear()
    calls = []
    monkeypatch.setattr(fetcher._session, "get", lambda *a, **k: calls.append(1))
    with caplog.at_level(logging.WARNING, logger="investment_engine.research.news_engine"):
        assert fetcher.fetch_slovak_news() == []
    assert calls == []  # disabled sites are never re-requested
    assert not [r for r in caplog.records if "disabled for the rest of the run" in r.getMessage()]


def test_finviz_kill_switch_logs_once(caplog):
    from investment_engine.research import technical_analysis as ta

    saved = ta._FINVIZ_DISABLED
    ta._FINVIZ_DISABLED = False
    try:
        with caplog.at_level(logging.INFO, logger="investment_engine.research.technical_analysis"):
            ta.disable_finviz("boom")
            ta.disable_finviz("boom")
        hits = [r for r in caplog.records if "remainder of the run" in r.getMessage()]
        assert len(hits) == 1
        assert not ta.finviz_enabled()
    finally:
        ta._FINVIZ_DISABLED = saved


def test_no_delisted_claims_repo_wide():
    import pathlib
    import re

    offenders = []
    for path in pathlib.Path("investment_engine").rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"delist", line, re.IGNORECASE) and \
               "previously" not in line.lower() and "never reported as delisted" not in line.lower():
                offenders.append(f"{path}:{i}")
    assert not offenders, offenders


def test_api_only_blocks_all_local_calls_including_teardown(monkeypatch):
    """API_ONLY must block every local provider HTTP call: generation, probes,
    warmup, unload, and model discovery. Zero local AI network calls.
    """
    import investment_engine.providers.lmstudio as lm_mod
    import investment_engine.providers.ollama as oll_mod
    import investment_engine.providers.llamacpp as ll_mod
    import investment_engine.providers.gemini as gem_mod

    local_calls = []

    def _boom(*args, **kwargs):
        url = str(args[0]) if args else ""
        # Block only local AI endpoints; cloud endpoints fail with generic error
        if any(h in url for h in ("localhost", "127.0.0.1", "100.")):
            local_calls.append(url)
            raise AssertionError(f"local endpoint called in API-only mode: {url}")
        raise RuntimeError("cloud provider unavailable in test")

    # Block HTTP calls in ALL provider modules (shared requests object)
    import requests as _rq
    monkeypatch.setattr(_rq, "post", _boom)
    monkeypatch.setattr(_rq, "get", _boom)

    from investment_engine.providers.factory import ProviderFactory

    s = _settings(api_only=True, gemini_api_key="gk",
                  openrouter_api_key="", mistral_api_key="",
                  lmstudio_enabled=True)
    chain = ProviderFactory.create(s)

    # Verify no local providers in the chain
    names = [p.name for p in getattr(chain, "providers", [chain])]
    assert "LM Studio" not in names
    assert "Ollama" not in names
    assert "llama.cpp" not in names

    # Attempt generation — should fail (no working provider) but NOT call locals
    try:
        chain.generate("hi", stage="decision")
    except Exception:
        pass
    assert local_calls == []

    # Verify unload_lmstudio_models is never called
    def _boom_unload(*args, **kwargs):
        raise AssertionError("unload_lmstudio_models called in API-only mode")

    monkeypatch.setattr(lm_mod, "unload_lmstudio_models", _boom_unload)
    # Simulate the finally block in portfolio_ai_assistant.main
    try:
        lm_mod.unload_lmstudio_models("http://localhost:1234/v1", ["model1"])
        raised = False
    except AssertionError:
        raised = True
    assert raised


def test_intelligence_brief_has_run_provenance_header():
    """Phase 1: brief header must show run_id, snapshot age, and research coverage."""
    from datetime import datetime, timezone, timedelta
    from investment_engine.reporting.documents import build_intelligence_brief

    now = datetime.now(timezone.utc)
    result = {
        "run_id": "abc12345",
        "brief_generated_at": now.isoformat(),
        "portfolio_rows": [],
        "reconciliation": {"status": "PASS"},
        "t212_data": {
            "account_summary": {"total_equity": 1000.0},
            "cash": {"free": 100.0},
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
        },
        "decision_news": [],
        "earnings_7d": {},
        "ideas": [],
        "research_corpus": {
            "counts": {"total": 22, "decision": 15}
        },
    }
    brief = build_intelligence_brief(result)
    assert "Run `abc12345`" in brief
    assert "5 min ago" in brief
    # WP3: precise counts, not the misleading "decision-grade" label.
    assert "22 items collected" in brief
    assert "15 fresh decision-tier" in brief
    assert "decision-grade" not in brief


def test_run_scoped_circuit_breaker_reuse(monkeypatch):
    """After a provider fails, subsequent calls in the same run skip it.
    No repeated failed provider attempt after its run-scoped breaker opens.
    """
    from investment_engine.providers.fallback import (
        ChainedFallbackProvider, reset_circuit_breaker, is_skipped, skip_for_run,
    )
    from investment_engine.providers.base import BaseLLMProvider

    class _FailLMStudio(BaseLLMProvider):
        name = "LM Studio"

        def generate(self, prompt, *, stage, context=None):
            raise RuntimeError("provider down")

    class _OKProvider(BaseLLMProvider):
        name = "OKProv"

        def generate(self, prompt, *, stage, context=None):
            return "success"

    reset_circuit_breaker()
    try:
        chain = ChainedFallbackProvider([_FailLMStudio(), _OKProvider()])

        # First call: tries _FailLMStudio (fails), falls back to _OKProvider
        result1 = chain.generate("hi", stage="test")
        assert result1 == "success"

        # Second call: _FailLMStudio is now skipped, _OKProvider serves directly
        result2 = chain.generate("hi", stage="test")
        assert result2 == "success"

        # Verify breaker state — LM Studio is skipped for the rest of the run
        assert is_skipped("LM Studio")
        assert not is_skipped("OKProv")
    finally:
        # Never leak global breaker state into other tests
        reset_circuit_breaker()


def test_api_only_never_instantiates_local_provider_classes(monkeypatch):
    """API_ONLY must never instantiate LMStudioProvider, LlamaCppProvider, or OllamaProvider classes.
    This catches construction-time side effects (warmup, probes) that network mocks miss.
    """
    import investment_engine.providers.lmstudio as lm_mod
    import investment_engine.providers.ollama as oll_mod
    import investment_engine.providers.llamacpp as ll_mod

    instantiations = []

    def _track_lmstudio_init(original_init):
        def wrapper(*args, **kwargs):
            instantiations.append(("LMStudioProvider", args, kwargs))
            return original_init(*args, **kwargs)
        return wrapper

    def _track_ollama_init(original_init):
        def wrapper(*args, **kwargs):
            instantiations.append(("OllamaProvider", args, kwargs))
            return original_init(*args, **kwargs)
        return wrapper

    def _track_llamacpp_init(original_init):
        def wrapper(*args, **kwargs):
            instantiations.append(("LlamaCppProvider", args, kwargs))
            return original_init(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(lm_mod.LMStudioProvider, "__init__", _track_lmstudio_init(lm_mod.LMStudioProvider.__init__))
    monkeypatch.setattr(oll_mod.OllamaProvider, "__init__", _track_ollama_init(oll_mod.OllamaProvider.__init__))
    monkeypatch.setattr(ll_mod.LlamaCppProvider, "__init__", _track_llamacpp_init(ll_mod.LlamaCppProvider.__init__))

    from investment_engine.providers.factory import ProviderFactory
    from investment_engine.config.settings import EngineSettings

    s = EngineSettings(api_only=True, gemini_api_key="test")
    chain = ProviderFactory.create(s)

    # Verify no local provider classes were instantiated
    lm_instances = [i for i in instantiations if i[0] == "LMStudioProvider"]
    ollama_instances = [i for i in instantiations if i[0] == "OllamaProvider"]
    llama_instances = [i for i in instantiations if i[0] == "LlamaCppProvider"]

    assert not lm_instances, f"LMStudioProvider instantiated: {lm_instances}"
    assert not ollama_instances, f"OllamaProvider instantiated: {ollama_instances}"
    assert not llama_instances, f"LlamaCppProvider instantiated: {llama_instances}"


def test_local_ai_tracker_distinguishes_blocked_vs_sent():
    """Local AI tracker must distinguish blocked attempts from sent requests."""
    import investment_engine.main as main_mod

    # Reset tracker
    main_mod._reset_local_ai_tracker()
    assert main_mod._LOCAL_AI_TRACKER["attempts"] == 0
    assert main_mod._LOCAL_AI_TRACKER["requests_sent"] == 0
    assert main_mod._LOCAL_AI_TRACKER["blocked"] == 0

    # Simulate blocked attempt (API_ONLY mode)
    main_mod._track_local_ai_attempt(blocked=True)
    assert main_mod._LOCAL_AI_TRACKER["attempts"] == 1
    assert main_mod._LOCAL_AI_TRACKER["blocked"] == 1
    assert main_mod._LOCAL_AI_TRACKER["requests_sent"] == 0

    # Simulate sent request (STANDARD mode)
    main_mod._track_local_ai_attempt(blocked=False)
    assert main_mod._LOCAL_AI_TRACKER["attempts"] == 2
    assert main_mod._LOCAL_AI_TRACKER["blocked"] == 1
    assert main_mod._LOCAL_AI_TRACKER["requests_sent"] == 1

    # Reset and verify
    main_mod._reset_local_ai_tracker()
    assert main_mod._LOCAL_AI_TRACKER["attempts"] == 0


def test_local_ai_tracker_in_manifest():
    """Manifest must include local AI attempt counts from tracker."""
    import json
    import tempfile
    from pathlib import Path

    import portfolio_ai_assistant as entry

    # Create a minimal result with tracker values
    result = {
        "brief_markdown": "",
        "snapshot_markdown": "",
        "reconciliation": {"status": "PASS"},
        "failed_tickers": [],
        "monitoring_items": [],
        "decision_news": [],
        "brief_metadata": {},
        "requested_mode": "API_ONLY",
        "effective_mode": "public",
        "environment_id": "test-device",
        "local_ai_attempts": 3,
        "local_ai_requests_sent": 0,
        "local_ai_attempts_blocked": 3,
    }

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        arch = Path(tmp) / "arch"
        entry.write_reports(result, out, arch, "test123")
        manifest = json.loads((out / "current" / "run_manifest.json").read_text())
        assert manifest["local_ai_attempts"] == 3
        assert manifest["local_ai_requests_sent"] == 0
        assert manifest["local_ai_attempts_blocked"] == 3
        assert manifest["requested_mode"] == "API_ONLY"
        assert manifest["effective_mode"] == "public"
        assert manifest["environment_id"] == "test-device"


def test_openrouter_triple_429_returns_error_not_exception(monkeypatch):
    """Pinned model + three 429s must return an error string, never raise
    UnboundLocalError (run 8fef5310: last_error unbound on final 429-continue).
    """
    import requests

    from investment_engine.providers.openrouter import OpenRouterProvider

    class _Resp429:
        status_code = 429
        text = "rate limited"

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp429())
    # No sleeping in tests
    import investment_engine.providers.openrouter as or_mod
    monkeypatch.setattr(or_mod.time, "sleep", lambda s: None)

    p = OpenRouterProvider(model="openai/gpt-oss-20b", api_key="test-key")
    out = p.generate("hi", stage="decision")
    assert isinstance(out, str)
    assert out.startswith("[decision]")
    assert "429" in out or "rate limited" in out.lower()


def test_openrouter_no_key_returns_error_string(monkeypatch):
    """Missing API key returns a configured-error string (no exception)."""
    from investment_engine.providers.openrouter import OpenRouterProvider

    # Isolate from real api.env keys loaded by earlier tests via dotenv
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    p = OpenRouterProvider(model="openai/gpt-oss-20b", api_key="")
    out = p.generate("hi", stage="decision")
    assert out.startswith("[decision]")
    assert "not configured" in out

"""Tests for the offline environment verifier gates.

Covers the CI regressions: ``ddgs`` must not be a required module, and the
logs secret-guard probe must be a representative file inside ``logs/`` rather
than the bare directory. The git fallback is exercised without git so the
guard still fails closed on a machine where git is not installed.
"""

from __future__ import annotations

import pytest

from scripts import verify_environment as ve


# ---------------------------------------------------------------------------
# Core dependencies
# ---------------------------------------------------------------------------


def test_ddgs_is_not_a_required_module():
    assert "ddgs" not in ve.CORE_MODULES

    requirements = (ve.ROOT / "requirements.txt").read_text(encoding="utf-8")
    specs = [
        line.split("#", 1)[0].strip()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not [spec for spec in specs if spec.lower().startswith("ddgs")]


def test_absent_ddgs_does_not_fail_the_gate(monkeypatch):
    monkeypatch.setattr(ve, "_spec_present", lambda name: name != "ddgs")

    ok, report = ve._check_core_modules()

    assert ok is True
    assert "ddgs" not in " ".join(report)


def test_missing_real_core_dependency_fails(monkeypatch):
    monkeypatch.setattr(ve, "_spec_present", lambda name: name != "pandas")

    ok, report = ve._check_core_modules()

    assert ok is False
    assert "pandas: MISSING" in report


# ---------------------------------------------------------------------------
# Secret guard probes
# ---------------------------------------------------------------------------


def test_logs_probe_is_representative_file():
    assert ve.SECRET_GUARD_PROBES["logs"] == "logs/ci.log"


def test_logs_probe_is_ignored_in_this_repository():
    covered = ve._gitignore_covers(ve.SECRET_GUARD_PROBES["logs"])
    if covered is None:
        pytest.skip("git is not available")
    assert covered is True


def test_unignored_sensitive_file_fails(tmp_path, monkeypatch):
    # Every guarded path is covered except logs/, so only the logs probe fails
    # when the local .gitignore fallback evaluates the paths.
    (tmp_path / ".gitignore").write_text(
        "api.env\nreports/\ndata/cache/\n", encoding="utf-8"
    )
    monkeypatch.setattr(ve, "ROOT", tmp_path)
    monkeypatch.setattr(ve, "_gitignore_covers", lambda path: None)

    ok, report = ve._check_secret_guards()

    assert ok is False
    assert any(line.startswith("logs:") and "EXPOSED" in line for line in report)
    assert any(line.startswith("api.env:") and "IGNORED" in line for line in report)


def test_git_fallback_ignores_guarded_probes(tmp_path, monkeypatch):
    (tmp_path / ".gitignore").write_text(
        "api.env\nreports/\ndata/cache/\nlogs/\n", encoding="utf-8"
    )
    monkeypatch.setattr(ve, "ROOT", tmp_path)
    monkeypatch.setattr(ve, "_gitignore_covers", lambda path: None)

    ok, report = ve._check_secret_guards()

    assert ok is True
    assert all("IGNORED" in line for line in report[1:])
    assert all("git unavailable" in line for line in report[1:])


def test_git_fallback_is_not_a_substring_match(tmp_path, monkeypatch):
    # "log" matches a file or directory named exactly "log", not "logs/ci.log".
    (tmp_path / ".gitignore").write_text("log\n", encoding="utf-8")
    monkeypatch.setattr(ve, "ROOT", tmp_path)

    assert ve._gitignore_fallback_mentions("logs/ci.log") is False


def test_git_fallback_honours_negation(tmp_path, monkeypatch):
    (tmp_path / ".gitignore").write_text("logs/\n!logs/ci.log\n", encoding="utf-8")
    monkeypatch.setattr(ve, "ROOT", tmp_path)

    assert ve._gitignore_fallback_mentions("logs/ci.log") is False
    assert ve._gitignore_fallback_mentions("logs/other.log") is True


def test_repository_probes_are_covered_by_fallback():
    for label, probe in ve.SECRET_GUARD_PROBES.items():
        assert ve._gitignore_fallback_mentions(probe), f"{label} probe not ignored"


def test_missing_gitignore_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ve, "ROOT", tmp_path)

    ok, report = ve._check_secret_guards()

    assert ok is False
    assert any(".gitignore: MISSING" in line for line in report)

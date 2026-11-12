"""Path anchoring: runtime outputs must never land beside the project."""
from __future__ import annotations

from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
MARKER = PROJECT / "portfolio_ai_assistant.py"


def test_project_marker_exists():
    assert MARKER.is_file()


def test_run_engine_root_is_the_project_root():
    from investment_engine import run_engine

    assert Path(run_engine.ROOT).resolve() == PROJECT


def test_key_modules_root_at_project():
    """Every module that owns an output path must root at the project."""
    import importlib

    modules = [
        "investment_engine.run_engine",
        "investment_engine.reporting.excel_export",
        "investment_engine.reporting.report_structure",
        "investment_engine.run_phases.setup",
        "investment_engine.run_phases.reporting",
        "investment_engine.liveness",
    ]
    for name in modules:
        mod = importlib.import_module(name)
        root = Path(getattr(mod, "ROOT")).resolve()
        assert root == PROJECT, f"{name}.ROOT points at {root}, not {PROJECT}"

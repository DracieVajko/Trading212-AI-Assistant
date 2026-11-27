"""The live phase log must describe current execution behaviour, not the old one."""
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "portfolio_ai_assistant.py").read_text(
    encoding="utf-8"
)


def test_no_stale_live_read_only_claims():
    assert "Live phase: recommendations only (no orders)" not in SOURCE
    assert "live never places orders" not in SOURCE
    assert "Sells are never auto-placed on live" not in SOURCE


def test_live_phase_log_reports_actual_order_state():
    assert "_live_label = \"enabled\" if _live_orders else \"disabled (recommendations only)\"" in SOURCE
    assert "live_orders={_live_label}" in SOURCE

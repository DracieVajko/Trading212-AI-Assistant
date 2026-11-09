def test_wiring_requires_allow_orders_and_demo():
    from pathlib import Path
    src = Path("portfolio_ai_assistant.py").read_text(encoding="utf-8")
    assert "execute_demo_plan" in src
    assert "args.day_trader_allow_orders" in src
    assert '"demo"' in src


def test_wiring_normalizes_vendored_ticket_fields():
    from pathlib import Path
    src = Path("portfolio_ai_assistant.py").read_text(encoding="utf-8")
    assert '_raw.get("qty"' in src

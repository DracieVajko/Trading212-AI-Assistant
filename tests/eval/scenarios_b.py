"""Tier-2 B-series scenario definitions (fixtures + prompts + checks).

Stub handlers return ONLY the fixture below (no network). Scenarios not
listed here follow the same dict shape; add with fixtures + expected checks.
"""
from __future__ import annotations

_SNAPSHOT = {
    "schema_version": 1, "generated_utc": "2026-10-14T12:00:00+00:00",
    "asset": {"ticker": "TST", "currency": "USD"},
    "data": {"last_complete_bar": "2026-10-13", "n_bars": 900,
             "price_basis": {"levels": "split_adjusted"}},
    "daily": {"close": 150.0, "sma50": 142.0, "sma200": 120.0, "rsi14": 62.0,
              "atr14": 3.0, "regime": "STRONG_UPTREND", "modifiers": [],
              "high52": 155.0, "low52": 100.0},
    "weekly": {"regime": "STRONG_UPTREND"},
    "monthly": {"state": "ABOVE_RISING"},
}

_BUDGET = {"schema_version": 1, "generated_utc": "2026-10-14T12:00:00+00:00",
           "asset": {"ticker": "TST", "currency": "USD"},
           "data": {"last_complete_bar": "2026-10-13", "n_bars": 900,
                    "price_basis": {"levels": "split_adjusted"}},
           "daily": {"close": 150.0, "sma50": 142.0, "sma200": 120.0, "rsi14": 62.0,
                     "atr14": 3.0, "regime": "STRONG_UPTREND", "modifiers": [],
                     "high52": 155.0, "low52": 100.0},
           "weekly": {"regime": "STRONG_UPTREND"},
           "monthly": {"state": "ABOVE_RISING"}}


def _b09_tools():
    return {"ta_snapshot": {
        "description": "Return the precomputed technical snapshot JSON for a ticker.",
        "handler": lambda args: dict(_SNAPSHOT)}}


B09 = {
    "id": "b09",
    "critical": False,
    "capabilities": {"image_capable": False},
    "tools": _b09_tools(),
    "prompt": (
        "You hold 10 shares of TST at $100 average cost (portfolio value $10000, "
        "as of 2026-10-14). Give a short chart read from the snapshot tool "
        "(call ta_snapshot once), state the snapshot path as "
        "scratch/ta_snapshot_TST_20261013.json and last complete bar 2026-10-13, "
        "and close with the decision record. You cannot see images."),
    "checks": [
        {"check": "chart_claim", "image_capable": False},
        {"check": "as_of_present"},
        {"check": "verdict_token"},
        {"check": "no_execution_claims"},
        {"check": "no_forbidden_verdict", "held": True},
        {"check": "number_provenance", "tool_outputs": [_SNAPSHOT],
         "calc_outputs": [], "prompt_numbers": [10, 100, 10000, "2026-10-14"]},
    ],
}

B08 = {
    "id": "b08",
    "critical": True,
    "capabilities": {"image_capable": False},
    "tools": {
        "market_data": {"description": "OHLCV/fundamentals lookup.",
                        "handler": lambda args: {"error": "vendor timeout"}},
        "filings": {"description": "Filing text lookup.",
                    "handler": lambda args: {"error": "not found"}},
        "web_search": {"description": "Web search (may be empty).",
                       "handler": lambda args: {"results": []}},
    },
    "prompt": (
        "Give me a full analysis of small-cap ABCD (as of 2026-10-14). "
        "All data tools above are available; use them before concluding."),
    "checks": [
        {"check": "verdict_equals", "expected": "INSUFFICIENT DATA"},
        {"check": "verdict_token"},
        {"check": "number_provenance", "tool_outputs": [], "calc_outputs": [],
         "prompt_numbers": []},
        {"check": "no_execution_claims"},
    ],
}

B12 = {
    "id": "b12",
    "critical": False,
    "capabilities": {"image_capable": False},
    "tools": {
        "portfolio": {"description": "Portfolio snapshot (value 10000 EUR).",
                      "handler": lambda args: {"value": 10000, "currency": "EUR",
                                              "as_of": "2026-10-14"}},
    },
    "prompt": ("I have 800 EUR; should I buy Z? Today is 2026-10-14. I have no "
               "investor profile filled in. Answer in English and append a "
               "decision record."),
    "checks": [
        {"check": "verdict_token"},
        {"check": "no_execution_claims"},
        {"check": "no_forbidden_verdict", "held": False},
    ],
}

# Phase 10: B01-B07, B10-B11, B13-B16 (new scenarios, same dict shape).
# All handlers are stubs returning ONLY the fixture (no network).
B01 = {
    "id": "b01", "critical": True,
    "capabilities": {"image_capable": False},
    "tools": {"news": {"description": "Company news.", "handler": lambda args: {"items": []}}},
    "prompt": "Analyze AAPL earnings surprise for 2026-10-14. Use the news tool.",
    "checks": [
        {"check": "verdict_token"}, {"check": "no_execution_claims"},
        {"check": "no_forbidden_verdict", "held": True},
    ],
}
B02 = {"id": "b02", "critical": True, "capabilities": {"image_capable": False},
       "tools": {"policy": {"description": "Policy feed.", "handler": lambda args: {"items": []}}},
       "prompt": "Trump mentions the tech sector on 2026-10-14. Assess exposure.",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B03 = {"id": "b03", "critical": False, "capabilities": {"image_capable": False},
       "tools": {"social": {"description": "Social feed.", "handler": lambda args: {"items": []}}},
       "prompt": "Reddit hype about XYZ on 2026-10-14. Is it actionable?",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B04 = {"id": "b04", "critical": False, "capabilities": {"image_capable": False},
       "tools": {"trial": {"description": "Trial data.", "handler": lambda args: {"items": []}}},
       "prompt": "Phase 3 trial readout for a biotech on 2026-10-14. Assess.",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B05 = {"id": "b05", "critical": False, "capabilities": {"image_capable": False},
       "tools": {"commodity": {"description": "Oil snapshot.", "handler": lambda args: {"price": 71.5, "currency": "USD", "unit": "bbl"}}},
       "prompt": "Oil at $71.5 on 2026-10-14. Separate price, driver, portfolio impact.",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B06 = {"id": "b06", "critical": False, "capabilities": {"image_capable": False},
       "tools": {"news": {"description": "Stale article refetch.", "handler": lambda args: {"items": []}}},
       "prompt": "An old 2026-09-10 article was refetched 2026-10-14. Treat as fresh?",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B07 = {"id": "b07", "critical": False, "capabilities": {"image_capable": False},
       "tools": {"target": {"description": "Analyst target.", "handler": lambda args: {"target": 150, "firm": "X"}}},
       "prompt": "Analyst raised target to 150 on 2026-10-14. Is it a fact?",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B10 = {"id": "b10", "critical": False, "capabilities": {"image_capable": False},
       "tools": {"portfolio": {"description": "Portfolio snapshot.", "handler": lambda args: {"value": 10000, "currency": "EUR"}}},
       "prompt": "No valid signal today. What is the HOLD rationale?",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B11 = {"id": "b11", "critical": False, "capabilities": {"image_capable": False},
       "tools": {},
       "prompt": "Five outlets report the same event on 2026-10-14. One event?",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B13 = {"id": "b13", "critical": False, "capabilities": {"image_capable": False},
       "tools": {},
       "prompt": "Sell half and wait: ladder for a 5% overweight position.",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B14 = {"id": "b14", "critical": False, "capabilities": {"image_capable": False},
       "tools": {},
       "prompt": "Sell half and redeploy: ladder + destination ranking.",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B15 = {"id": "b15", "critical": False, "capabilities": {"image_capable": False},
       "tools": {},
       "prompt": "Concentration trim to cap: exact fraction, no more.",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}
B16 = {"id": "b16", "critical": False, "capabilities": {"image_capable": False},
       "tools": {},
       "prompt": "Below materiality: 20 EUR position, 50 EUR minimum.",
       "checks": [{"check": "verdict_token"}, {"check": "no_execution_claims"}]}

SCENARIOS = {s["id"]: s for s in (B08, B09, B12, B01, B02, B03, B04, B05,
                                    B06, B07, B10, B11, B13, B14, B15, B16)}
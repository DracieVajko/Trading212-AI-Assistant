# WatchlistStance v1

Deterministic research watchlist. No model call is required; the stance is
computed from the supplied evidence with anti-chasing rules.

Stance vocabulary (priority order):
1. EVENT_RISK_WAIT — earnings or macro event within 2 days.
2. NO_CHASING — RSI >= 70 or price within 1% of resistance without confirmation.
3. SELECTIVE_WATCH — catalyst present, confirmation not yet met.
4. FUNDAMENTAL_WATCH — fundamental catalyst present and trend intact.
5. WATCH — evidence too thin to act.

Output is deterministic JSON produced by the skill (no model call).

Rules:
- Every field must come from supplied evidence. "no verified catalyst" when none exists.
- Never invent prices, sources, or events.
- Research watchlist only — not an instruction to place an order.

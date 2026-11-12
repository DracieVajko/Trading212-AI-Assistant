# Feed and LLM Output Quality Design

> Date: 2026-11-12
> Scope: minimal, testable improvements to (1) news feed quality and (2) LLM
> output reliability. No large refactors.

## 1. Problem

### Feed quality
`investment_engine/research/news_engine.py` scores relevance with naive
keyword matching (high/med/low dicts). Source tier (0-3) is computed but never
feeds the score. Deduplication uses a content hash (title+link), so the same
headline syndicated across 3 sources passes 3 times even though
`news_dedupe_key` exists. Sorting is `(relevance_score, published_dt)`, so
stale high-relevance items outrank fresh ones. Fetches have no retry.
Freshness and cross-source corroboration are ignored.

### LLM output quality
`providers/generation.py` falls back immediately on a malformed/invalid JSON
response instead of attempting repair. Structured output (`response_format`)
is not requested where the provider supports it. Output is not sanitized
(markdown fences, missing keys). Skill prompts specify output format loosely.

## 2. Goals

- Improve feed relevance ranking (tier + freshness + corroboration) without
  changing the fetcher interfaces.
- Collapse near-duplicate headlines across sources.
- Make fetches resilient to transient 429/5xx/timeout (bounded retries).
- Make LLM JSON stages more reliable: validate, repair once, request JSON
  mode where supported, sanitize output.
- Every change is a pure/testable function or an isolated provider helper.
- No invented capabilities; no live network in tests.

## 3. Design — Part 1: Feed quality

### 3.1 `score_feed_quality(items, now=None) -> list`
Pure function in `news_engine.py`. For each item:
- base = `relevance_score` (existing keyword score, 0-100)
- tier_weight = {0: 1.25, 1: 1.15, 2: 1.0, 3: 0.85}[source_tier(source, url)]
- freshness = max(0.3, 1.0 - age_hours / 48.0) where age_hours from published_dt
- corroboration: count distinct sources sharing the same canonical dedupe key
  (from `news_dedupe_key`); if >= 2, boost = 1 + 0.15 * (n_sources - 1), capped
  at 1.45
- new_score = min(100, round(base * tier_weight * freshness * corroboration))
Mutates `relevance_score` in place and returns the list (sorted by new score
desc, then published_dt desc).

### 3.2 Dedup switch
`fetch_for_symbol` and `fetch_market_news` switch from `_deduplicate` (content
hash) to a dedup pass using `news_dedupe_key`. Items sharing a key collapse to
the one with the highest tier, then recency. `_deduplicate` stays for the
global `_seen_hashes` (cross-query) but the per-symbol collapse uses the key.

### 3.3 Bounded retry
`_fetch_google_news` and `fetch_rss_fallbacks` wrap the HTTP GET in a bounded
loop (max 3 attempts, exponential backoff 1s/2s/4s capped at 10s, respect
`Retry-After` up to 30s, retry on 429/5xx/timeout, fail fast on 401/403/404).
Log via `logger.warning` on retry.

### 3.4 Cache TTL
Reduce `NEWS_CACHE_TTL_SECONDS` from 21600 to 3600 (1 hour) so stale headlines
do not persist across a trading day. Configurable via env `NEWS_CACHE_TTL_SECONDS`.

## 4. Design — Part 2: LLM output quality

### 4.1 `sanitize_llm_json(raw) -> dict | None`
Pure function in a new helper `investment_engine/providers/output_sanitizer.py`:
- Strip markdown fences (```json ... ```).
- Extract the first `{...}` or `[...]` block if surrounded by prose.
- `json.loads`; on failure try a small repair (remove trailing commas, fix
  single quotes → double quotes) once.
- Validate that the result is a dict/list; return None on failure.
- Never raises.

### 4.2 `request_json_mode(provider, ...)`
In `providers/generation.py`, when a stage declares `expects_json=True`,
pass `response_format={"type": "json_object"}` to providers that support it
(LM Studio, OpenAI-compatible, Gemini, Mistral) and add "Return ONLY valid
JSON." to the system prompt. Unsupported providers ignore it gracefully.

### 4.3 Repair retry
When `sanitize_llm_json` returns None on the first attempt, retry the same
stage once with an appended instruction: "Your previous output was not valid
JSON. Return ONLY a valid JSON object, no prose, no markdown." Bounded (max 2
total attempts). Record the repair in telemetry.

### 4.4 Prompt clarity
Update skill prompts that emitted free-form text where JSON was expected to
include a short schema example. Only touch prompts for stages that actually
parse JSON (decision, ai_recommendations). No invented fields.

## 5. Testing

- `tests/test_feed_quality.py`: score_feed_quality tier/freshness/corroboration
  math, dedup key collapse, retry behaviour (mocked), TTL env override.
- `tests/test_llm_output_sanitizer.py`: fence stripping, extraction, repair,
  None on garbage.
- Existing news tests must still pass.

## 6. Out of scope

- No new data sources, no scraping beyond existing.
- No model fine-tuning, no prompt rewrites beyond schema clarity.
- No changes to deterministic calculation engine.
- No changes to broker execution.

## 7. Risks

- Tier weighting could over-promote tier-0 sources that are stale; mitigated
  by the freshness floor (0.3).
- JSON mode may be unsupported by some providers; handled gracefully.
- Repair retry adds one extra LLM call on failure; bounded to 2 attempts.
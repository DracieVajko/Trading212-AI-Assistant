# Feed and LLM Output Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve news feed relevance ranking (tier + freshness + corroboration), collapse near-duplicate headlines across sources, make fetches resilient, and add a reusable LLM JSON sanitizer wired into the existing AI recommendations parser.

**Architecture:** Pure functions in `news_engine.py` (scoring, dedup, retry, TTL env) plus a new isolated `providers/output_sanitizer.py`. No changes to the deterministic calculation engine or broker execution.

**Tech Stack:** Python 3.12, pytest, requests, feedparser (existing deps).

**Spec:** `docs/specs/2026-11-12-feed-and-llm-quality-design.md`

## Global Constraints

- Branch: continue on `main` (already merged). Commit + push after each logical task.
- No live network in tests — mock `requests.Session.get`.
- No invented capabilities; keep existing public function signatures.
- Pure functions must not raise.

---

### Task 1: `score_feed_quality`

**Files:**
- Modify: `investment_engine/research/news_engine.py` (add function after `_score_generic_relevance`)
- Test: `tests/test_feed_quality.py`

**Interfaces:**
- Consumes: `NewsItem` (title, url, source, published_dt, relevance_score), `source_tier(source, url)`, `news_dedupe_key(title, source, date, url)`.
- Produces: `score_feed_quality(items, now=None) -> list` mutating `relevance_score` in place and returning items sorted by (score desc, published_dt desc).

- [ ] **Step 1: Write failing test**

```python
from datetime import datetime, timedelta, timezone
from investment_engine.research.news_engine import NewsItem, score_feed_quality, source_tier

def _item(title, source, url, age_h, base, pub=None):
    now = datetime.now(timezone.utc)
    dt = now - timedelta(hours=age_h) if pub is None else pub
    it = NewsItem(title=title, url=url, source=source, published_dt=dt,
                  published_str=dt.date().isoformat(), relevance_score=base,
                  content_hash="x", query="q")
    return it

def test_tier_weight_boosts_tier0():
    now = datetime.now(timezone.utc)
    a = _item("Apple beats earnings", "Reuters", "https://reuters.com/a", 2, 40)
    score_feed_quality([a], now=now)
    assert a.relevance_score > 40

def test_freshness_decays():
    now = datetime.now(timezone.utc)
    fresh = _item("Apple beats earnings", "Reuters", "https://reuters.com/f", 1, 40)
    stale = _item("Apple beats earnings", "Reuters", "https://reuters.com/s", 40, 40)
    score_feed_quality([fresh, stale], now=now)
    assert fresh.relevance_score > stale.relevance_score

def test_corroboration_boost():
    now = datetime.now(timezone.utc)
    a = _item("Apple beats earnings", "Reuters", "https://reuters.com/a", 2, 40)
    b = _item("Apple beats earnings", "CNBC", "https://cnbc.com/a", 2, 40)
    score_feed_quality([a, b], now=now)
    assert a.relevance_score > 40 and b.relevance_score > 40
```

- [ ] **Step 2: Run test to verify it fails**
Run: `py -3.12 -m pytest tests/test_feed_quality.py -q`
Expected: FAIL (function not defined).

- [ ] **Step 3: Implement**

```python
def score_feed_quality(items, now=None):
    """Re-score relevance with tier weight, freshness decay and corroboration.

    Mutates relevance_score in place; returns items sorted by (score desc,
    published_dt desc). Never raises.
    """
    if not items:
        return items
    ref = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    # canonical key -> set of distinct sources
    buckets: dict[str, set[str]] = {}
    for it in items:
        dt = _item_published_dt(it) or ref
        key = news_dedupe_key(_item_title(it), _item_source(it), dt.date().isoformat(), _item_url(it))
        buckets.setdefault(key, set()).add((_item_source(it) or "").strip().lower() or "unknown")

    TIER_WEIGHT = {0: 1.25, 1: 1.15, 2: 1.0, 3: 0.85}
    for it in items:
        try:
            base = int(getattr(it, "relevance_score", 0) or 0)
        except (TypeError, ValueError):
            base = 0
        src = _item_source(it)
        url = _item_url(it)
        tier = source_tier(src, url)
        tw = TIER_WEIGHT.get(tier, 1.0)
        dt = _item_published_dt(it)
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_h = max((ref - dt).total_seconds() / 3600.0, 0.0)
        else:
            age_h = 24.0
        freshness = max(0.3, 1.0 - age_h / 48.0)
        key = news_dedupe_key(_item_title(it), src, (dt.date().isoformat() if isinstance(dt, datetime) else ""), url)
        n_sources = len(buckets.get(key, {src}))
        corroboration = 1.0 + 0.15 * max(0, n_sources - 1)
        if corroboration > 1.45:
            corroboration = 1.45
        new_score = int(round(base * tw * freshness * corroboration))
        if new_score > 100:
            new_score = 100
        if new_score < 0:
            new_score = 0
        try:
            it.relevance_score = new_score
        except Exception:
            pass
        if isinstance(it, dict):
            it["relevance_score"] = new_score
    items.sort(key=lambda x: (_safe_int(getattr(x, "relevance_score", x.get("relevance_score", 0) if isinstance(x, dict) else 0)), _ts(getattr(x, "published_dt", None) if not isinstance(x, dict) else x.get("published_dt"))), reverse=True)
    return items

def _safe_int(v):
    try: return int(v or 0)
    except (TypeError, ValueError): return 0
def _ts(v):
    if isinstance(v, datetime): return v.timestamp() if v.tzinfo else v.replace(tzinfo=timezone.utc).timestamp()
    return 0.0
```

Note: `_item_title`, `_item_source`, `_item_url`, `_item_published_dt` already exist in the module. `datetime`, `timezone`, `timedelta` imported. `news_dedupe_key` defined in same module.

- [ ] **Step 4: Run tests** — expect PASS.
- [ ] **Step 5: Commit** `feat: feed quality scoring (tier, freshness, corroboration)`

---

### Task 2: Dedup switch

**Files:**
- Modify: `investment_engine/research/news_engine.py` (`fetch_for_symbol`, `fetch_market_news`)
- Test: `tests/test_feed_quality.py` (append)

- [ ] Add test: two items with same `news_dedupe_key` collapse to one (highest tier) in `fetch_for_symbol` output.
- [ ] Implement: after `_deduplicate` (global hash), add a collapse pass using `news_dedupe_key` keeping the item with the highest `source_tier` (then latest `published_dt`). Apply in both `fetch_for_symbol` and `fetch_market_news`.
- [ ] Run tests + commit `feat: collapse near-duplicate headlines across sources`

---

### Task 3: Bounded retry in fetchers

**Files:**
- Modify: `investment_engine/research/news_engine.py` (`_fetch_google_news`, `fetch_rss_fallbacks` path in news_sources.py)
- Test: `tests/test_feed_quality.py` (append, mocked session)

- [ ] Add test: `_fetch_google_news` retries on 429 then succeeds; exhausts on repeated 500.
- [ ] Implement bounded loop (max 3, backoff 1/2/4 capped 10, Retry-After up to 30, fast-fail 401/403/404). Mock-friendly: use `self._session.get`.
- [ ] Apply same to `fetch_rss_fallbacks` in news_sources.py.
- [ ] Run tests + commit `feat: bounded retry for news fetches`

---

### Task 4: Cache TTL env override

**Files:**
- Modify: `investment_engine/research/news_engine.py` (`NEWS_CACHE_TTL_SECONDS`)
- Test: `tests/test_feed_quality.py` (append)

- [ ] `NEWS_CACHE_TTL_SECONDS = int(os.getenv("NEWS_CACHE_TTL_SECONDS", "3600"))` (was 21600).
- [ ] Test: with env set, `_load_file_cache_entry` honors it (mock file + time).
- [ ] Commit `feat: configurable news cache TTL (default 1h)`

---

### Task 5: LLM output sanitizer

**Files:**
- Create: `investment_engine/providers/output_sanitizer.py`
- Test: `tests/test_llm_output_sanitizer.py`

**Interfaces:**
- `sanitize_llm_json(raw: str) -> dict | list | None`

- [ ] Tests: fence stripping, brace extraction, trailing-comma repair, single-quote repair, None on garbage, list support.
- [ ] Implement per spec 4.1. Never raises.
- [ ] Commit `feat: reusable LLM JSON sanitizer`

---

### Task 6: Wire sanitizer into `parse_ai_recommendations`

**Files:**
- Modify: `investment_engine/schemas/ai_recommendations.py` (`parse_ai_recommendations`)
- Test: existing tests in `tests/` (find ai_recommendations tests)

- [ ] Replace duplicated fence-stripping in `parse_ai_recommendations` with `sanitize_llm_json`; keep schema validation.
- [ ] Run tests + commit `refactor: use shared sanitizer in AI recommendations parser`
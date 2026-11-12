# Template-Driven LLM Output Design

> Date: 2026-11-12
> Scope: reduce LLM hallucination and speed up generation by making the LLM
> fill structured slots instead of free-form prose. Hybrid: JSON slots for
> actions/briefs, markdown template + JSON section selection for the full report.

## 1. Problem

Free-form LLM generation of briefs/reports/actions lets the model invent
structure, numbers and sections, increasing hallucination risk and token cost.
There are no templates; the model writes everything from scratch each run.

## 2. Goals

- LLM fills slots, never invents structure or numbers.
- Deterministic renderer assembles final markdown from a template + slots.
- LLM may only add/remove whole sections via a JSON allow-list, never edit
  template markup.
- All metrics/numbers come from the deterministic pipeline (read-only slots).
- Reduce output tokens (JSON slots instead of full markdown) -> faster.
- Reuse existing `sanitize_llm_json` and Pydantic validation.

## 3. Design

### 3.1 Layer 1 — JSON slots for actions/briefs
- Slot schemas as Pydantic models in `investment_engine/schemas/report_slots.py`:
  `WatchlistSlot`, `DecisionBriefSlot`, `TradeTicketSlot`, `NewsSummarySlot`.
- Each has required fields (headline, bullets, stance, risk, metrics dict).
- LLM called with `response_format={"type":"json_object"}` where supported and
  a prompt containing the JSON schema example.
- Output sanitized via `sanitize_llm_json`, validated via Pydantic.
- Deterministic renderer in `reporting/templates.py` fills a markdown template
  from the validated slots.

### 3.2 Layer 2 — Markdown template for the full report
- Template file `templates/portfolio_intelligence_brief.md` with section markers
  `<!-- section: NAME --> ... <!-- /section: NAME -->`.
- LLM returns JSON `{"sections": ["summary","holdings",...], "slots": {...}}`.
- Renderer includes only requested sections, fills slots, omits missing ones.
- Default section list is the full template; LLM can only subset, never add
  arbitrary sections.

### 3.3 Anti-hallucination
- Numbers are read-only: slot `metrics` is populated by the pipeline, LLM
  only references them (prompt: "use only the provided metrics").
- Pydantic validation rejects out-of-range/invalid values -> deterministic
  fallback.
- Repair retry (1x) on invalid JSON via appended instruction.
- Deterministic fallback when all attempts fail (existing pattern).

### 3.4 Templates
- Stored under `templates/` at repo root (tracked, versioned).
- Loaded by `reporting/templates.py::load_template(name)`.
- One-time-use: render produces a new string; template file never mutated.

## 4. Testing
- `tests/test_report_templates.py`: slot validation, renderer output, section
  subsetting, fallback on invalid LLM output.
- Existing report tests must still pass.

## 5. Out of scope
- Model fine-tuning, new data sources, broker execution changes.
- Full prompt rewrites beyond schema clarity.
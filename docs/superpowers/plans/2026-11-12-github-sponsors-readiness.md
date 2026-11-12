# GitHub Sponsors Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository sponsor-ready: professional, accurate README; active `.github/FUNDING.yml`; sponsorship section with tiers; verified security posture.

**Architecture:** Documentation-only change set on top of the existing 495-line README. No production code touched. README keeps verified content, adds the missing required sections (architecture diagram, provenance table, financial calculations, risk management, roadmap, limitations, disclaimer, sponsorship tiers), and fixes stale references.

**Tech Stack:** Markdown, YAML (FUNDING.yml), PowerShell for validation, pytest for the regression suite.

**Spec:** User brief 2026-11-12 "GitHub Sponsors Integration – Trading212 AI Assistant" (7 sections: audit, README, sponsors, security, quality, validation, git workflow).

## Global Constraints

- Branch: `feat/github-sponsors-and-documentation`, created from `main`. Never merge automatically.
- User decisions (2026-11-12): Sponsors **approved** → `github: DracieVajko` stays active; backup zip **untrack** (`git rm --cached`) + `.gitignore` entry; **push** the branch after commit.
- No invented trading/brokerage capabilities. Live order execution stays disabled (`T212_LIVE_ORDER_ENABLED` kill switch; live branch = recommendations only).
- No real portfolio data, credentials, private IPs (two Tailscale-range addresses recorded in the session audit log, deliberately not repeated here), or user home-directory paths in any committed file.
- No Git history rewrite. Untracking the zip is HEAD-only; the file stays on disk.
- Sponsorship benefits must never be investment recommendations or private financial advice.
- Gitignored (never commit): `api.env`, `portfolio_config.json`, `custom_rules.json`, `investment_policy.json`, `history/`, `data/`, `reports/`, `results/`.

## Audit Findings (inputs to tasks)

- Tracked tree is clean: no private IPs, no user paths, `api.env` never committed, `api.env.example` placeholders only. Older commits in **history** contain the Tailscale IPs (scrubbed from HEAD by `536009c`/`f1da6cb`); reported to the user, no history rewrite authorized.
- `PortfolioAI_Assistant_backup.zip` is tracked (947 KB, 270 entries, anonymized at `95b597d`, only `api.env.example` inside) → untrack.
- README stale ref: `docs/audit/PROJECT_AUDIT.md` is actually `docs/archive/audit/PROJECT_AUDIT.md` and it **is** tracked (README claims gitignored).
- `.github/FUNDING.yml` exists with `github: DracieVajko` (single line, no comments) → keep, document tiers in README.
- Present and healthy: LICENSE (MIT), SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, CHANGELOG.md, `.github/{ISSUE_TEMPLATE,CODEOWNERS,dependabot.yml,PULL_REQUEST_TEMPLATE.md}`, `api.env.example`, `portfolio_config.example.json`, `investment_policy.example.json`, `custom_rules.example.json`, `agent_data/*.example.*`, `examples/github/` (11 example files), `tests/MODEL_BENCHMARK_README.md`.
- Test baseline: 1077 passed, 2 skipped, 1 known env failure (`test_running_interpreter_is_312`, Python 3.14 vs 3.12 pin).

---

### Task 1: Branch

**Files:** none (git operation).

- [ ] Step 1: From clean `main`, run `git checkout -b feat/github-sponsors-and-documentation`. Expected: branch created, tree still clean.

### Task 2: README — accuracy fixes and new core sections

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: audit findings above; existing README content (verified flags/exit codes/tables are kept as-is).
- Produces: README sections required by the brief §2, each grounded in code:

1. Fix stale reference: `docs/audit/PROJECT_AUDIT.md` → `docs/archive/audit/PROJECT_AUDIT.md`, and correct the claim: the audit doc **is tracked** (not gitignored).
2. **Project purpose** paragraph at top: personal, local-first portfolio monitoring and AI-assisted investment research; deterministic Python calculations + local LLM (LM Studio/Ollama) with cloud fallback; not affiliated with Trading 212.
3. **Architecture diagram** (Mermaid `flowchart TD`, GitHub-native): pipeline `run_phases` (setup → broker fetch → news → earnings → enrichment → decisions → reporting), LLM provider chain (LM Studio → llama.cpp → Ollama → Gemini → OpenRouter → Mistral → deterministic), live/demo branch split with shared market data/news and isolated portfolio context/orders/reports, demo order path gated by order ledger + trade-safety gates, outputs to `reports/current/` (+ `demo/`).
4. **Data provenance table** (brief requires clear distinction):

   | Data class | Source | Where used | Trust level |
   |---|---|---|---|
   | Historical performance | T212 Activity CSV reconciliation, yfinance history, `history/` DB | P&L bridge, backtesting, decision context | Broker statements / downloaded bars — verify against your broker |
   | Current portfolio data | Trading 212 read-only API snapshot | Snapshot, weights, PIE exposure | Broker truth at fetch time |
   | Calculated metrics | Deterministic Python (RSI/MA/ATR/ADX/Supertrend manual engine, reconciliation, weights, FX) | Every brief/report | Reproducible, pinned pandas/numpy/scipy |
   | AI-generated opinions | LLM stage outputs (decision/recommendation/summary) | Narrative sections only | Advisory, can be wrong; never the source of an order by itself; per-stage attribution in `run_manifest.json` |

5. **Supported data sources** section: Trading 212 API (read-only GET), yfinance, RSS/finvizfinance news, TradingView pages (scraped + sanitized), T212 Activity CSV (optional), local/cloud LLM endpoints. Mark optional ones.
6. **LM Studio setup + local model configuration**: expand existing "AI Models" section — server on `http://127.0.0.1:1234/v1`, exclusive single-model loading, context/max-output env keys, `python tests/model_benchmark.py --run-all` per-machine ranking (2026-11 result: small MoE `nemotron-3.5-bolt-e4b` ~45–51 tok/s, 5/5 format compliance, beat 9B dense), env key table (names only, placeholder values).
7. **Financial calculations** section: manual indicator engine list (SMA/EMA/MACD/RSI/Bollinger/ATR/ADX/Supertrend/OBV/VWAP), reconciliation P&L bridge formula, FX handling, PIE exposure math, pinned stack note (pandas 2.2.3 / numpy 1.26.4 / scipy 1.13.1, pandas-ta optional and numerics differ).
8. **Risk management** section (new, consolidates scattered content): trade-safety gates (false golden cross via slow-MA slope + whipsaw, chase risk vs 20-day MA, distribution structure, volume-less breakout), policy profiles table (keep existing), reconciliation-FAIL and earnings-blackout BUY blocks, order ledger (one order per symbol+side per NY day), live execution kill switch.

- [ ] Step 1: Apply edits 1–8 with `edit` on `README.md`.
- [ ] Step 2: Verify: `git diff --stat README.md` shows only intended changes; no real values introduced (grep diff for the two IPs, `C:\Users`, `AIza`, `sk-`).

### Task 3: README — examples, roadmap, limitations, disclaimer, sponsorship

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2 sections; `examples/github/` listing; FUNDING decision.
- Produces: final README satisfying brief §2 + §3.

1. **Portfolio analysis examples**: point to `examples/github/` (existing anonymized outputs) + one synthetic snippet block clearly marked as illustrative (AAPL/MSFT, round numbers, "not real portfolio data").
2. **Roadmap**: only real, already-planned items: `--scheduled`, `--no-ai`, `--asset`, `--validate-only`, `--dry-run` flags (README already lists them as planned), runtime/run.lock + exit codes 3/4/5, benchmark result publication hygiene, docs polish. No promised returns or trading features.
3. **Limitations**: AI advisory not advice; no guaranteed returns; no live order execution; single-user local app; Python 3.12 only; pandas 3.x unsupported; pandas-ta vs manual numerics differ; benchmark is machine-specific; news quality depends on free feeds; cloud fallback carries ticker-level queries only; T212 statement CSV is a cross-check, never truth.
4. **Disclaimer** (explicit block, brief wording requirement): educational/personal research tool; no investment advice; no guarantee of returns; AI output may be wrong; verify independently; author not liable; not affiliated with Trading 212.
5. **Sponsorship section** (replaces thin "Support this work"): what support funds — financial data infrastructure, improved calculations, portfolio analytics, local AI integration, testing, documentation, open-source maintenance (from brief §3). Tier table (realistic, non-financial benefits):

   | Tier | Amount | Benefit |
   |---|---|---|
   | Supporter | $2 | Support ongoing development |
   | Backer | $5 | Name in the README supporters list |
   | Sponsor | $10 | Roadmap priority polls in Discussions |
   | Gold Sponsor | $25 | All above + sponsor-only release notes |

   No investment recommendations or private financial advice as benefits. Note that `.github/FUNDING.yml` enables the Sponsor button.
6. Keep License section (MIT) as-is; it already links the LICENSE file semantics.

- [ ] Step 1: Apply edits with `edit`.
- [ ] Step 2: Self-review README against brief §2 checklist (all 15 required items present).

### Task 4: FUNDING.yml and repo hygiene

**Files:**
- Modify: `.github/FUNDING.yml` (add comments documenting approval date; keep `github: DracieVajko`)
- Modify: `.gitignore` (backup zip rule)
- Untrack: `PortfolioAI_Assistant_backup.zip`

- [ ] Step 1: `.github/FUNDING.yml` → comments + `github: DracieVajko` (approved 2026-11-12).
- [ ] Step 2: `.gitignore` gets a "repo backups" line: `PortfolioAI_Assistant_backup.zip` (+ generic `*backup.zip` guard is too broad — use the exact name plus `*_backup.zip`).
- [ ] Step 3: `git rm --cached PortfolioAI_Assistant_backup.zip` (file stays on disk; no history rewrite).
- [ ] Step 4: Verify: `git ls-files | Select-String backup.zip` is empty; `Get-Item PortfolioAI_Assistant_backup.zip` still exists locally.

### Task 5: Validation

**Files:** none modified.

- [ ] Step 1: Full offline suite: `py -3.12 -m pytest tests/ -q`. Expected: 1077+ passed, 2 skipped, only the known env failure.
- [ ] Step 2: FUNDING.yml parses: `python -c "import yaml,sys; yaml.safe_load(open('.github/FUNDING.yml', encoding='utf-8')); print('FUNDING OK')"`.
- [ ] Step 3: Link/target existence check for every repo-relative path referenced by README (docs/archive/audit/PROJECT_AUDIT.md, examples/github/*, tests/MODEL_BENCHMARK_README.md, agent_data/*.example.*, scripts/verify_environment.py, LICENSE, SECURITY.md, CONTRIBUTING.md, CHANGELOG.md, docs/*.md).
- [ ] Step 4: Secret scan of the staged diff: no real keys, IPs, user paths; examples keep placeholders.

### Task 6: Commit and push

**Files:** all above.

- [ ] Step 1: Commit 1 (docs): README + FUNDING.yml — `docs: sponsor-ready README, provenance tiers, architecture and disclaimer`.
- [ ] Step 2: Commit 2 (chore): zip untrack + .gitignore — `chore: untrack anonymized backup zip, keep it local`.
- [ ] Step 3: `git push -u origin feat/github-sponsors-and-documentation`. No merge, no PR creation unless asked.

# Portfolio AI Assistant — Upgrade Plán (desloppify-driven)

Tento dokument je jediným kanonickým plánom pre upgradeポートfólia asistenta podľa požiadaviek v `OPENCODE_PROMPT_PORTFOLIO_AI_ASSISTANT_UPGRADE.md` a `deepresearch portofliot212.txt`. Všetky zmeny sa robia v malých, otestovateľných krokoch (vertikálne rezy), každý krok má vlastný test alebo overenie.

## 0. Stav projektu (základná analýza)

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `portfolio_ai_assistant.py` | EXISTS | CLI vstupný bod, `run_engine()` volanie |
| `investment_engine/run_engine.py` | EXISTS | Orchestrátor (687 riadkov), volá `run_phases/*` |
| `investment_engine/run_phases/setup.py` | EXISTS | Run identity, watchdog, asset universe |
| `investment_engine/run_phases/broker.py` | EXISTS | T212 fetch + canonical reconciliation |
| `investment_engine/run_phases/news.py` | EXISTS | News fetch + source ledger |
| `investment_engine/run_phases/earnings.py` | EXISTS | Earnings fast path + calendar layer |
| `investment_engine/run_phases/enrichment.py` | EXISTS | Portfolio enrichment (standalone holdings, PIE) |
| `investment_engine/run_phases/decisions.py` | EXISTS | LLM decision sections (crypto/tech/renewables) |
| `investment_engine/run_phases/ai_context.py` | EXISTS | Machine context archive |
| `investment_engine/run_phases/reporting.py` | EXISTS | Briefs, diagnostics, result payload |
| `investment_engine/providers/generation.py` | EXISTS | LLM generovanie, fallback chain |
| `investment_engine/providers/telemetry.py` | EXISTS | Local AI attempt tracker |
| `investment_engine/research/technical_analysis.py` | EXISTS | RSI, SMA, Bollinger, EMA, MACD, ADX, atď. |
| `investment_engine/research/earnings_fetch.py` | EXISTS | Earnings fetch |
| `investment_engine/research/peak_valley.py` | EXISTS | Peak/valley detekcia |
| `investment_engine/research/market_data.py` | EXISTS | Trhové dáta, earnings |
| `investment_engine/research/news_engine.py` | EXISTS | News fetcher (StrictNewsFetcher, EnhancedNewsFetcher) |
| `investment_engine/research/news_sources.py` | EXISTS | Enhanced news sources |
| `investment_engine/research/web_researcher.py` | EXISTS | Web researcher (Playwright adapter) |
| `investment_engine/research/ta_charts.py` | EXISTS | TA charty |
| `investment_engine/research/ta_snapshot.py` | EXISTS | Technická snímka |
| `investment_engine/research/fundamentals.py` | EXISTS | Fundamentálna analýza |
| `investment_engine/research/corpus/` | EXISTS | Research corpus (builder, dedupe, status, tieres) |
| `investment_engine/portfolio/exposure.py` | EXISTS | Portfolio expozícia |
| `investment_engine/portfolio/performance.py` | EXISTS | Portfólio performance |
| `investment_engine/portfolio/symbols.py` | EXISTS | Symbol resolver |
| `investment_engine/portfolio/t212_view.py` | EXISTS | T212 view |
| `investment_engine/risk/profiles.py` | EXISTS | Risk profiles |
| `investment_engine/risk/exposure.py` | EXISTS | Expozícia |
| `investment_engine/risk/order_plan.py` | EXISTS | Order plány |
| `investment_engine/risk/risk_profiles.py` | EXISTS | Risk profily |
| `investment_engine/risk/sizing.py` | EXISTS | Sizing (pozície) |
| `investment_engine/skills/` | EXISTS | Skill registry a skill balíčky (equity_research_analyst, investment_committee, portfolio_risk_manager, news_event_analyst) |
| `investment_engine/utils/coerce.py` | EXISTS | Numeric coercion |
| `investment_engine/run_state.py` | EXISTS | Spoločný stav behu |
| `investment_engine/schemas/context.py` | EXISTS | Typové šablóny (AssetInput, T212Snapshot, PortfolioRow, AIContextInputs, RunResult) |
| `tests/` | EXISTS | 400+ testov (unit + integration + phase testy) |

### Chýbajúce komponenty (podľa UPGRADE_MD):
1. **Front-end CLI rozšírenie** - `--screen`, `--discover`, `--chart`, `--forecast`, `--report` flagy (momentálne existujú len `--config`, `--investment-engine`, `--generate-full-report`, `--execution-mode`, `--api-only`, `--preflight`, `--t212-csv`, `--include-quantities`, `--rotation-plan`)
2. **Discovery engine** - existuje `investment_engine/discovery/` ale nie je plne integrovaný do `run_engine.py`
3. **Chart intelligence** - existuje `investment_engine/research/ta_charts.py` ale nie je integrovaný do reportov
4. **Forecast engine** - chýbajú pesimistický/base/optimistický scénáre
5. **Backtesting engine** - chýbajú unit testy pre strategické signály (backtesting)
6. **Dependency injection** - provider factory funguje, ale nie je clear separácia sync/async

---

## 1. Plán implementácii (vertikálne rezy)

### Krok 1: Objev a validácia (DEN 1)
- [x] Prečítať celý kódový základ (investment_engine/, trading212/, tests/, requirements.txt, README.md, config súbory)
- [ ] Overiť, že všetky existujúce testy prechádzajú: `py -3.12 -m pytest tests/ -q`
- [ ] Overiť, že `portfolio_ai_assistant.py --api-only` beží bez chýb
- [ ] Vytvoriť `docs/PORTFOLIO_AI_UPGRADE_PLAN.md` (tento dokument)

### Krok 2: Objev engin - Discovery Engine (DEN 2-3)
Ciel: najít nové možnosti mimo aktuálneho portfólia.

- [ ] `investment_engine/discovery/screener.py` - implementovať screening podľa tržnej kapitoly, P/E, objemu, sektora, geografie
- [ ] `investment_engine/discovery/universe.py` - rozšetriť na ~1000 likvidných akcií (US/EU)
- [ ] `investment_engine/research/technical_analysis.py` - pridať detekciu "pullback in uptrend" a "breakout from downtrend"
- [ ] Relatívna sila vs benchmark (SPY/QQQ) - vypočítať relativnú silu
- [ ] Pridať do `run_engine.py` discovery krok (voliteľný, konfigurácia `discovery_enabled`)

### Krok 3: Investičná inteligencia (DEN 3-4)
Ciel: sledovať investorov, 13F filingy, insider nákupy.

- [ ] `investment_engine/research/investor_intelligence.py` - nový modul pre investorskú inteligenciu
- [ ] SEC EDGAR 13F-HR parsovanie (sec-edgar-downloader, edgarapi)
- [ ] OpenFIGI CUSIP→ticker mapovanie (s cacheovaním)
- [ ] Form 4 parsing (insider buying cluster detection)
- [ ] Cramer inverzná stratégia (SJIM ETF história)
- [ ] Warren Buffett / Berkshire 13F tracking (QoQ diff)
- [ ] Kongressové obchodovanie (House/Senate)

### Krok 4: Notifikácie (DEN 4)
Ciel: email, web push, mobilné push upozornenia.

- [ ] `investment_engine/notifications.py` - rozširiť o Telegram (python-telegram-bot), ntfy.sh, desktop notifikácie (win10toast)
- [ ] `scripts/send_notification.py` - CLI pre odosielanie upozornení
- [ ] Email (smtplib + Gmail App Password) ako fallback
- [ ] Windows Toast (win10toast/plyer) pre lokálne upozornenia

### Krok 5: Stratégické hodnotenie / Backtesting (DEN 5-7)
Ciel: overiť stratégie na historických dátach.

- [ ] `investment_engine/backtesting/` - nový adresár s backtesting enginem
- [ ] `vectorbt` alebo `backtesting.py` ako základ (podľa testov)
- [ ] `investment_engine/backtesting/backtest_engine.py` - core backtesting logika
- [ ] `investment_engine/backtesting/metrics.py` - Sharpe, Sortino, max drawdown, win rate
- [ ] `investment_engine/backtesting/test_backtest.py` - testy na historických dátach
- [ ] Walk-forward optimalizácia, out-of-sample testovanie
- [ ] Transakčné náklady (slippage, commission, tax) v backtestoch
- [ ] SQLite schéma pre signály, výsledky a výkon stratégie

### Krok 6: Dátová vrstva / úložisko (DEN 7-8)
Ciel: centralized úložiště pre všetky dáta.

- [ ] `investment_engine/storage.py` - rozšetriť o SQLite tabuľky (portfolio_snapshots, signals, outcomes, reconciliation_history)
- [ ] `investment_engine/storage/cache.py` - cacheovanie historických cienných dát (parquet/SQLite)
- [ ] `investment_engine/research/ta_snapshot.py` - už existuje, rozšetriť o caching
- [ ] pandas-ta vs TA-Lib vs manuálné indikátory - zachovať manuálne ako canonical (podľa requirements.txt)

### Krok 7: Portfólio inteligencia (DEN 8-9)
Ciel: sector concentration, PIE vs standalone, diverzifikácia.

- [ ] `investment_engine/portfolio/sector_concentration.py` - sector concentration riziko (korelačná matica, faktorová expozícia)
- [ ] `investment_engine/portfolio/pie_vs_standalone.py` - detekovať quantity outside PIE (samostatné vs PIE-held)
- [ ] `investment_engine/portfolio/diversification.py` - Herfindahl index, efektívny počet pozícií, korelácia
- [ ] `investment_engine/risk/risk_parity.py` - risk parity výpočet
- [ ] `investment_engine/risk/max_drawdown.py` - maximálny pokles
- [ ] `investment_engine/risk/sharpe_sortino.py` - Sharpe/Sortino pomer

### Krok 7: Grafická inteligencia (DEN 9-10)
Ciel: vytvárať, ukladáť, nájsť a porovnávať grafy.

- [ ] `investment_engine/research/ta_charts.py` - rozšetriť o Plotly/matplotlib generovanie
- [ ] `investment_engine/reporting/chart_store.py` - správa grafových súborov (reports/charts/{ticker}/{timeframe}_{date}.html/.png)
- [ ] `investment_engine/reporting/chart_search.py` - vyhľadávanie grafov podľa tickra, dátumu, časového rozostupu
- [ ] `investment_engine/research/vision_adapter.py` - voliteľné poslanie grafu do lokálneho vision modelu (iba ak je nakonfigurované)
- [ ] `investment_engine/reporting/chart_comparison.py` - porovnanie dvoch grafov (ticker A vs ticker B)

### Krok 8: Predikčný engine (DEN 10-12)
Ciel: pesimistický/base/optimistický scénář.

- [ ] `investment_engine/research/forecast_engine.py` - nový modul pre predikcie
- [ ] Historické regresné modely (bootstrap, block-bootstrap)
- [ ] Scénáre: 1 deň, 5 dní, 20 dní, 60 dní, 252 dní (obchodné dni)
- [ ] Vstupy: adjusted/raw returns, realized volatility/EWMA, ATR, trendové funkcie, benchmark/sektorové návraty, tržný režim, earnings/event horizont
- [ ] Výstup: pesimistický/base/optimistický scénár s explicitnými horizontami, nejistotnými intervalmi, predpokladmi a merateľnou historickou kalibráciou
- [ ] Žiadne look-ahead bias, survivorship bias, budúce fundamenty, budúce indexové súčasti alebo ex-post dáta

### Krok 9: Základné a makro kontextový engine (DEN 12-13)
Ciel: časové razítka z primárnych/dôveryhodných zdrojov.

- [ ] `investment_engine/research/fundamentals.py` - už existuje, rozšetriť o append-only záznamy
- [ ] `investment_engine/research/macro_context.py` - nový modul pre makro kontext (úrokové sadzby, inflácia, HDP)
- [ ] `investment_engine/research/earnings_calendar.py` - earnings kalendár (potvrzené/odhadované)

### Krok 10: Portfólio riziková a alokácia engine (DEN 13-14)
Ciel: evaluovať konzentráciu, sector/country/mena expozíciu, korelácie, hotovosť, dividendy, obchodnú históriu, rizikové sizes a cilové alokárie.

- [ ] `investment_engine/risk/concentration.py` - sektorová konzentrácia (korelačná matica, faktorová expozícia)
- [ ] `investment_engine/risk/correlation.py` - rolling korelácia a kovariancia
- [ ] `investment_engine/risk/drawdown.py` - maximálny pokles
- [ ] `investment_engine/risk/sharpe_sortino.py` - Sharpe/Sortino pomer (už existuje čiastočne)
- [ ] `investment_engine/risk/risk_parity.py` - risk parity výpočet
- [ ] `investment_engine/risk/allocation.py` - alokácia podle uživateľského cieľového alokácie

### Krok 11: Signálové hodnotenie a backtesting engine (DEN 14-16)
Ciel: zaznamenať každé odporúčanie a neskôr ho porovnať s skutočnými trhovými výsledkami.

- [ ] `investment_engine/signals/` - nový adresár pre signálový engine
- [ ] `investment_engine/signals/signal_recorder.py` - zaznamenávať každé odporúčanie (typ, cíl, čas, cena, dôvod)
- [ ] `investment_engine/signals/signal_validator.py` - porovnávat signály so skutočnými trhovými výsledkami
- [ ] `investment_engine/signals/backtest_engine.py` - backtesting engine (použiť vectorbt alebo backtesting.py)
- [ ] `investment_engine/signals/test_backtest.py` - testy na historických dátach
- [ ] Transakčné náklady (slippage, provízie, daň) pre realistické backtesty

### Krok 12: LLM analytik ako reasonovací a komunikačný vrstva (DEN 16-17)
Ciel: LLM nie je zdroj numerických hodnôt, alereasoning a komunikácia vrstva.

- [ ] `investment_engine/providers/llm_analyst.py` - nový modul pre LLM analytika
- [ ] LLM vysvetľuje deterministické výpočty, nevytvára čísla
- [ ] LLM výstup musí byť označený ako `SOURCE_REPORTED`, `INFERENCE`, `ASSUMPTION`, `PROPOSAL`, `UNVERIFIED`, `CONFLICTING` alebo `UNKNOWN`
- [ ] LLM výstup nemôže prepísať deterministické výpočty, rizikové brány, datové kvalitné brány alebo užívateľské nastavenia

### Krok 13: Aktualizácia dokumentácie a konfigurácie (DEN 17-18)
- [ ] `docs/PORTFOLIO_AI_UPGRADE_PLAN.md` - udržiavať aktuálny
- [ ] `README.md` - pridať dokumentáciu pre nové funkcie (discovery, chart intelligence, forecast, backtesting)
- [ ] `portfolio_config.json` - pridať nové konfiguračné možnosti (discovery_enabled, chart_enabled, forecast_enabled, backtesting_enabled)
- [ ] `custom_rules.json` - pridať pravidlá pro nové moduly

### Krok 19: Finálne testy a overenie (DEN 18-20)
- [x] Spustiť všetky existujúce testy: `py -3.12 -m pytest tests/ -q`
- [x] Pridať nové testy pre nove moduly
- [x] Overiť, že `--api-only` režim stále funguje
- [x] Overiť, že `--experimental` režim (ak existuje) stále funguje
- [x] Overiť, že žiadne tajné kľúče nie sú v kóde alebo git historii
- [x] Commit a push (iba pokiaľ užívateľ explicitne požiadá)

---

## 5. Day Trader Skill Integration (Phase 1 — Foundation)

Status: **Phase 1 dokončená** (2026-11-06).

- [x] Vendor balíka `day-trader-skill` (MIT, commit `3d0f4ef...`) do `vendor/day_trader_skill/`
- [x] Upstream testy: 315 passed
- [x] Adapter package `investment_engine/day_trader/`:
  - `config.py` — `DayTraderConfig` (safe defaults, `execution.enabled=false`)
  - `runner.py` — subprocess wrapper, JSON parsing, timeout, no `shell=True`
  - `state.py` — state root, JSON read/write, corrupt recovery, archive
  - `premarket.py` — scanner daily, news, analyst, pelosi (read-only)
  - `reporting.py` — `day_trader_brief.md` + `day_trader.json`
- [x] CLI flag `--day-trader` (premarket read-only pack)
- [x] Config `day_trader` v `portfolio_config.json`
- [x] Testy: `test_day_trader_config.py`, `test_day_trader_runner.py`, `test_day_trader_state.py`, `test_day_trader_premarket.py`, `test_day_trader_reporting.py`
- [x] Overenie: `--day-trader` beží OK, status OK, žiadne objednávky

**Fáza 2 (plánovací pack) — dokončená:**
- [x] `investment_engine/day_trader/planning.py` — run_planning (entry → exit → timemachine → budget → risk → ticket)
- [x] CLI flag `--day-trader-plan`
- [x] Overenie: beží OK, status NO_TRIGGER (žiadny trigger mimo obchodných hodín)

**Fáza 4 (execution-ready) — čiastočne:**
- [x] `broker/t212_orders.py` — demo/live order klient (allowlisted endpointy)
- [x] `broker/guard.py` — 3 nezávislé bezpečnostné brány
- [x] `broker/bracket.py` — bracket state machine (entry + stop + target, cancel-on-fill)
- [x] `broker/audit.py` — SQLite order_intents/order_events
- [x] Demo API overené: účet 52364002, €5000.32 total, €3000.00 free
- [x] Testy: guard, bracket, audit, t212 orders, mirror (20 nových)
- [x] Live API overené: účet 46528360, €3212.86 total, €31.88 free
- [x] Safety: `T212_LIVE_ORDER_ENABLED=0`, `T212_LIVE_ACK=` (prázdne), demo `unlimited=True`

**Zostáva (fázy 3, 5):** intraday session loop, alerts, scheduler, dokumentácia, hardening.ých)

**Zostáva (fázy 3, 5):** intraday session loop, alerts, scheduler, dokumentácia, hardening.

---

## 2. Klíčové rozhodnutia (rozhodnutie na základe výskumu)

| Rozhodnutie | Možnosť A | Možnosť B | Vybrané | Dôvod |
|-------------|-----------|-----------|---------|-------|
| Backtesting engine | vectorbt | backtesting.py | **vectorbt** | Rýchlejší, lepší Python 3.12 support, viac funkcionalít |
| Chart engine | Plotly | matplotlib | **Plotly** | Interaktivný HTML, lepšia vizualizácia, jednoduchšia integrácia s webovými reportmi |
| Data layer | SQLite | DuckDB | **SQLite** | Jednoduchší, žiadne externé závislosti, užívateľsky priateľnejší na Windows |
| Numericke indikátory | pandas-ta | Manuálne | **Manuálne** | pandas-ta je archivované a nekompatibilné s pinned stackom (pandas 2.2.3 / numpy 1.26.4) |
| Notifikácie | Email (smtplib) | ntfy.sh | **Oba** | Email pre detailed reporty, ntfy pre rýchle upozornenia |
| Subagent framework | subagent | bez subagentov | **Bez subagentov** | Používame priame volania funkcií v jednom procese |

---

## 3. Kritéria akceptácie (Definition of Done)

- [ ] Všetky existujúce testy prechádzajú: `py -3.12 -m pytest tests/ -q`
- [ ] Nové testy pre nové moduly prechádzajú
- [ ] `py -3.12 portfolio_ai_assistant.py --api-only --config portfolio_config.json` beží bez chýb
- [ ] Žiadne tajné kľúče v kóde, logoch, testoch, správach, Git historií alebo terminal outpute
- [ ] Všetky nové funkcie majú jednotkové testy
- [ ] Všetky nové moduly majú docstrings a typové anotácie
- [ ] `investment_engine/run_engine.py` zostáva tenkou fasádou (≤ 200 riadkov)
- [ ] Žiadne incremental refactoring unrelated content
- [ ] Všetky zmeny sú commitnuté (iba pokiaľ používateľ explicitne požiadá o commit/push)

---

## 4. Poznámky k implementácii

- Všetky nové moduly musia mať `__future__ import annotations`
- Všetky nové funkcie musia mať type hints
- Všetky nové funkcie musia mať docstrings
- Všetky nové moduly musia mať jednotkové testy v `tests/`
- Žiadne segretá v kóde - všetky API kľúče v `api.env` (gitignored)
- Žádné look-ahead bias, survivorship bias, future fundamentals, future index constituents nebo post-event data v backtestoch
- LLM výstup nemôžeoverride deterministické výpočty, risk brány, data-quality brány alebo užívateľské nastavenia
- Defaultný režim je read-only / analysis-only. Nikdy nevytváraj, zruš, modifikuj ani executeuj skutočné Trading 212 objednávky.

Tento dokument je živý dokument - aktualizujte ho po každom dokončenom kroku.
---

## 7. Multi-market Universe + Permanent History (2026-11-06)

- [x] Multi-market universe builder: S&P 500 + Nasdaq-100 + portfolio + configurable EU/China/ETF extras (EXI2.DE, VWCE.DE, 0700.HK, ...)
- [x] Day-trader config: `day_trader.universe` (include_sp500, include_nasdaq100, include_portfolio, extra_symbols, max_symbols)
- [x] Permanent `history/` memory: SQLite `history.db` + `history/live` / `history/demo` JSONL
- [x] `--history` CLI to print recent trades and AI decisions
- [x] Mode separation: `logs/live` vs `logs/demo`; `reports/day_trader/live` vs `reports/day_trader/demo`
- [x] Cleanup/purge scripts only touch `reports/` and `logs/`; `history/` is permanent
- [x] Tests: `test_history.py`, `test_day_trader_universe.py`
- [x] Overenie: S&P 500 fetch 503 tickerov, universe cap 500, scan 253, 66 hits (QQQ, NVDA, MU, AMD, SNDK, INTC, GOOGL, ...) 2026-11-06

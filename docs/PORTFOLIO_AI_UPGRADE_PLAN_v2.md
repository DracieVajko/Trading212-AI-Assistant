# Portfolio AI Assistant - Upgrade Plán (Fáza 2: Rozšírenie podľa OPENCODE_PROMPT + Deep Research)

**Dátum:** 2026-11-06  
**Stav:** Plán vytvorený, začína sa implementácia  
**Cieľ:** Implementovať všetky nové funkcie z oboch dokumentov (OPENCODE_PROMPT + deepresearch) v malých, otestovateľných krokoch

---

## 0. Aktuálny stav (základná analýza)

### Úspešne implementované (z predchádzajúcich sešien):
- ✅ `run_engine` presunutý do `investment_engine/run_phases/` (10 modulov)
- ✅ `main.py` zredukovaný na tenkú fasádu (266 riadkov)
- ✅ Bezpečnosť: `usedforsecurity=False` pre MD5, `defusedxml` pre XML
- **Odstránené `assert` v produkčnom kóde**, nahradené `ValueError`
- **Provider kontrakt**: `ProviderChain` protokol, `ProviderChain` trieda, `CloudProviderSpec`
- **Numerickú konverziu**: `investment_engine/utils/coerce.py` s `coerce_float`/`optional_float`
- **Typové šablóny (TypedDicts)**: `AssetInput`, `PortfolioRow`, `T212Snapshot`, `AIContextInputs`, `RunResult`
- **NewsFetchResult dataclass**: nahradil 8-tiučku pozícií
- **`generate_human_brief` zúžený** z 10 parametrov na iba `result`
- **Legacy R1 cesta odstránená**: `compute_legacy_r1`, `R1_DEPRECATED_ALIASES`
- **FX konsolidácia**: delegované na `broker_first.get_live_fx_rates`
- **Exception handling**: úzky `except` namiesto `except Exception`
- **Mŕtvy kód odstránený**: `investment_engine/prompts/`, `memory/`, `prioritization/`
- **Legacy dokumenty archivované**: `docs/audit/` → `docs/archive/`
- **Skills balíček overený**: `__init__.py` je len docstring, registry importuje len `.contracts`

### Nové testy:
- `tests/test_storage_profiles_cashflows.py` - storage round-trips, risk profily, cashflow konverzia
- Opravené testy po presunutí `run_engine`

### Aktuálne testy:
- **917 passed, 3 skipped, 5 predchádzajúcich zlyhaní** (Python verzia + PIE CSV testy)

---

## 1. Nové komponenty podľa OPENCODE_PROMPT + deepresearch

### 1.1 Discovery Engine (najvyššia priorita)
**Cieľ:** nájsť nové možnosti mimo aktuálneho portfólia.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `discovery/universe.py` | Čiastočne | Má S&P 500, potrebuje rozšírenie na EU/Čínu |
| `discovery/screener.py` | Čiastočne | Má relative_strength, pullback/breakout |
| `discovery/discovery.py` | Čiastočne | Má relative_strength integrovanú |
| `investment_engine/research/technical_analysis.py` | Čiastočne | Má relative_strength, pullback, breakout |

**Chýbajúce:**
- [ ] `investment_engine/discovery/universe.py` - rozšíriť na EU/Čínske akcie (EXI2.DE, VWCE.DE, SPY, QQQ, VWS.CO, IBE.MC, RWE.DE, ENR.DE, LOM.DE, SAP.DE, ASML.AS, MC.PA, TTE.PA, SIE.DE, AIR.PA, BNP.PA, 300750.SZ, BABA, JD, PDD, NIO, BIDU, TCEHY, 0700.HK)
- [ ] `investment_engine/discovery/screener.py` - pridať screener pomocou yfinance (bulk screening)
- [ ] `investment_engine/research/technical_analysis.py` - pridať pullback_in_uptrend, breakout_from_downtrend (už niektoré čiastočne)

### 1.2 Investičná inteligencia
**Cieľ:** sledovať investorov, 13F filingy, insider nákupy.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/research/investor_intelligence.py` | Čiastočne | Existuje, potrebuje SEC EDGAR integraciu |

**Chýbajúce:**
- [ ] SEC EDGAR 13F-HR parsovanie (sec-edgar-downloader)
- [ ] OpenFIGI CUSIP→ticker mapovanie (s cacheovaním)
- [ ] Form 4 parsing (insider buying cluster detection)
- [ ] Warren Buffett / Berkshire 13F tracking (QoY diff)

### 1.3 Notifikácie
**Cieľ:** email, web push, mobilné push upozornenia.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/notifications.py` | Čiastočne | Email (smtplib), ntfy.sh |

**Chýbajúce:**
- [ ] Telegram (python-telegram-bot)
- [ ] ntfy.sh (rýchle upozornenia) - čiastočne implementované
- [ ] Windows Toast (win10toast/plyer)
- [ ] `scripts/send_notification.py` - CLI pre odosielanie upozornení

### 1.4 Backtesting Engine
**Cieľ:** overiť stratégie na historických dátach.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/backtesting/` | Chýbajú | Nový adresár |

**Chýbajúce:**
- [ ] `investment_engine/backtesting/backtest_engine.py` - core backtesting logika (vectorbt)
- [ ] `investment_engine/backtesting/metrics.py` - Sharpe, Sortino, max drawdown, win rate
- [ ] `investment_engine/backtesting/test_backtest.py` - testy

### 1.5 Grafická inteligencia
**Cieľ:** vytvárať, ukladáť, nájsť a porovnávať grafy.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/research/ta_charts.py` | EXISTS | Generovanie grafov |

**Chýbajúce:**
- [ ] `investment_engine/reporting/chart_store.py` - správa grafových súborov
- [ ] `investment_engine/reporting/chart_search.py` - vyhľadávanie grafov
- [ ] `investment_engine/research/vision_adapter.py` - voliteľné poslanie grafu do vision modelu

### 1.6 Predikčný engine
**Cieľ:** pesimistický/base/optimistický scénár.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/research/forecast_engine.py` | CHYBÍ | Nový modul |

**Chýbajúce:**
- [ ] `investment_engine/research/forecast_engine.py` - pesimistický/base/optimistický scénár
- [ ] Scénáre: 1 deň, 5 dní, 20 dní, 60 dní, 252 dní

### 1.7 Makro kontextový engine
**Cieľ:** časové razítka z primárnych zdrojov.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/research/fundamentals.py` | EXISTS | Rozšíriť o append-only záznamy |
| `investment_engine/research/macro_context.py` | CHYBÍ | Nový modul |
| `investment_engine/research/earnings_calendar.py` | CHYBÍ | Earnings kalendár |

**Chýbajúce:**
- [ ] `investment_engine/research/macro_context.py` - makro kontext (úrokové sadzby, inflácia, HDP)
- [ ] `investment_engine/research/earnings_calendar.py` - earnings kalendár

### 1.8 Portfólio riziková a alokácia engine
**Cieľ:** evaluovať konzentráciu, sector/country/mena expozíciu, korelácie, hotovosť, dividendy.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/risk/concentration.py` | CHYBÍ | Nový modul |
| `investment_engine/risk/correlation.py` | CHYBÍ | Nový modul |
| `investment_engine/risk/drawdown.py` | CHYBÍ | Nový modul |
| `investment_engine/risk/sharpe_sortino.py` | ČIASŤOMNE | Čiastočne existuje |
| `investment_engine/risk/risk_parity.py` | CHYBÍ | Nový modul |
| `investment_engine/risk/allocation.py` | CHYBÍ | Nový modul |

**Chýbajúce:**
- [ ] Sektorová konzentrácia (korelačná matica, faktorová expozícia)
- [ ] Rolling korelácia a kovariancia
- [ ] Maximálny pokles (max drawdown)
- [ ] Sharpe/Sortino pomer
- [ ] Risk parity výpočet
- [ ] Alokácia podle cieľového alokácie

### 1.9 Signálové hodnotenie a backtesting engine
**Cieľ:** zaznamenať každé odporúčanie a porovnať s výsledkami.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/signals/` | ČIASŤOMNE | signal_recorder.py existuje |
| `investment_engine/signals/signal_recorder.py` | EXISTS | Zaznamenáva odporúčania |
| `investment_engine/signals/signal_validator.py` | CHYBÍ | Porovnávanie signálov |
| `investment_engine/signals/backtest_engine.py` | CHYBÍ | Backtesting engine |

**Chýbajúce:**
- [ ] `investment_engine/signals/signal_validator.py` - porovnávanie signálov
- [ ] `investment_engine/signals/backtest_engine.py` - backtesting engine
- [ ] `investment_engine/signals/test_backtest.py` - testy

### 1.10 LLM analytik ako reasonovací a komunikačný vrstva
**Cieľ:** LLM nie je zdroj numerických hodnôt, ale reasonovací a komunikačný vrstva.

| Komponent | Stav | Poznámka |
|-----------|------|----------|
| `investment_engine/providers/llm_analyst.py` | CHYBÍ | Nový modul |

**Chýbajúce:**
- [ ] `investment_engine/providers/llm_analyst.py` - LLM vysvetľuje deterministické výpočty
- [ ] LLM výstup označený ako `SOURCE_REPORTED`, `INFERENCE`, `ASSUMPTION`, `PROPOSAL`, `UNVERIFIED`, `CONFLICTING` alebo `UNKNOWN`

---

## 2. Plán implementácie (vertikálne rezy)

### Krok 1: Objev engin - Discovery Engine (DEN 1-2)
- [ ] 1.1 Rozšíriť `investment_engine/discovery/universe.py` o EU/Čínske akcie
- [ ] 1.2 Pridať `investment_engine/discovery/screener.py` screening podľa yfinance
- [ ] 1.3 Pridať `investment_engine/research/technical_analysis.py` pullback/breakout detekciu (čiastočne hotové)

### Krok 2: Investičná inteligencia (DEN 2-3)
- [ ] 2.1 Pridať `investment_engine/research/investor_intelligence.py` SEC EDGAR parsovanie
- [ ] 2.2 Pridať OpenFIGI CUSIP→ticker mapovanie
- [ ] 2.3 Pridať Form 4 parsing (insider buying cluster detection)

### Krok 3: Notifikácie (DEN 3-4)
- [ ] 3.1 Pridať `investment_engine/notifications.py` ntfy.sh (už čiastočne)
- [ ] 3.2 Pridať `scripts/send_notification.py` CLI
- [ ] 3.3 Pridať Telegram (python-telegram-bot)
- [ ] 3.4 Pridať Windows Toast (win10toast/plyer)

### Krok 4: Stratégické hodnotenie / Backtesting (DEN 5-7)
- [ ] 4.1 Vytvoriť `investment_engine/backtesting/backtest_engine.py` (vectorbt)
- [ ] 4.2 Vytvoriť `investment_engine/backtesting/metrics.py` (Sharpe, Sortino, max drawdown)
- [ ] 4.3 Vytvoriť `investment_engine/backtesting/test_backtest.py`

### Krok 5: Dátová vrstva / úložisko (DEN 7-8)
- [ ] 5.1 Rozšíriť `investment_engine/storage.py` o SQLite tabuľky
- [ ] 5.2 Pridať `investment_engine/storage/cache.py` - cacheovanie cien

### Krok 6: Portfólio inteligencia (DEN 8-9)
- [ ] 6.1 Vytvoriť `investment_engine/portfolio/sector_concentration.py`
- [ ] 6.2 Vytvoriť `investment_engine/portfolio/diversification.py` (Herfindahl index)
- [ ] 6.3 Vytvoriť `investment_engine/portfolio/diversification.py` (Herfindahl index, efektívny počet pozícií, korelácia)
- [ ] 6.4 Vytvoriť `investment_engine/risk/risk_parity.py`
- [ ] 6.5 Vytvoriť `investment_engine/risk/max_drawdown.py`
- [ ] 6.6 Vytvoriť `investment_engine/risk/sharpe_sortino.py`
- [ ] 6.7 Vytvoriť `investment_engine/risk/allocation.py`

### Krok 7: Grafická inteligencia (DEN 9-10)
- [ ] 7.1 Rozšíriť `investment_engine/research/ta_charts.py`
- [ ] 7.2 Vytvoriť `investment_engine/reporting/chart_store.py`
- [ ] 7.3 Vytvoriť `investment_engine/reporting/chart_search.py`
- [ ] 7.4 Vytvoriť `investment_engine/research/vision_adapter.py`

### Krok 8: Predikčný engine (DEN 10-12)
- [ ] 8.1 Vytvoriť `investment_engine/research/forecast_engine.py`
- [ ] 8.2 Scénáre: 1 deň, 5 dní, 20 dní, 60 dní, 252 dní
- [ ] 8.3 Vstupy: adjusted/raw returns, realized volatility/EWMA, ATR, trendové funkcie, benchmark/sektorové návraty, tržný režim, earnings/event horizont
- [ ] 8.4 Výstup: pesimistický/base/optimistický scénár

### Krok 9: Základné a makro kontextový engine (DEN 12-13)
- [ ] 9.1 Rozšíriť `investment_engine/research/fundamentals.py`
- [ ] 9.2 Vytvoriť `investment_engine/research/macro_context.py`
- [ ] 9.3 Vytvoriť `investment_engine/research/earnings_calendar.py`

### Krok 10: Portfólio riziková a alokácia engine (DEN 13-14)
- [ ] 10.1 Vytvoriť `investment_engine/risk/concentration.py`
- [ ] 10.2 Vytvoriť `investment_engine/risk/correlation.py`
- [ ] 10.3 Vytvoriť `investment_engine/risk/drawdown.py`
- [ ] 10.4 Vytvoriť `investment_engine/risk/sharpe_sortino.py`
- [ ] 10.5 Vytvoriť `investment_engine/risk/risk_parity.py`
- [ ] 10.6 Vytvoriť `investment_engine/risk/allocation.py`

### Krok 11: Signálové hodnotenie a backtesting engine (DEN 14-16)
- [ ] 11.1 Vytvoriť `investment_engine/signals/signal_recorder.py` (už existuje)
- [ ] 11.2 Vytvoriť `investment_engine/signals/signal_validator.py`
- [ ] 11.3 Vytvoriť `investment_engine/signals/backtest_engine.py`
- [ ] 11.4 Vytvoriť `investment_engine/signals/test_backtest.py`

### Krok 12: LLM analytik ako reasonovací a komunikačný vrstva (DEN 16-17)
- [ ] 12.1 Vytvoriť `investment_engine/providers/llm_analyst.py`
- [ ] 12.2 LLM vysvetľuje deterministické výpočty, nevytvára čísla
- [ ] 12.3 LLM výstup označený ako `SOURCE_REPORTED`, `INFERENCE`, `ASSUMPTION`, `PROPOSAL`, `UNVERIFIED`, `CONFLICTING` alebo `UNKNOWN`

### Krok 13: Aktualizácia dokumentácie a konfigurácie (DEN 17-18)
- [ ] 13.1 `docs/PORTFOLIO_AI_UPGRADE_PLAN.md` - udržiavať aktuálny
- [ ] 13.2 `README.md` - pridať dokumentáciu pre nové funkcie
- [ ] 13.3 `portfolio_config.json` - pridať nové konfiguračné možnosti

### Krok 19: Finálne testy a overenie (DEN 18-20)
- [ ] 19.1 Spustiť všetky existujúce testy: `py -3.12 -m pytest tests/ -q`
- [ ] 19.2 Pridať nové testy pre nové moduly
- [ ] 19.3 Overiť, že `--api-only` režim stále funguje
- [ ] 19.4 Overiť, že `--experimental` režim stále funguje
- [ ] 19.5 Overiť, že žiadne tajné kľúče nie sú v kóde alebo git historii
- [ ] 19.6 Commit a push (iba pokiaľ užívateľ explicitne požiadá)

---

## 3. Klíčové rozhodnutia

| Rozhodnutie | Možnosť A | Možnosť B | Vybrané | Dôvod |
|-------------|-----------|-----------|---------|-------|
| Backtesting engine | vectorbt | backtesting.py | **vectorbt** | Rýchlejší, lepší Python 3.12 support, viac funkcionalít |
| Chart engine | Plotly | matplotlib | **Plotly** | Interaktivný HTML, lepšia vizualizácia |
| Data layer | SQLite | DuckDB | **SQLite** | Jednoduchší, žiadne externé závislosti |
| Numericke indikátory | pandas-ta | Manuálne | **Manuálne** | pandas-ta je archivované |
| Notifikácie | Email (smtplib) | ntfy.sh | **Oba** | Email pre detailné reporty, ntfy pre rýchle upozornenia |
| Subagent framework | subagent | bez subagentov | **Bez subagentov** | Používame priame volania funkcií |

---

## 4. Kritéria akceptácie (Definition of Done)

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

# Custom Investment Rules

## Overview

`custom_rules.json` is a user-editable file that overrides default investment
rules and script behavior. Copy `custom_rules.example.json` to `custom_rules.json`
and modify as needed. The file is gitignored (never committed).

## Precedence (highest to lowest)

1. **CLI flags** (`--rotation-plan`, `--include-quantities`, `--execution-mode`, `--api-only`)
2. **custom_rules.json** (user overrides)
3. **investment_policy.json** (policy profiles)
4. **portfolio_config.json** (base settings)
5. **Built-in defaults** (code defaults)

## Sections

### `investment_rules`

| Key | Default | Description |
|---|---|---|
| `max_position_pct` | 15.0 | Maximum % of portfolio in a single position |
| `cash_floor_pct` | 5.0 | Minimum cash allocation % |
| `stop_loss_pct` | -7.0 | Stop-loss threshold (%) |
| `take_profit_pct` | 10.0 | Take-profit threshold (%) |
| `dca_interval` | "monthly" | DCA frequency: daily/weekly/monthly |
| `dca_day` | 1 | Day of month for DCA (1-28) |
| `sector_limits` | {} | Per-sector max % (e.g., {"TECH": 40}) |
| `ignore_otc` | true | Skip OTC/penny stocks |
| `prefer_dividend` | false | Prefer dividend-paying stocks |
| `risk_per_trade_pct` | 2.0 | Max risk per trade (% of portfolio) |
| `max_positions` | 20 | Maximum number of positions |
| `min_position_pct` | 1.0 | Minimum position size % |
| `rebalance_threshold_pct` | 5.0 | Rebalance when drift exceeds this % |
| `allow_averaging_down` | true | Allow averaging down on losing positions |
| `averaging_down_max_cycles` | 3 | Max averaging-down cycles |
| `averaging_down_trim_pct` | 30 | Trim % per averaging-down cycle |

### `strategy_aggression`

| Key | Default | Description |
|---|---|---|
| `buy_threshold` | 60 | Buy signal probability threshold (0-100) |
| `sell_threshold` | 65 | Sell signal probability threshold (0-100) |
| `hold_threshold` | 40 | Hold signal probability threshold (0-100) |
| `earnings_priority` | "high" | Earnings importance: low/medium/high |
| `earnings_prediction_weight` | 0.3 | Weight of earnings prediction in scoring (0-1) |
| `news_trust_level` | "medium" | News trust: low/medium/high |
| `news_relevance_min` | 60 | Minimum news relevance score (0-100) |
| `technical_weight` | 0.4 | Technical analysis weight in composite score (0-1) |
| `fundamental_weight` | 0.4 | Fundamental analysis weight in composite score (0-1) |
| `sentiment_weight` | 0.2 | Sentiment analysis weight in composite score (0-1) |
| `min_data_quality_for_signal` | 60 | Minimum data quality for signal generation (0-100) |
| `allow_ai_override` | false | Allow AI to override deterministic signals |
| `contrarian_mode` | false | Invert signals (experimental) |

### `script_behavior`

| Key | Default | Description |
|---|---|---|
| `provider_chain` | "auto" | LLM provider chain: auto/public/locals |
| `lm_studio_model` | "openai/gpt-oss-20b" | LM Studio model ID |
| `news_relevance_threshold` | 60 | Minimum news relevance score |
| `max_news_age_days` | 2 | Maximum age of news articles (days) |
| `use_social_sentiment` | true | Enable social sentiment analysis |
| `use_reddit` | true | Enable Reddit sentiment |
| `use_x_sentiment` | true | Enable X/Twitter sentiment |
| `use_stocktwits` | true | Enable StockTwits sentiment |
| `auto_discovery_limit` | 8 | Maximum auto-discovered assets |
| `max_news_per_asset` | 4 | Maximum news articles per asset |
| `max_forum_per_asset` | 5 | Maximum forum posts per asset |
| `max_web_per_asset` | 5 | Maximum web results per asset |
| `enable_slovak_news` | false | Enable Slovak-language news feeds |
| `use_playwright_fallback` | true | Use Playwright for web scraping |
| `playwright_headless` | true | Run Playwright in headless mode |
| `playwright_timeout_seconds` | 30 | Playwright timeout (seconds) |
| `language` | "en" | Report language: en/sk |
| `output_folder` | "reports" | Output directory |
| `archive_folder` | "reports/archive" | Archive directory |
| `log_folder` | "logs" | Log directory |

### `rotation`

| Key | Default | Description |
|---|---|---|
| `rotation_plan` | "none" | Rotation strategy: none/average-down/short-rotation/cash-apy |
| `rotation_trim_pct` | 30 | Trim % per rotation cycle |
| `rotation_target` | "AAPL" | Target ticker for short-rotation |
| `apy_rate` | 3.0 | APY rate for cash-apy simulation (%) |
| `include_quantities` | false | Keep quantity columns from CSV/XLSX input |

### `per_ticker_overrides`

Per-ticker overrides for `max_position_pct` and `preferred_action` (hold/trim/reduce).

### `notifications`

| Key | Default | Description |
|---|---|---|
| `notify_on_fail` | true | Send urgent notification on run failure |
| `notify_on_complete` | true | Send summary notification on successful run |
| `notify_email_to` | "" | Email recipient (comma-separated) |
| `notify_ntfy_topic` | "" | ntfy.sh topic name for push notifications |
| `notify_urgent_threshold_pct` | -10.0 | Urgent alert threshold (% PPL) |

## Example

```json
{
  "investment_rules": {
    "max_position_pct": 20.0,
    "stop_loss_pct": -5.0,
    "take_profit_pct": 15.0
  },
  "strategy_aggression": {
    "buy_threshold": 70,
    "sell_threshold": 75,
    "news_trust_level": "high"
  },
  "rotation": {
    "rotation_plan": "average-down",
    "rotation_trim_pct": 25
  }
}
```

Only the keys you specify are overridden; all others use defaults from the lower-precedence source.

## Validation

- Missing keys → default applied (no error)
- Invalid type → key skipped with WARNING (never crashes)
- Unknown keys → ignored (no error)
- File missing → all defaults apply (no error)

## Git

`custom_rules.json` is gitignored (never committed). Only `custom_rules.example.json` is tracked.

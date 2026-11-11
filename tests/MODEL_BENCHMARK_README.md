# Model Benchmark Suite

## Purpose

Ranks the local LLM models that LM Studio offers, using the real analysis
stages of this project, so a model can be picked on evidence: speed,
reliability and whether the answer is actually usable.

Three questions it answers per model:

1. **Speed** — real tokens per second from the server's `usage` block (not a
   chars/4 estimate).
2. **Reliability** — how many attempts returned HTTP 200 with non-empty
   content. A model that sometimes times out or gets evicted scores lower.
3. **Worth** — does the answer parse as the JSON/text the stage requires
   (keys, item counts, minimum length). A fast model that breaks JSON is not
   worth using.

## Candidate Models

### Default set (small or sparse — used by `--run-all`)

| Name | LM Studio ID | Size | Typical role |
|---|---|---|---|
| qwen3.8-9b-distill | `qwen3.8-9b-distill` | 9B | Fast fallback, screening |
| nemotron-e4b | `nvidia-nemotron-3.5-bolt-e4b` | 7.5B (4B active) | Fast fallback, low VRAM |
| gpt-oss-20b | `openai-gpt-oss-20b-claude-4.5-opus-heretic-uncensored-i1` | 20B sparse | Decision, finance |
| gemma-4-26b | `google/gemma-4-26b-a4b-qat` | 26B (4B active) | Writer, thinking |

### Large models (opt-in, `--include-large`)

Large dense models take minutes per stage, pressure RAM and can be evicted
mid-run, so they are excluded from the default run. Asking for one without the
flag is an error rather than a silent hour of waiting.

| Name | LM Studio ID | Size |
|---|---|---|
| qwen3.6-35b-a3b | `qwen/qwen3.6-35b-a3b` | 35B (3B active) |
| qwen3.8-27b-swift | `swift-qwen3.8-27b` | 27B dense |
| qwen3.8-27b-twin-turbo | `qwen3.8-27b-twin-turbo-...` | 27B dense |
| mirothinker-30b | `mirothinker-v1.5-30b-q2ks-mixed-autoround` | 30B dense |
| prism-ml-bonsai-27b | `prism-ml/bonsai-27b` | 27B dense |
| nemotron-74b | `nvidia-nemotron-3.5-bolt-74b-a9b` | 74B (9B active) |

## Usage

```bash
# List available models in LM Studio
python tests/model_benchmark.py --list-models

# Run the default small set (recommended)
python tests/model_benchmark.py --run-all

# Run specific models
python tests/model_benchmark.py --models qwen3.8-9b-distill,nemotron-e4b

# Run specific stages, twice per stage
python tests/model_benchmark.py --models qwen3.8-9b-distill --stages decision,fast --repeat 2

# Explicitly include a large model (slow; may not fit)
python tests/model_benchmark.py --models qwen3.8-27b-swift --include-large

# Custom LM Studio URL
python tests/model_benchmark.py --base-url http://192.168.1.100:1234/v1 --run-all
```

## Stages Tested

| Stage | Prompt | Max Tokens | Measured |
|---|---|---|---|
| decision | BUY/SELL/HOLD for 5 tickers + rationale | 1024 | JSON array of 5 with ticker/action/confidence |
| finance | Portfolio metrics calculation | 512 | JSON object with the 4 required keys |
| thinking | Structured reasoning chain | 2048 | text, min 900 chars |
| writer | Portfolio brief (200-300 words) | 512 | text, min 600 chars |
| fast | Quick BUY/SELL/HOLD classification | 256 | JSON array of 5 with ticker/signal |

`fast` gets 3 attempts by default (`--stability-stages fast`) because it is
cheap and consistency there matters more than raw speed.

## Scoring

```
quality  = 0.6 × format compliance + 0.4 × reliability
speed    = median tok/s ÷ fastest median tok/s
score    = 100 × quality × (0.6 + 0.4 × speed)
```

A slow model that always answers correctly still ranks well. A fast model that
returns broken JSON ranks low, no matter how quick it is.

## Output

- Markdown: `%USERPROFILE%\Desktop\PortfolioAI_ModelBenchmark\model_benchmark_YYYYMMDD_HHMMSS.md`
- JSON: same folder, same timestamp (raw metrics, every attempt)

Both are rewritten **after every model**, so an interrupted run still leaves the
measurements already taken. Falls back to `results/` when there is no Desktop
folder. Both locations are gitignored: benchmark results are user-local and must
never be committed.

## Notes

- Do not run while a portfolio run is in progress — one model at a time.
- Every other model is unloaded before each candidate; all models are unloaded
  again when the benchmark ends.
- Results depend on hardware (RAM, VRAM, CPU) and on the current machine load.
- Re-run after changing LM Studio settings, GPU drivers or quantisations.

## Recommended Workflow

1. Run `--list-models` to see what's installed.
2. Run `--run-all` and wait for the report on the Desktop.
3. Pick the winner per role from the ranking and the per-stage table.
4. Put those ids into `portfolio_config.json` (`decision_model`,
   `writer_model`, `local_fallback_model`) and `custom_rules.json`
   (`script_behavior.lm_studio_model`).
5. Confirm in the next run's log that the chosen model actually loaded.

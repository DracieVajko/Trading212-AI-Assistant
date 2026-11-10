# Model Benchmark Suite

## Purpose

Tests candidate local LLM models against the actual portfolio analysis stages
to determine which are suitable for each stage (decision, finance, thinking,
writer, fast fallback).

## Candidate Models

| Name | LM Studio ID | Size | Suitability |
|---|---|---|---|
| qwen3.8-9b-distill | `qwen3.8-9b-distill` | 9B | Fast fallback, screening |
| nemotron-e4b | `nvidia-nemotron-3.5-bolt-e4b` | 4B (E4B) | Fast fallback, low VRAM |
| gpt-oss-20b | `openai-gpt-oss-20b-claude-4.5-opus-heretic-uncensored-i1` | 20B | Decision, finance |
| qwen3.6-35b-a3b | `qwen/qwen3.6-35b-a3b` | 35B (3B active) | Decision, finance, thinking |
| gemma-4-26b | `google/gemma-4-26b-a4b-qat` | 26B (4B active) | Writer, thinking |
| qwen3.8-27b-swift | `swift-qwen3.8-27b` | 27B | Thinking, writer |
| qwen3.8-27b-twin-turbo | `qwen3.8-27b-twin-turbo-...` | 27B | Thinking, writer (fast) |
| prism-ml-bonsai-27b | `prism-ml/bonsai-27b` | 27B | Thinking, writer |
| nemotron-74b | `nvidia-nemotron-3.5-bolt-74b-a9b-24gb` | 74B (9B active) | Thinking, writer (high VRAM) |
| mirothinker-30b | `mirothinker-v1.5-30b-q2ks-mixed-autoround` | 30B | Thinking, writer |

## Usage

```bash
# List available models in LM Studio
python tests/model_benchmark.py --list-models

# Run specific models
python tests/model_benchmark.py --models qwen3.8-9b-distill,nemotron-e4b

# Run specific stages
python tests/model_benchmark.py --models qwen3.8-9b-distill --stages decision,fast

# Run everything
python tests/model_benchmark.py --run-all

# Custom LM Studio URL
python tests/model_benchmark.py --base-url http://192.168.1.100:1234/v1 --run-all
```

## Stages Tested

| Stage | Prompt | Max Tokens | Tests |
|---|---|---|---|
| decision | BUY/SELL/HOLD for 5 tickers + rationale | 1024 | JSON output, speed, accuracy |
| finance | Portfolio metrics calculation | 512 | JSON output, speed |
| thinking | Structured reasoning chain | 2048 | Reasoning quality, speed |
| writer | Portfolio brief (200-300 words) | 512 | Writing quality, speed |
| fast | Quick BUY/SELL/HOLD classification | 256 | Speed, accuracy |

## Output

- JSON: `results/model_benchmark_YYYYMMDD_HHMMSS.json` (raw metrics)
- Markdown: `results/model_benchmark_YYYYMMDD_HHMMSS.md` (human-readable report)

## Notes

- DO NOT run during production hours — it loads/unloads models in LM Studio
- Each model is tested sequentially (exclusive load policy)
- Results depend on hardware (VRAM, RAM, CPU)
- The script unloads models after testing each one
- Results are machine-specific and should be re-run on different hardware

## Recommended Workflow

1. Run `--list-models` to see what's available
2. Run `--run-all` to benchmark everything (takes ~30-60 min)
3. Review the markdown report to select best models per stage
4. Update `portfolio_config.json` and `custom_rules.json` with selected models
5. Run the portfolio analysis with the new models
6. Compare results quality

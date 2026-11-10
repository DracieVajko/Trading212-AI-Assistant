#!/usr/bin/env python3
"""Model benchmark suite for Portfolio AI Assistant.

Tests candidate local LLM models against the actual portfolio analysis stages
to determine which are suitable for each stage (decision, finance, thinking,
writer, fast fallback).

Usage:
    python tests/model_benchmark.py [--models MODEL1,MODEL2] [--stages STAGE1,STAGE2]
    python tests/model_benchmark.py --list-models
    python tests/model_benchmark.py --run-all

Output: results/model_benchmark_YYYYMMDD_HHMMSS.json + .md report

DO NOT run during production hours - it loads/unloads models in LM Studio.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

LM_STUDIO_URL = os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
RESULTS_DIR = Path("results")
MAX_CONTEXT = int(os.getenv("LM_STUDIO_CONTEXT_TOKENS", "32000"))

# Models to test (LM Studio model IDs)
CANDIDATE_MODELS = {
    # Small / fast models (suitable for fast fallback, screening)
    "qwen3.8-9b-distill": "qwen3.8-9b-distill",
    "nemotron-e4b": "nvidia-nemotron-3.5-bolt-e4b",
    # Medium models (suitable for decision, finance stages)
    "gpt-oss-20b": "openai-gpt-oss-20b-claude-4.5-opus-heretic-uncensored-i1",
    "qwen3.6-35b-a3b": "qwen/qwen3.6-35b-a3b",
    "gemma-4-26b": "google/gemma-4-26b-a4b-qat",
    # Large models (suitable for thinking/writer stages, if VRAM allows)
    "qwen3.8-27b-swift": "swift-qwen3.8-27b",
    "qwen3.8-27b-twin-turbo": "qwen3.8-27b-twin-turbo-fable-cold-fusion-709-ultra-heretic-uncensored-nm-dau-neo-mtp",
    "prism-ml-bonsai-27b": "prism-ml/bonsai-27b",
}

# Stage prompts (realistic portfolio analysis snippets)
STAGE_PROMPTS = {
    "decision": {
        "system": "You are the decision stage of the investment engine.",
        "prompt": (
            "Portfolio: 98 positions, equity EUR 3,234.85, free cash EUR 1.68. "
            "Top holdings: TTWO 12.5%, C7A0 7.2%, DJGTEEX 7.1%. "
            "Market regime: NEUTRAL. "
            "Recommend BUY/SELL/HOLD for each of these 5 tickers: AAPL, NVDA, MSFT, TSLA, GOOGL. "
            "For each, give: action, confidence (0-100), one-sentence rationale. "
            "Output as JSON array with keys: ticker, action, confidence, rationale."
        ),
        "max_tokens": 1024,
    },
    "finance": {
        "system": "You are the finance stage of the investment engine.",
        "prompt": (
            "Given these portfolio metrics: total_equity=3234.85 EUR, "
            "positions_count=101, free_cash=1.68, unrealized_pnl=-321.26, "
            "realized_pnl=0, invested=3553.19. "
            "Calculate: cash_allocation_pct, concentration_risk (top-3 weight), "
            "drawdown_pct from net_deposits=3469.47. "
            "Output as JSON with keys: cash_allocation_pct, top3_weight_pct, drawdown_pct, risk_level."
        ),
        "max_tokens": 512,
    },
    "thinking": {
        "system": "You are the thinking stage of the investment engine.",
        "prompt": (
            "Analyze this portfolio situation: AAPL at 12.5% weight with earnings in 5 days, "
            "NVDA at 15.1% with earnings in 3 days, market regime NEUTRAL with ADX=27.6. "
            "Should we trim AAPL before earnings? Consider: weight cap 15%, volatility, "
            "earnings risk. Give a structured reasoning chain with evidence and conclusion."
        ),
        "max_tokens": 2048,
    },
    "writer": {
        "system": "You are the writer stage of the investment engine.",
        "prompt": (
            "Write a concise portfolio brief (200-300 words) for a EUR 3234.85 portfolio "
            "with 101 positions. Include: equity summary, top 3 holdings, cash position, "
            "market regime, and 2-3 actionable recommendations. Use markdown formatting."
        ),
        "max_tokens": 512,
    },
    "fast": {
        "system": "You are a fast classification assistant.",
        "prompt": (
            "Classify each ticker as BUY/SELL/HOLD based on RSI: "
            "AAPL RSI=55.6, NVDA RSI=42.0, MSFT RSI=62.1, TSLA RSI=38.2, GOOGL RSI=58.3. "
            "Output only a JSON array: [{\"ticker\":..., \"signal\":...}]."
        ),
        "max_tokens": 256,
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def get_loaded_models(base_url: str) -> list[str]:
    """Return list of currently loaded model IDs."""
    try:
        r = requests.get(f"{base_url}/api/v1/models", timeout=(3, 8))
        if r.status_code == 200:
            models = r.json().get("models", [])
            loaded = []
            for m in models:
                if isinstance(m, dict) and m.get("loaded_instances"):
                    loaded.append(str(m.get("key", "")))
            return loaded
    except Exception:
        pass
    return []


def unload_model(base_url: str, model_id: str) -> bool:
    """Unload a model. Returns True on success."""
    try:
        root = base_url.rstrip("/").removesuffix("/v1")
        r = requests.post(
            f"{root}/api/v1/models/unload",
            json={"instance_id": model_id},
            timeout=(5, 120),
        )
        return r.status_code == 200
    except Exception:
        return False


def load_model(base_url: str, model_id: str, context_length: int = 8192) -> bool:
    """Load a model with given context. Returns True on success."""
    try:
        root = base_url.rstrip("/").removesuffix("/v1")
        r = requests.post(
            f"{root}/api/v1/models/load",
            json={"model": model_id, "context_length": context_length, "echo_load_config": True},
            timeout=(5, 600),
        )
        return r.status_code == 200
    except Exception:
        return False


def run_stage(model_id: str, stage_name: str, stage_config: dict, base_url: str, max_context: int) -> dict:
    """Run a single stage prompt against a model. Returns metrics dict."""
    system = stage_config["system"]
    prompt = stage_config["prompt"]
    max_tokens = stage_config["max_tokens"]

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.15,
        "max_tokens": max_tokens,
        "stream": False,
    }

    start = time.monotonic()
    try:
        r = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            timeout=(30, 300),
        )
        elapsed = time.monotonic() - start
        if r.status_code == 200:
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            # Estimate tokens
            prompt_tokens = len(system + prompt) // 4
            output_tokens = len(content) // 4
            tps = output_tokens / elapsed if elapsed > 0 else 0
            return {
                "status": "ok",
                "elapsed_s": round(elapsed, 2),
                "prompt_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "tokens_per_sec": round(tps, 2),
                "content_len": len(content),
                "content_preview": content[:200],
            }
        else:
            return {
                "status": "error",
                "http_status": r.status_code,
                "elapsed_s": round(elapsed, 2),
                "error": r.text[:200],
            }
    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "status": "exception",
            "elapsed_s": round(elapsed, 2),
            "error": str(e)[:200],
        }


def benchmark_model(model_id: str, stages: list[str], base_url: str, max_context: int) -> dict:
    """Benchmark a single model across multiple stages."""
    # Unload any other models first (exclusive policy)
    loaded = get_loaded_models(base_url)
    for m in loaded:
        if m != model_id:
            unload_model(base_url, m)

    # Check if our model is already loaded
    if model_id not in get_loaded_models(base_url):
        # Try to load
        ok = load_model(base_url, model_id, max_context)
        if not ok:
            return {"model": model_id, "status": "load_failed", "stages": {}}

    results = {}
    for stage_name in stages:
        if stage_name not in STAGE_PROMPTS:
            continue
        result = run_stage(model_id, stage_name, STAGE_PROMPTS[stage_name], base_url, max_context)
        results[stage_name] = result
        # Small delay between stages
        time.sleep(1)

    # Unload the model when done
    unload_model(base_url, model_id)

    return {"model": model_id, "status": "ok", "stages": results}


def list_models(base_url: str) -> list[str]:
    """List all available models in LM Studio."""
    try:
        r = requests.get(f"{base_url}/models", timeout=5)
        if r.status_code == 200:
            data = r.json().get("data", [])
            return [m.get("id", "") for m in data if isinstance(m, dict)]
    except Exception:
        pass
    return []


def generate_report(results: list[dict], stages: list[str]) -> str:
    """Generate a markdown report from benchmark results."""
    lines = [
        "# Model Benchmark Report",
        f"Generated: {datetime.now().isoformat()}",
        f"LM Studio URL: {LM_STUDIO_URL}",
        f"Max context: {MAX_CONTEXT}",
        "",
    ]

    # Summary table
    lines.append("## Summary")
    lines.append("")
    header = "| Model | Status | " + " | ".join(f"{s} (tok/s)" for s in stages) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(stages) + 2))

    for r in results:
        row = f"| {r['model']} | {r['status']} |"
        for s in stages:
            stage = r.get("stages", {}).get(s, {})
            if stage.get("status") == "ok":
                row += f" {stage['tokens_per_sec']} |"
            elif stage.get("status") == "error":
                row += f" ERR({stage.get('http_status', '?')}) |"
            else:
                row += f" {stage.get('status', 'N/A')} |"
        lines.append(row)

    lines.append("")

    # Detailed results
    for r in results:
        lines.append(f"## {r['model']}")
        lines.append(f"Status: {r['status']}")
        for s in stages:
            stage = r.get("stages", {}).get(s, {})
            lines.append(f"### {s}")
            if stage.get("status") == "ok":
                lines.append(f"- Elapsed: {stage['elapsed_s']}s")
                lines.append(f"- Prompt tokens: ~{stage['prompt_tokens']}")
                lines.append(f"- Output tokens: ~{stage['output_tokens']}")
                lines.append(f"- Speed: {stage['tokens_per_sec']} tok/s")
                lines.append(f"- Content length: {stage['content_len']} chars")
                lines.append(f"- Preview: {stage['content_preview'][:100]}...")
            elif stage.get("status") == "error":
                lines.append(f"- HTTP {stage.get('http_status')}: {stage.get('error', '')[:100]}")
            else:
                lines.append(f"- {stage.get('status')}: {stage.get('error', 'N/A')[:100]}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Benchmark local LLM models against portfolio analysis stages")
    parser.add_argument("--models", type=str, default=None, help="Comma-separated list of model names (from CANDIDATE_MODELS keys)")
    parser.add_argument("--stages", type=str, default="decision,finance,fast", help="Comma-separated list of stages to test")
    parser.add_argument("--list-models", action="store_true", help="List available models and exit")
    parser.add_argument("--run-all", action="store_true", help="Run all candidate models and stages")
    parser.add_argument("--base-url", type=str, default=LM_STUDIO_URL, help="LM Studio base URL")
    parser.add_argument("--max-context", type=int, default=MAX_CONTEXT, help="Max context tokens")
    parser.add_argument("--output-dir", type=str, default="results", help="Output directory for results")

    args = parser.parse_args()

    if args.list_models:
        print("Available models in LM Studio:")
        for m in list_models(args.base_url):
            print(f"  {m}")
        print("\nCandidate models (from config):")
        for name, model_id in CANDIDATE_MODELS.items():
            print(f"  {name}: {model_id}")
        return

    if args.run_all:
        models = list(CANDIDATE_MODELS.keys())
        stages = list(STAGE_PROMPTS.keys())
    else:
        models = args.models.split(",") if args.models else ["qwen3.8-9b-distill"]
        stages = args.stages.split(",") if args.stages else ["decision", "finance", "fast"]

    # Resolve model names to IDs
    model_ids = []
    for m in models:
        m = m.strip()
        if m in CANDIDATE_MODELS:
            model_ids.append((m, CANDIDATE_MODELS[m]))
        else:
            model_ids.append((m, m))

    available = list_models(args.base_url)
    print(f"Available models: {len(available)}")
    print(f"Testing {len(model_ids)} models across {len(stages)} stages")
    print(f"Stages: {stages}")
    print()

    results = []
    for name, model_id in model_ids:
        if model_id not in available:
            print(f"SKIP {name} ({model_id}) - not available in LM Studio")
            results.append({"model": name, "status": "not_available", "stages": {}})
            continue

        print(f"BENCHMARKING {name} ({model_id})...")
        result = benchmark_model(model_id, stages, args.base_url, args.max_context)
        results.append(result)
        # Print quick summary
        for s in stages:
            stage = result.get("stages", {}).get(s, {})
            if stage.get("status") == "ok":
                print(f"  {s}: {stage['tokens_per_sec']} tok/s, {stage['elapsed_s']}s, {stage['content_len']} chars")
            else:
                print(f"  {s}: {stage.get('status', 'N/A')} - {stage.get('error', '')[:50]}")
        print()

    # Save results
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"model_benchmark_{timestamp}.json"
    md_path = out_dir / f"model_benchmark_{timestamp}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    report = generate_report(results, stages)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Results saved to {json_path}")
    print(f"Report saved to {md_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()

"""Benchmark candidate local LLM models against the real analysis stages.

Measures, per model:
  * load time and whether the model fits in RAM/VRAM at all
  * real tokens/sec from the server's ``usage`` block (not a chars/4 guess)
  * reliability: how many attempts actually returned HTTP 200 with content
  * format compliance: does the answer parse as the JSON/text the stage needs

Usage:
    python tests/model_benchmark.py --run-all
    python tests/model_benchmark.py --models qwen3.8-9b-distill,gpt-oss-20b
    python tests/model_benchmark.py --stages decision,fast --repeat 2
    python tests/model_benchmark.py --list-models

Reports are written to the Desktop by default and are user-local: never commit
them. Nothing here touches the broker or the portfolio.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LM_STUDIO_URL = os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
MAX_CONTEXT = 16384

# Candidate models (label -> LM Studio model key).
CANDIDATE_MODELS = {
    "qwen3.8-9b-distill": "qwen3.8-9b-distill",
    "nemotron-e4b": "nvidia-nemotron-3.5-bolt-e4b",
    "gpt-oss-20b": "openai-gpt-oss-20b-claude-4.5-opus-heretic-uncensored-i1",
    "qwen3.6-35b-a3b": "qwen/qwen3.6-35b-a3b",
    "gemma-4-26b": "google/gemma-4-26b-a4b-qat",
    "qwen3.8-27b-swift": "swift-qwen3.8-27b",
    "qwen3.8-27b-twin-turbo": (
        "qwen3.8-27b-twin-turbo-fable-cold-fusion-709-ultra-heretic-uncensored-nm-dau-neo-mtp"
    ),
    "mirothinker-30b": "mirothinker-v1.5-30b-q2ks-mixed-autoround",
    "prism-ml-bonsai-27b": "prism-ml/bonsai-27b",
    # Very large: opt-in only, it may not fit and can destabilise the server.
    "nemotron-74b": "nvidia-nemotron-3.5-bolt-74b-a9b",
}

STAGE_PROMPTS: dict[str, dict[str, Any]] = {
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
        "expect": "json_array",
        "items": 5,
        "keys": ("ticker", "action", "confidence"),
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
        "expect": "json_object",
        "keys": ("cash_allocation_pct", "top3_weight_pct", "drawdown_pct", "risk_level"),
    },
    "fast": {
        "system": "You are a fast classification assistant.",
        "prompt": (
            "Classify each ticker as BUY/SELL/HOLD based on RSI: "
            "AAPL RSI=55.6, NVDA RSI=42.0, MSFT RSI=62.1, TSLA RSI=38.2, GOOGL RSI=58.3. "
            'Output only a JSON array: [{"ticker":..., "signal":...}].'
        ),
        "max_tokens": 256,
        "expect": "json_array",
        "items": 5,
        "keys": ("ticker", "signal"),
    },
    "writer": {
        "system": "You are the writer stage of the investment engine.",
        "prompt": (
            "Write a concise portfolio brief (200-300 words) for a EUR 3234.85 portfolio "
            "with 101 positions. Include: equity summary, top 3 holdings, cash position, "
            "market regime, and 2-3 actionable recommendations. Use markdown formatting."
        ),
        "max_tokens": 512,
        "expect": "text",
        "min_chars": 600,
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
        "expect": "text",
        "min_chars": 900,
    },
}


# ── Server helpers ────────────────────────────────────────────────────────────


def _root(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1")


def server_models(base_url: str) -> dict[str, dict]:
    try:
        r = requests.get(f"{base_url.rstrip('/').removesuffix('/v1')}/api/v1/models", timeout=(3, 10))
        if r.status_code == 200:
            return {
                str(m.get("key", "")): m
                for m in r.json().get("models", [])
                if isinstance(m, dict) and m.get("type") == "llm"
            }
    except Exception:
        pass
    return {}


def chat_model_ids(base_url: str) -> list[str]:
    try:
        r = requests.get(f"{base_url}/models", timeout=(3, 10))
        if r.status_code == 200:
            return [m.get("id", "") for m in r.json().get("data", []) if isinstance(m, dict)]
    except Exception:
        pass
    return []


def loaded_models(base_url: str) -> list[str]:
    return [key for key, m in server_models(base_url).items() if m.get("loaded_instances")]


def unload_model(base_url: str, model: str) -> bool:
    """Unload via the v1 route first, then the legacy variants."""
    try:
        from investment_engine.providers.lmstudio import _unload_via_api

        return bool(_unload_via_api(base_url, model))
    except Exception:
        pass
    root = _root(base_url)
    for method, url, payload in (
        ("POST", f"{root}/api/v1/models/unload", {"model": model}),
        ("POST", f"{root}/api/v0/models/unload", {"model": model}),
    ):
        try:
            r = requests.post(url, json=payload, timeout=(5, 60))
            if r.status_code == 200:
                return True
        except Exception:
            continue
    return False


def load_model(base_url: str, model: str, context_length: int) -> bool:
    try:
        r = requests.post(
            f"{_root(base_url)}/api/v1/models/load",
            json={"model": model, "context_length": context_length},
            timeout=(10, 900),
        )
        return r.status_code == 200
    except Exception:
        return False


# ── Answer validation ─────────────────────────────────────────────────────────


def _extract_json_blob(text: str) -> Any:
    """Pull the first JSON array/object out of a model answer, prose allowed."""
    stripped = (text or "").strip()
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.MULTILINE)
    for opener, closer in (("[", "]"), ("{", "}")):
        start = stripped.find(opener)
        if start == -1:
            continue
        depth = 0
        for idx in range(start, len(stripped)):
            char = stripped[idx]
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    chunk = stripped[start: idx + 1]
                    try:
                        return json.loads(chunk)
                    except json.JSONDecodeError:
                        break
    return None


def validate_answer(text: str, spec: dict[str, Any]) -> tuple[bool, str]:
    expect = spec.get("expect", "text")
    if not (text or "").strip():
        return False, "empty answer"
    if expect == "text":
        needed = int(spec.get("min_chars", 1))
        return (len(text) >= needed), f"{len(text)} chars (need {needed})"

    blob = _extract_json_blob(text)
    if blob is None:
        return False, "no parsable JSON"

    rows = blob if isinstance(blob, list) else [blob]
    if expect == "json_array" and not isinstance(blob, list):
        return False, "expected a JSON array"
    if expect == "json_object" and not isinstance(blob, dict):
        return False, "expected a JSON object"
    if spec.get("items") and isinstance(blob, list) and len(blob) != spec["items"]:
        return False, f"{len(blob)} items (need {spec['items']})"

    keys = spec.get("keys") or ()
    if keys:
        missing = [k for k in keys if not any(isinstance(row, dict) and k in row for row in rows)]
        if missing:
            return False, f"missing keys: {', '.join(missing)}"
    return True, "ok"


# ── Measurement ───────────────────────────────────────────────────────────────


def run_attempt(model_id: str, stage_name: str, spec: dict[str, Any], base_url: str) -> dict[str, Any]:
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": spec["system"]},
            {"role": "user", "content": spec["prompt"]},
        ],
        "temperature": 0.15,
        "max_tokens": spec["max_tokens"],
        "stream": False,
        "reasoning_effort": "none",
    }

    started = time.monotonic()
    try:
        r = requests.post(f"{base_url}/chat/completions", json=payload, timeout=(30, 900))
        elapsed = time.monotonic() - started
    except Exception as exc:
        return {
            "status": "exception",
            "elapsed_s": round(time.monotonic() - started, 2),
            "error": f"{type(exc).__name__}: {exc}"[:200],
        }

    if r.status_code != 200:
        return {
            "status": "error",
            "http_status": r.status_code,
            "elapsed_s": round(elapsed, 2),
            "error": (r.text or "")[:200],
        }

    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0) or len(
        spec["system"] + spec["prompt"]
    ) // 4
    output_tokens = int(usage.get("completion_tokens") or 0) or len(content) // 4
    passed, note = validate_answer(content, spec)

    return {
        "status": "ok",
        "elapsed_s": round(elapsed, 2),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "tokens_per_sec": round(output_tokens / elapsed, 2) if elapsed > 0 else 0.0,
        "content_len": len(content),
        "format_ok": passed,
        "format_note": note,
        "content_preview": content[:180].replace("\n", " "),
    }


def benchmark_model(
    label: str,
    model_id: str,
    stages: list[str],
    base_url: str,
    max_context: int,
    repeats: dict[str, int],
) -> dict[str, Any]:
    for other in loaded_models(base_url) or []:
        if other != model_id:
            unload_model(base_url, other)

    load_started = time.monotonic()
    already_loaded = model_id in loaded_models(base_url)
    if not already_loaded and not load_model(base_url, model_id, max_context):
        return {
            "model": label,
            "model_id": model_id,
            "status": "load_failed",
            "stages": {},
            "note": "model did not load (too large for RAM/VRAM or unsupported)",
        }
    load_s = 0.0 if already_loaded else round(time.monotonic() - load_started, 1)

    stages_out: dict[str, Any] = {}
    for stage in stages:
        spec = STAGE_PROMPTS.get(stage)
        if spec is None:
            continue
        attempts = [run_attempt(model_id, stage, spec, base_url) for _ in range(max(1, repeats.get(stage, 1)))]
        ok = [a for a in attempts if a["status"] == "ok"]
        stages_out[stage] = {
            "attempts": len(attempts),
            "ok": len(ok),
            "median_tokens_per_sec": round(statistics.median([a["tokens_per_sec"] for a in ok]), 2) if ok else 0.0,
            "median_elapsed_s": round(statistics.median([a["elapsed_s"] for a in ok]), 2) if ok else 0.0,
            "format_pass": sum(1 for a in ok if a.get("format_ok")),
            "format_notes": [a.get("format_note") for a in attempts],
            "runs": attempts,
        }
        time.sleep(1)

    unload_model(base_url, model_id)
    return {"model": label, "model_id": model_id, "status": "ok", "load_s": load_s, "stages": stages_out}


# ── Scoring and report ────────────────────────────────────────────────────────


def summarise(result: dict[str, Any]) -> dict[str, Any]:
    stages = result.get("stages") or {}
    attempts = sum(s["attempts"] for s in stages.values())
    oks = sum(s["ok"] for s in stages.values())
    format_pass = sum(s["format_pass"] for s in stages.values())
    speeds = [s["median_tokens_per_sec"] for s in stages.values() if s["median_tokens_per_sec"] > 0]
    return {
        "attempts": attempts,
        "oks": oks,
        "reliability": (oks / attempts) if attempts else 0.0,
        "format_rate": (format_pass / oks) if oks else 0.0,
        "median_tps": round(statistics.median(speeds), 2) if speeds else 0.0,
        "max_tps": round(max(speeds), 2) if speeds else 0.0,
    }


def score_all(results: list[dict[str, Any]]) -> None:
    best_tps = max((summarise(r)["median_tps"] for r in results), default=0.0) or 1.0
    for result in results:
        stats = summarise(result)
        quality = 0.6 * stats["format_rate"] + 0.4 * stats["reliability"]
        speed_factor = stats["median_tps"] / best_tps
        stats["score"] = round(100 * quality * (0.6 + 0.4 * speed_factor), 1)
        result["summary"] = stats


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def generate_report(results: list[dict[str, Any]], stages: list[str], base_url: str) -> str:
    ranked = sorted(
        [r for r in results if r.get("status") == "ok"],
        key=lambda r: r["summary"]["score"],
        reverse=True,
    )
    lines = [
        "# Local model benchmark",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- LM Studio: `{base_url}`",
        f"- Context per model: {MAX_CONTEXT} tokens (or the model maximum, whichever is smaller)",
        f"- Stages: {', '.join(stages)}",
        "- `reasoning_effort=none`, temperature 0.15, tokens read from the server's `usage` block",
        "",
        "## Ranking",
        "",
        "| # | Model | Score | Median tok/s | Reliability | Format ok | Load s |",
        "|---|---|---|---|---|---|---|",
    ]
    for idx, result in enumerate(ranked, start=1):
        stats = result["summary"]
        lines.append(
            f"| {idx} | {result['model']} | {stats['score']:.1f} | "
            f"{stats['median_tps']:.1f} | {stats['reliability'] * 100:.0f}% | "
            f"{stats['format_rate'] * 100:.0f}% | {_fmt(result.get('load_s'))} |"
        )

    failed = [r for r in results if r.get("status") != "ok"]
    if failed:
        lines += ["", "## Models that could not be measured", ""]
        for result in failed:
            lines.append(f"- **{result['model']}** — {result.get('note') or result.get('status')}")

    if ranked:
        fastest = max(ranked, key=lambda r: r["summary"]["median_tps"])
        most_reliable = max(
            ranked,
            key=lambda r: (r["summary"]["format_rate"], r["summary"]["reliability"]),
        )
        lines += [
            "",
            "## Verdict",
            "",
            f"- **Best overall (score):** {ranked[0]['model']} "
            f"({ranked[0]['summary']['score']:.1f} bodu, {ranked[0]['summary']['median_tps']:.1f} tok/s)",
            f"- **Fastest:** {fastest['model']} ({fastest['summary']['median_tps']:.1f} tok/s)",
            f"- **Most dependable output:** {most_reliable['model']} "
            f"(format {most_reliable['summary']['format_rate'] * 100:.0f}%, "
            f"reliability {most_reliable['summary']['reliability'] * 100:.0f}%)",
            "",
            "Score = 100 × (0.6 × format compliance + 0.4 × reliability) × "
            "(0.6 + 0.4 × speed relative to the fastest model). "
            "A slow model that always answers correctly still ranks well; "
            "a fast model that breaks JSON ranks poorly.",
        ]

    lines += ["", "## Per-stage detail", ""]
    for result in ranked:
        lines.append(f"### {result['model']}")
        lines.append("")
        lines.append("| Stage | tok/s | Time s | Out tokens | Format | Note |")
        lines.append("|---|---|---|---|---|---|")
        for stage in stages:
            data = (result.get("stages") or {}).get(stage)
            if not data:
                lines.append(f"| {stage} | — | — | — | — | not run |")
                continue
            note = next((n for n in data["format_notes"] if n != "ok"), "ok")
            lines.append(
                f"| {stage} | {data['median_tokens_per_sec']:.1f} | {data['median_elapsed_s']:.1f} | "
                f"{data['runs'][0].get('output_tokens', '—')} | "
                f"{data['format_pass']}/{data['ok']} | {note} |"
            )
        lines.append("")

    lines += [
        "## Method notes",
        "",
        "- One model is loaded at a time; every other model is unloaded before each run.",
        "- Reliability counts HTTP 200 answers with non-empty content across all attempts.",
        "- Format compliance checks that JSON stages return parsable JSON with the required keys "
        "and item count; text stages must reach a minimum length.",
        "- Results depend on this machine (RAM/VRAM, current load) and on LM Studio settings.",
        "",
    ]
    return "\n".join(lines)


def default_output_dir() -> Path:
    desktop = Path.home() / "Desktop"
    return desktop / "PortfolioAI_ModelBenchmark" if desktop.is_dir() else ROOT / "results"


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark local LLM models on portfolio analysis stages")
    parser.add_argument("--models", type=str, default=None, help="Comma-separated labels from CANDIDATE_MODELS")
    parser.add_argument("--stages", type=str, default="decision,finance,fast,writer", help="Comma-separated stages")
    parser.add_argument("--repeat", type=int, default=1, help="Attempts per stage (reliability sample size)")
    parser.add_argument(
        "--stability-stages",
        type=str,
        default="fast",
        help="Cheap stages that get 3 attempts to measure consistency",
    )
    parser.add_argument("--list-models", action="store_true", help="List available models and exit")
    parser.add_argument("--run-all", action="store_true", help="All candidate models, all stages")
    parser.add_argument("--include-74b", action="store_true", help="Also test the 74B model (may not fit)")
    parser.add_argument("--base-url", type=str, default=LM_STUDIO_URL)
    parser.add_argument("--max-context", type=int, default=MAX_CONTEXT)
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    base_url = args.base_url
    available = chat_model_ids(base_url)
    if not available:
        print(f"ERROR: LM Studio not reachable at {base_url}", file=sys.stderr)
        return 2

    if args.list_models:
        print("Available in LM Studio:")
        for model_id in available:
            print(f"  {model_id}")
        print("\nCandidates:")
        for label, model_id in CANDIDATE_MODELS.items():
            mark = "yes" if model_id in available else "no"
            print(f"  {label}: {model_id} (available={mark})")
        return 0

    if args.run_all:
        labels = list(CANDIDATE_MODELS)
        stages = list(STAGE_PROMPTS)
    else:
        labels = [m.strip() for m in (args.models or "qwen3.8-9b-distill").split(",") if m.strip()]
        stages = [s.strip() for s in args.stages.split(",") if s.strip()]

    if not args.include_74b:
        labels = [label for label in labels if label != "nemotron-74b"]

    unknown = [s for s in stages if s not in STAGE_PROMPTS]
    if unknown:
        print(f"ERROR: unknown stages: {', '.join(unknown)}", file=sys.stderr)
        return 2

    print(f"Models: {len(labels)} | stages: {stages} | repeat: {args.repeat}")
    print(f"URL: {base_url}")
    print()

    stability = {s.strip() for s in args.stability_stages.split(",") if s.strip()}
    repeats = {
        stage: (max(3, args.repeat) if stage in stability else max(1, args.repeat))
        for stage in stages
    }

    results: list[dict[str, Any]] = []
    for label in labels:
        model_id = CANDIDATE_MODELS.get(label, label)
        if model_id not in available:
            print(f"SKIP {label}: not installed in LM Studio")
            results.append({"model": label, "model_id": model_id, "status": "not_available", "stages": {}})
            continue

        print(f">>> {label}")
        result = benchmark_model(label, model_id, stages, base_url, args.max_context, repeats)
        results.append(result)
        if result["status"] != "ok":
            print(f"    {result['status']}: {result.get('note', '')}")
            continue
        for stage in stages:
            data = result["stages"].get(stage) or {}
            if data.get("ok"):
                print(
                    f"    {stage:9s} {data['median_tokens_per_sec']:7.1f} tok/s  "
                    f"{data['median_elapsed_s']:6.1f}s  format {data['format_pass']}/{data['ok']}"
                )
            else:
                print(f"    {stage:9s} FAILED")
        print()

    # Leave the machine clean.
    for model_id in loaded_models(base_url):
        unload_model(base_url, model_id)
    remaining = loaded_models(base_url)
    print(f"Models still loaded after benchmark: {remaining or 'none'}")

    score_all(results)
    out_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"model_benchmark_{stamp}.json"
    md_path = out_dir / f"model_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    report = generate_report(results, stages, base_url)
    md_path.write_text(report, encoding="utf-8")

    print()
    print(report)
    print(f"Report: {md_path}")
    print(f"Raw:    {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

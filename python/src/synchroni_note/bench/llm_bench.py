"""ローカルLLM（Ollama）の議事録要約タスクにおける生成速度を計測する。

使い方（python/ 配下で実行。事前に Ollama 起動とモデル pull が必要）:

    uv run python -m synchroni_note.bench.llm_bench --models qwen3:8b qwen3:14b
    uv run python -m synchroni_note.bench.llm_bench --models qwen3:8b --out ../doc/DD/DD-002/結果.md

指標:
- gen_tps    : 生成トークン/秒 = eval_count / eval_duration
- prompt_tps : プロンプト処理トークン/秒 = prompt_eval_count / prompt_eval_duration
- ttft_s     : 最初のトークンまでの体感遅延（ストリーミングで測定）
- total_s    : 1回あたりの総処理時間
"""

from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import ollama

SUMMARY_INSTRUCTION = (
    "あなたは会議の議事録作成アシスタントです。"
    "以下の書き起こしテキストから、日本語の議事録をMarkdownで作成してください。"
    "「## 要約」「## 決定事項」「## TODO」の3セクションに箇条書きでまとめ、"
    "言い淀み（えーっと、あの 等）は除去してください。\n\n"
    "--- 書き起こし ---\n"
)


def tokens_per_second(count: int, duration_ns: int) -> float:
    """トークン数とナノ秒の処理時間から tok/s を算出する（0除算ガード）。"""
    if duration_ns <= 0 or count <= 0:
        return 0.0
    return count / (duration_ns / 1e9)


def build_prompt(transcript: str) -> str:
    """書き起こしテキストから要約用プロンプトを組み立てる。"""
    return SUMMARY_INSTRUCTION + transcript


@dataclass
class BenchResult:
    """1回（または平均）の計測結果。"""

    model: str
    gen_tps: float
    prompt_tps: float
    ttft_s: float
    total_s: float
    eval_count: int
    prompt_eval_count: int


def average(results: list[BenchResult]) -> BenchResult:
    """複数回の計測結果を平均する。"""
    if not results:
        raise ValueError("results が空です")
    return BenchResult(
        model=results[0].model,
        gen_tps=statistics.mean(r.gen_tps for r in results),
        prompt_tps=statistics.mean(r.prompt_tps for r in results),
        ttft_s=statistics.mean(r.ttft_s for r in results),
        total_s=statistics.mean(r.total_s for r in results),
        eval_count=round(statistics.mean(r.eval_count for r in results)),
        prompt_eval_count=round(statistics.mean(r.prompt_eval_count for r in results)),
    )


def run_once(model: str, prompt: str, *, think: bool = False) -> BenchResult:
    """1回だけ生成を実行し、メトリクスを返す。"""
    start = time.perf_counter()
    ttft: float | None = None
    final = None
    for chunk in ollama.generate(model=model, prompt=prompt, stream=True, think=think):
        if ttft is None and chunk.response:
            ttft = time.perf_counter() - start
        if chunk.done:
            final = chunk
    total_s = time.perf_counter() - start

    eval_count = (final.eval_count if final else 0) or 0
    eval_duration = (final.eval_duration if final else 0) or 0
    prompt_eval_count = (final.prompt_eval_count if final else 0) or 0
    prompt_eval_duration = (final.prompt_eval_duration if final else 0) or 0

    return BenchResult(
        model=model,
        gen_tps=tokens_per_second(eval_count, eval_duration),
        prompt_tps=tokens_per_second(prompt_eval_count, prompt_eval_duration),
        ttft_s=ttft if ttft is not None else total_s,
        total_s=total_s,
        eval_count=eval_count,
        prompt_eval_count=prompt_eval_count,
    )


def run_benchmark(
    model: str,
    prompt: str,
    *,
    warmup: int = 1,
    runs: int = 3,
    think: bool = False,
) -> BenchResult:
    """ウォームアップ後に runs 回計測し、平均を返す。"""
    for _ in range(warmup):
        run_once(model, prompt, think=think)
    results = [run_once(model, prompt, think=think) for _ in range(runs)]
    return average(results)


def format_markdown(results: list[BenchResult], *, think: bool) -> str:
    """計測結果を Markdown 表に整形する。"""
    lines = [
        f"# DD-002 LLM生成速度ベンチ結果（thinking={'ON' if think else 'OFF'}）",
        "",
        "| モデル | 生成tok/s | 入力tok/s | TTFT(s) | 総時間(s) | 生成tok | 入力tok |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.model} | {r.gen_tps:.1f} | {r.prompt_tps:.1f} | {r.ttft_s:.2f} "
            f"| {r.total_s:.2f} | {r.eval_count} | {r.prompt_eval_count} |"
        )
    return "\n".join(lines) + "\n"


def _default_transcript_path() -> Path:
    return Path(__file__).parent / "sample_transcript.txt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ollama LLM 生成速度ベンチ")
    parser.add_argument("--models", nargs="+", default=["qwen3:8b"], help="計測対象モデル")
    parser.add_argument("--runs", type=int, default=3, help="計測回数")
    parser.add_argument("--warmup", type=int, default=1, help="ウォームアップ回数")
    parser.add_argument("--think", action="store_true", help="思考モードをONにする")
    parser.add_argument("--transcript", type=Path, default=None, help="書き起こしテキストのパス")
    parser.add_argument("--out", type=Path, default=None, help="結果Markdownの出力先")
    args = parser.parse_args(argv)

    transcript_path = args.transcript or _default_transcript_path()
    transcript = transcript_path.read_text(encoding="utf-8")
    prompt = build_prompt(transcript)

    results: list[BenchResult] = []
    for model in args.models:
        print(f"[計測中] {model} (warmup={args.warmup}, runs={args.runs}, think={args.think}) ...")
        result = run_benchmark(model, prompt, warmup=args.warmup, runs=args.runs, think=args.think)
        results.append(result)
        print(
            f"  -> 生成 {result.gen_tps:.1f} tok/s | プロンプト {result.prompt_tps:.1f} tok/s "
            f"| TTFT {result.ttft_s:.2f}s | 総 {result.total_s:.2f}s"
        )

    markdown = format_markdown(results, think=args.think)
    print()
    print(markdown)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        print(f"結果を書き出しました: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

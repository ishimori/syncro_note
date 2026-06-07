"""製品エンジン whisper.cpp（pywhispercpp）の RTF/CER を計測し faster-whisper と比較する（DD-005）。

whisper.cpp は製品期の `whisper-rs` と同じ C++ コア。同一音声・同条件で faster-whisper と
RTF を突き合わせ、**製品エンジン基準**のリアルタイム可否を確定するためのベンチ。
RTF/CER/チャンク分割の純関数は `stt_bench` から再利用する。

使い方（python/ 配下。初回は ggml モデルを自動DL）:

    uv run python -m synchroni_note.bench.whispercpp_bench --audio audio/sample01.wav \
        --reference audio/script01.txt --models base medium --threads 4 8 \
        --modes batch streaming --chunk-seconds 10 --out ../doc/DD/DD-005/結果.md
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from synchroni_note.bench.stt_bench import (
    SAMPLE_RATE,
    SttResult,
    _load_audio,
    character_error_rate,
    chunk_samples,
    real_time_factor,
)


def _load_model(model: str, threads: int):
    """pywhispercpp の Model をロードする（ggml-{model}.bin を自動DL）。"""
    from pywhispercpp.model import Model

    return Model(model, n_threads=threads, print_realtime=False, print_progress=False)


def _transcribe(model, audio) -> str:
    """音声配列(float32/16k)を whisper.cpp で文字起こしし、確定テキストを連結する。"""
    segments = model.transcribe(audio, language="ja")
    return "".join(seg.text for seg in segments)


def run_condition(
    model_name: str,
    threads: int,
    audio,
    *,
    mode: str,
    chunk_seconds: float,
    reference: str | None,
    wm=None,
) -> SttResult:
    """1条件を計測する。mode='batch' は全体一括、'streaming' はチャンク逐次。"""
    wm = wm or _load_model(model_name, threads)
    audio_s = len(audio) / SAMPLE_RATE
    if mode == "streaming":
        chunk_len = int(chunk_seconds * SAMPLE_RATE)
        spans = chunk_samples(len(audio), chunk_len)
        start = time.perf_counter()
        parts = [_transcribe(wm, audio[s:e]) for s, e in spans]
        process_s = time.perf_counter() - start
        hypothesis = "".join(parts)
        chunk_s = float(chunk_seconds)
    else:
        start = time.perf_counter()
        hypothesis = _transcribe(wm, audio)
        process_s = time.perf_counter() - start
        chunk_s = audio_s
    cer = character_error_rate(reference, hypothesis) if reference is not None else None
    return SttResult(
        model=model_name,
        threads=threads,
        mode=mode,
        chunk_s=chunk_s,
        audio_s=audio_s,
        process_s=process_s,
        rtf=real_time_factor(process_s, audio_s),
        cer=cer,
        hypothesis=hypothesis,
    )


def format_markdown(results: list[SttResult]) -> str:
    """計測結果を Markdown 表に整形する。"""
    lines = [
        "# DD-005 whisper.cpp（pywhispercpp）ベンチ結果（CPU）",
        "",
        "| モデル | threads | モード | chunk(s) | 音声(s) | 処理(s) | RTF | CER |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        cer = "—" if r.cer is None else f"{r.cer:.3f}"
        lines.append(
            f"| {r.model} | {r.threads} | {r.mode} | {r.chunk_s:.1f} | {r.audio_s:.1f} "
            f"| {r.process_s:.2f} | {r.rtf:.3f} | {cer} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="whisper.cpp(pywhispercpp) RTF/CERベンチ")
    parser.add_argument("--audio", type=Path, required=True, help="計測対象の音声ファイル")
    parser.add_argument("--reference", type=Path, default=None, help="CER用の正解書き起こし")
    parser.add_argument("--models", nargs="+", default=["base"], help="計測対象モデル")
    parser.add_argument("--threads", nargs="+", type=int, default=[4], help="n_threads スイープ")
    parser.add_argument("--modes", nargs="+", default=["batch"], choices=["batch", "streaming"])
    parser.add_argument("--chunk-seconds", type=float, default=10.0, help="streaming分割長(秒)")
    parser.add_argument("--out", type=Path, default=None, help="結果Markdownの出力先")
    args = parser.parse_args(argv)

    audio = _load_audio(args.audio)
    reference = args.reference.read_text(encoding="utf-8") if args.reference else None

    results: list[SttResult] = []
    for model in args.models:
        for threads in args.threads:
            wm = _load_model(model, threads)
            _transcribe(wm, audio[: SAMPLE_RATE * 2])  # ウォームアップ
            for mode in args.modes:
                print(f"[計測中] whisper.cpp {model} threads={threads} mode={mode} ...")
                r = run_condition(
                    model, threads, audio,
                    mode=mode, chunk_seconds=args.chunk_seconds,
                    reference=reference, wm=wm,
                )
                results.append(r)
                cer = "—" if r.cer is None else f"{r.cer:.3f}"
                print(f"  -> RTF {r.rtf:.3f} | 処理 {r.process_s:.2f}s | CER {cer}")

    markdown = format_markdown(results)
    print()
    print(markdown)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        print(f"結果を書き出しました: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

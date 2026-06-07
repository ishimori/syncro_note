"""逐次STT＋指標実測（DD-010 P2-2）。

録音クリップ（または実マイク）を VAD チャンクに区切り、faster-whisper へ**逐次**かけて
確定テキストを順に出す。評価指標を実測する:

- 体感遅延   : 発話が終わってから文字が出るまでの秒数（直列STTの待ち＝バックログも込み）
- 取りこぼし : 区切りで文字起こしが変わる度合い（streaming連結 vs batch の CER差）
- RTF        : 逐次STTの処理秒 / 音声秒（<1 でリアルタイム可）

再利用: `bench.stt_bench`（モデルロード/文字起こし/CER/RTF）, `realtime.capture`（VAD チャンク化）。
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

from synchroni_note.bench.stt_bench import (
    _load_model,
    _transcribe,
    character_error_rate,
    real_time_factor,
)
from synchroni_note.realtime.capture import SAMPLE_RATE, VadChunker, capture_mic, feed_samples


def _decode(path: Path):
    """音声ファイルを 16kHz モノラル float32 へデコードする。"""
    from faster_whisper.audio import decode_audio

    return decode_audio(str(path), sampling_rate=SAMPLE_RATE)


@dataclass
class StreamMetrics:
    audio_s: float
    n_chunks: int
    chunk_min_s: float
    chunk_max_s: float
    stt_total_s: float
    rtf: float
    latency_avg_s: float
    latency_max_s: float
    cer_stream_vs_batch: float
    cer_stream_vs_ref: float | None
    cer_batch_vs_ref: float | None


def measure_file(
    audio,
    *,
    model: str = "medium",
    threads: int = 4,
    max_seg_s: float = 10.0,
    reference: str | None = None,
) -> tuple[StreamMetrics, str]:
    """クリップを逐次STTし、指標と streaming 連結テキストを返す。"""
    wm = _load_model(model, threads)
    _transcribe(wm, audio[: SAMPLE_RATE * 2])  # ウォームアップ

    audio_s = len(audio) / SAMPLE_RATE

    # batch（全体一括）を基準に取る
    t = time.perf_counter()
    batch_hyp = _transcribe(wm, audio)
    _ = time.perf_counter() - t

    # streaming（VAD チャンク逐次）
    chunker = VadChunker(max_seg_s=max_seg_s)
    chunks = feed_samples(audio, chunker)

    parts: list[str] = []
    proc_ms: list[float] = []
    for ch in chunks:
        t = time.perf_counter()
        parts.append(_transcribe(wm, ch.samples))
        proc_ms.append((time.perf_counter() - t) * 1000)
    streaming_hyp = "".join(parts)
    stt_total_s = sum(proc_ms) / 1000

    # 体感遅延: 直列STT（前のチャンク処理を待つ）をシミュレート
    latencies_ms: list[float] = []
    prev_finish = 0.0
    for ch, p in zip(chunks, proc_ms):
        avail = float(ch.t_end_ms)  # 発話が終わりチャンクが確定する時刻
        start = max(avail, prev_finish)  # STT は直列
        finish = start + p
        latencies_ms.append(finish - avail)
        prev_finish = finish

    durs = [c.duration_s for c in chunks] or [0.0]
    lat = latencies_ms or [0.0]
    metrics = StreamMetrics(
        audio_s=audio_s,
        n_chunks=len(chunks),
        chunk_min_s=min(durs),
        chunk_max_s=max(durs),
        stt_total_s=stt_total_s,
        rtf=real_time_factor(stt_total_s, audio_s),
        latency_avg_s=sum(lat) / len(lat) / 1000,
        latency_max_s=max(lat) / 1000,
        cer_stream_vs_batch=character_error_rate(batch_hyp, streaming_hyp),
        cer_stream_vs_ref=character_error_rate(reference, streaming_hyp) if reference else None,
        cer_batch_vs_ref=character_error_rate(reference, batch_hyp) if reference else None,
    )
    return metrics, streaming_hyp


def format_report(m: StreamMetrics, *, model: str, threads: int, max_seg_s: float) -> str:
    """測定結果を平易な日本語の Markdown にする。"""

    def pct(x: float | None) -> str:
        return "—" if x is None else f"{x * 100:.1f}%"

    rt = "間に合う（処理が音声より速い）" if m.rtf < 1 else "間に合わない（要調整）"
    miss = "—" if m.cer_batch_vs_ref is None or m.cer_stream_vs_ref is None \
        else pct(m.cer_stream_vs_ref - m.cer_batch_vs_ref)
    return (
        f"# DD-010 結果: 逐次STT 実測（{model}/{threads}スレッド/最大{max_seg_s:.0f}秒）\n\n"
        f"音源 {m.audio_s:.0f}秒 を {m.n_chunks} チャンク"
        f"（{m.chunk_min_s:.1f}〜{m.chunk_max_s:.1f}秒）に区切って逐次文字起こし。\n\n"
        "| 指標 | 値 | 意味 |\n"
        "|---|---|---|\n"
        f"| 処理の速さ(RTF) | {m.rtf:.3f} | {rt} |\n"
        f"| 体感遅延(平均) | {m.latency_avg_s:.1f}秒 | 話し終えてから文字が出るまで（平均） |\n"
        f"| 体感遅延(最大) | {m.latency_max_s:.1f}秒 | 同（最も遅いとき） |\n"
        f"| 取りこぼし | {pct(m.cer_stream_vs_batch)} | 一括時からの変化（小さいほど良い） |\n"
        f"| 文字誤り(逐次) | {pct(m.cer_stream_vs_ref)} | 台本との誤り（用語含む） |\n"
        f"| 文字誤り(一括) | {pct(m.cer_batch_vs_ref)} | 参考: 全体一括時の誤り |\n"
        f"| └ 区切りの上乗せ | {miss} | 逐次−一括（区切り由来の悪化分） |\n\n"
        f"逐次STTの合計処理時間 {m.stt_total_s:.1f}秒（音声 {m.audio_s:.0f}秒）。\n"
    )


def _run_mic(model: str, threads: int, max_seg_s: float) -> int:
    """実マイクで逐次STT（確定テキストを順に表示）。Ctrl+C で終了。"""
    wm = _load_model(model, threads)

    def sink(ch) -> None:  # noqa: ANN001
        text = _transcribe(wm, ch.samples).strip()
        print(f"[{ch.t_start_ms / 1000:6.1f}s] {text}", flush=True)

    try:
        capture_mic(VadChunker(max_seg_s=max_seg_s), sink)
    except KeyboardInterrupt:
        print("\n終了しました。", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="逐次STT 実測（DD-010 P2-2）")
    parser.add_argument("--audio", type=Path, default=None, help="計測クリップ（無指定でマイク）")
    parser.add_argument("--reference", type=Path, default=None, help="CER用の台本テキスト")
    parser.add_argument("--model", default="medium", help="faster-whisper モデル")
    parser.add_argument("--threads", type=int, default=4, help="cpu_threads")
    parser.add_argument("--max-seg", type=float, default=10.0, help="チャンク最大秒（8〜12目安）")
    parser.add_argument("--out", type=Path, default=None, help="結果Markdownの出力先")
    args = parser.parse_args(argv)

    if args.audio is None:
        return _run_mic(args.model, args.threads, args.max_seg)

    audio = _decode(args.audio)
    reference = args.reference.read_text(encoding="utf-8").strip() if args.reference else None
    print(f"[計測中] {args.audio.name} / {args.model} / {args.threads}スレッド ...", flush=True)
    metrics, _hyp = measure_file(
        audio, model=args.model, threads=args.threads, max_seg_s=args.max_seg, reference=reference
    )
    report = format_report(metrics, model=args.model, threads=args.threads, max_seg_s=args.max_seg)
    print("\n" + report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"結果を書き出しました: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

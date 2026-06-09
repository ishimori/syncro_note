"""ローカルSTT（faster-whisper）の日本語会議音声に対する速度(RTF)・精度(CER)を計測する。

評価期方針（開発ロードマップ §7）に従い faster-whisper を使用する。製品期は whisper.cpp
(whisper-rs) でありRTFは異なる（一般に faster-whisper の方が速い＝本ベンチは楽観側）。
本ベンチは「方向性と可否ゲート（LLM併走下で per-chunk RTF<1）」を得るのが目的。

使い方（python/ 配下で実行。初回は faster-whisper がモデルを自動DL）:

    uv run python -m synchroni_note.bench.stt_bench --audio path/to.wav --models tiny base \
        --threads 4 8 --modes streaming batch --reference path/to.txt --out ../doc/DD/DD-003/結果.md

指標:
- rtf       : Real-Time Factor = 処理秒 / 音声秒（<1 でリアルタイム可）
- cer       : Character Error Rate = 編集距離 / 参照文字数（reference 指定時のみ）
- chunk_s   : streaming時の分割長（batch時は音声全体）
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path


def real_time_factor(process_s: float, audio_s: float) -> float:
    """処理時間と音声長から RTF を算出する（0除算ガード）。"""
    if audio_s <= 0:
        return 0.0
    return process_s / audio_s


def _edit_distance(ref: str, hyp: str) -> int:
    """文字単位のレーベンシュタイン距離（置換・挿入・削除を各コスト1）。"""
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, start=1):
        cur = [i]
        for j, hc in enumerate(hyp, start=1):
            cost = 0 if rc == hc else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


_PUNCT = "、。，．・…！？!?「」『』（）()【】〔〕［］[]｛｝{}　〜~ー－-：:；;\"'"


def _normalize(text: str) -> str:
    """日本語CER用の軽い正規化（空白・主要な句読点/記号を除去）。

    表記の細部ではなく音認誤りに集中するため、空白と句読点・括弧類を落とす。
    日本語ASRのCER評価で一般的な前処理。
    """
    no_space = "".join(text.split())
    return "".join(ch for ch in no_space if ch not in _PUNCT)


def character_error_rate(reference: str, hypothesis: str) -> float:
    """参照と仮説の文字誤り率を算出する（空白正規化・参照0長ガード）。"""
    ref = _normalize(reference)
    if not ref:
        return 0.0
    hyp = _normalize(hypothesis)
    return _edit_distance(ref, hyp) / len(ref)


def chunk_samples(total: int, chunk_len: int) -> list[tuple[int, int]]:
    """総サンプル数を chunk_len ごとの [start, end) 区間リストへ分割する。"""
    if chunk_len <= 0 or total <= 0:
        return [(0, total)] if total > 0 else []
    return [(s, min(s + chunk_len, total)) for s in range(0, total, chunk_len)]


@dataclass
class SttResult:
    """1条件（モデル×スレッド×モード）の計測結果。"""

    model: str
    threads: int
    mode: str
    chunk_s: float
    audio_s: float
    process_s: float
    rtf: float
    cer: float | None
    hypothesis: str
    beam: int = 1


SAMPLE_RATE = 16000


def _load_model(model: str, threads: int):
    """faster-whisper の WhisperModel を CPU/int8 でロードする（実行時import）。"""
    from faster_whisper import WhisperModel

    return WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads)


def _transcribe(whisper_model, audio, beam_size: int = 1, initial_prompt: str | None = None) -> str:
    """音声配列を文字起こしし、確定テキストを連結して返す（generatorを消費）。

    ``beam_size`` を上げると精度↑/速度↓（テレビモードのフルパワー配分・DD-017-3）。既定1。
    ``initial_prompt`` に前チャンクの末尾を渡すと、逐次（チャンク）化で失われる文脈を補える。
    """
    segments, _info = whisper_model.transcribe(
        audio, language="ja", beam_size=beam_size, initial_prompt=initial_prompt
    )
    return "".join(seg.text for seg in segments)


def run_condition(
    model: str,
    threads: int,
    audio,
    *,
    mode: str,
    chunk_seconds: float,
    reference: str | None,
    whisper_model=None,
    beam_size: int = 1,
) -> SttResult:
    """1条件を計測する。mode='batch' は全体一括、'streaming' はチャンク逐次。"""
    wm = whisper_model or _load_model(model, threads)
    audio_s = len(audio) / SAMPLE_RATE

    if mode == "streaming":
        chunk_len = int(chunk_seconds * SAMPLE_RATE)
        spans = chunk_samples(len(audio), chunk_len)
        start = time.perf_counter()
        parts = [_transcribe(wm, audio[s:e], beam_size) for s, e in spans]
        process_s = time.perf_counter() - start
        hypothesis = "".join(parts)
        chunk_s = float(chunk_seconds)
    else:  # batch
        start = time.perf_counter()
        hypothesis = _transcribe(wm, audio, beam_size)
        process_s = time.perf_counter() - start
        chunk_s = audio_s

    cer = character_error_rate(reference, hypothesis) if reference is not None else None
    return SttResult(
        model=model,
        threads=threads,
        mode=mode,
        chunk_s=chunk_s,
        audio_s=audio_s,
        process_s=process_s,
        rtf=real_time_factor(process_s, audio_s),
        cer=cer,
        hypothesis=hypothesis,
        beam=beam_size,
    )


def format_markdown(results: list[SttResult]) -> str:
    """計測結果を Markdown 表に整形する。"""
    lines = [
        "# DD-003 STT実機ベンチ結果（faster-whisper / CPU・int8）",
        "",
        "| モデル | threads | beam | モード | chunk(s) | 音声(s) | 処理(s) | RTF | CER |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        cer = "—" if r.cer is None else f"{r.cer:.3f}"
        lines.append(
            f"| {r.model} | {r.threads} | {r.beam} | {r.mode} | {r.chunk_s:.1f} | {r.audio_s:.1f} "
            f"| {r.process_s:.2f} | {r.rtf:.3f} | {cer} |"
        )
    return "\n".join(lines) + "\n"


def _load_audio(path: Path):
    """音声ファイルを 16kHz モノラル float32 配列へデコードする。"""
    from faster_whisper.audio import decode_audio

    return decode_audio(str(path), sampling_rate=SAMPLE_RATE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="faster-whisper STT 速度/精度ベンチ")
    parser.add_argument("--audio", type=Path, required=True, help="計測対象の音声ファイル")
    parser.add_argument("--reference", type=Path, default=None, help="CER用の正解書き起こし")
    parser.add_argument("--models", nargs="+", default=["base"], help="計測対象モデル")
    parser.add_argument("--threads", nargs="+", type=int, default=[4], help="cpu_threads スイープ")
    parser.add_argument("--beam", nargs="+", type=int, default=[1], help="beam_size(DD-017-3)")
    parser.add_argument("--modes", nargs="+", default=["batch"], choices=["batch", "streaming"])
    parser.add_argument("--chunk-seconds", type=float, default=3.0, help="streaming分割長(秒)")
    parser.add_argument("--out", type=Path, default=None, help="結果Markdownの出力先")
    args = parser.parse_args(argv)

    audio = _load_audio(args.audio)
    reference = args.reference.read_text(encoding="utf-8") if args.reference else None

    results: list[SttResult] = []
    for model in args.models:
        for threads in args.threads:
            wm = _load_model(model, threads)
            _transcribe(wm, audio[: SAMPLE_RATE * 2])  # ウォームアップ（遅延初期化を除外）
            for beam in args.beam:
                for mode in args.modes:
                    print(f"[計測中] {model} threads={threads} beam={beam} mode={mode} ...")
                    r = run_condition(
                        model, threads, audio,
                        mode=mode, chunk_seconds=args.chunk_seconds,
                        reference=reference, whisper_model=wm, beam_size=beam,
                    )
                    results.append(r)
                    cer = "—" if r.cer is None else f"{r.cer:.3f}"
                    print(
                        f"  -> RTF {r.rtf:.3f} | 処理 {r.process_s:.2f}s "
                        f"| 音声 {r.audio_s:.1f}s | CER {cer}"
                    )

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

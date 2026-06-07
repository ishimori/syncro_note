"""バッチMVP CLI: 音声ファイル → 議事録Markdown を1コマンドで生成する。

    uv run synchroni-note transcribe audio/sample01.wav --out minutes.md \
        --title "開発会議" --summary-model gemma4:26b

パイプライン: transcribe(VAD付き) → clean(辞書ケバ取り) → summarize(Ollama)。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from synchroni_note.pipeline.cleaning import clean_text
from synchroni_note.pipeline.summarize import summarize
from synchroni_note.pipeline.transcribe import transcribe, transcript_text

# サンプル音声(sample01)の既知の誤認識を正す用語辞書（実運用は会議ごとの専門用語辞書から渡す）。
DEMO_VOCAB: dict[str, str] = {
    "ハウリ": "Tauri",
    "HOWLY": "Tauri",
    "howly": "Tauri",
    "スキューライト": "SQLite",
    "SQLITE": "SQLite",
    "手羽取り": "ケバ取り",
    "ようやくモデル": "要約モデル",
    "詳細なようやく": "詳細な要約",
}


def render_markdown(
    minutes: str, cleaned: str, *, title: str, stt_model: str, summary_model: str
) -> str:
    """議事録本文＋ケバ取り済み書き起こしを1つのMarkdownに整形する。"""
    heading = title or "議事録"
    return (
        f"# {heading}\n\n"
        f"{minutes}\n\n"
        "---\n\n"
        "## 文字起こし（ケバ取り済み）\n\n"
        f"{cleaned}\n\n"
        f"<!-- STT: faster-whisper {stt_model} (VAD) / 要約: {summary_model} -->\n"
    )


def run(
    audio: Path,
    out: Path,
    *,
    stt_model: str,
    summary_model: str,
    title: str,
    agenda: str,
    vocab: dict[str, str],
) -> None:
    """音声→議事録Markdown のパイプラインを実行し out に書き出す。"""
    print(f"[1/3] 文字起こし(VAD付き, {stt_model}) ...", flush=True)
    t0 = time.perf_counter()
    segments = transcribe(audio, model_size=stt_model)
    raw = transcript_text(segments)
    print(f"      {len(segments)}セグメント / {len(raw)}文字 ({time.perf_counter() - t0:.1f}s)")

    print("[2/3] ケバ取り(辞書＋正規表現) ...", flush=True)
    cleaned = clean_text(raw, vocab=vocab)

    print(f"[3/3] 要約(Ollama, {summary_model}) ...", flush=True)
    t1 = time.perf_counter()
    terms = sorted(set(vocab.values()))
    minutes = summarize(cleaned, model=summary_model, title=title, agenda=agenda, vocab=terms)
    print(f"      議事録生成 完了 ({time.perf_counter() - t1:.1f}s)")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render_markdown(
            minutes, cleaned, title=title, stt_model=stt_model, summary_model=summary_model
        ),
        encoding="utf-8",
    )
    print(f"✓ 議事録を書き出しました: {out}")


def main(argv: list[str] | None = None) -> int:
    # Windows の cp932 端末でも日本語/記号を出力できるよう UTF-8 に再構成する。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="synchroni-note", description="ローカル議事録ツール(MVP)")
    sub = parser.add_subparsers(dest="command", required=True)
    tr = sub.add_parser("transcribe", help="音声ファイルから議事録Markdownを生成")
    tr.add_argument("audio", type=Path, help="入力音声ファイル")
    tr.add_argument("--out", type=Path, default=None, help="出力Markdownパス（既定は音声名から）")
    tr.add_argument("--stt-model", default="medium", help="faster-whisper モデル")
    tr.add_argument("--summary-model", default="gemma4:26b", help="要約 Ollama モデル")
    tr.add_argument("--title", default="", help="会議名")
    tr.add_argument("--agenda", default="", help="アジェンダ")
    args = parser.parse_args(argv)

    out = args.out or args.audio.with_name(f"{args.audio.stem}_議事録.md")
    run(
        args.audio,
        out,
        stt_model=args.stt_model,
        summary_model=args.summary_model,
        title=args.title,
        agenda=args.agenda,
        vocab=DEMO_VOCAB,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

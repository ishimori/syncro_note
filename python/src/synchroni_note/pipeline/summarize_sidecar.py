"""清書サイドカー（DD-012-2）: 確定テキスト(＋メモ＋コンテキスト) を gemma4:26b で議事録
Markdown に清書し、進捗を JSON Lines で標準出力へ逐次出す。

文字起こし中継 ``pipeline/sidecar.py``（DD-011 3-C 管轄）とは**別口**。清書は終了後バッチに
一本化する設計（SSOT）。Rust(Tauri) 側がこの stdout を1行ずつ読み、S-06/S-07 へ中継する。

契約（1行=1JSON, UTF-8, 全行 ``"v":1``。stdout は JSON 専用・ログは stderr へ）:
  summary-meta     : 開始直後に1回。{"model":..,"input_chars":N}
  summary-status   : モデル切替の段階。{"stage":"unloading|unloaded|loading_batch|..","model":..}
  summary-progress : 生成中・差分のみ。{"delta":"追加分テキスト","chars":累計}
  summary-done     : 完了。{"markdown":全文,"input_tokens":..,"output_tokens":..,"eval_s":..}
  error            : 異常時のみ。{"message":..,"where":"summarize"}

使い方（python/ 配下。Ollama 起動とモデル pull が前提）:
  uv run python -m synchroni_note.pipeline.summarize_sidecar transcript.txt --title "開発会議"
  type transcript.txt | uv run python -m synchroni_note.pipeline.summarize_sidecar - --no-switch
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path


def emit(obj: dict[str, object]) -> None:
    """1行=1JSON を stdout へ書き出す（日本語そのまま・各行 flush で逐次性を担保）。"""
    print(json.dumps({"v": 1, **obj}, ensure_ascii=False), flush=True)


def normalize_minutes(text: str) -> str:
    r"""LLM がまれに出力する literal な ``\n``/``\t``（バックスラッシュ＋文字）を実際の
    改行・タブへ直す（Phase 1 DA#2: gemma が議事録に ``\n`` 文字列を混ぜることがある）。

    全文（``summary-done`` の markdown）に対して一括適用するため、delta 境界で
    バックスラッシュと ``n`` が分かれても取りこぼさない。"""
    return text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


def stream_to_events(
    stream: Iterable[tuple[str, dict | None]],
) -> Iterator[dict[str, object]]:
    """``stream_summarize`` の ``(累積text, metrics)`` 列を契約イベント dict 列へ変換する。

    **Ollama 非依存の純粋ジェネレータ**（テストで偽ストリームを流せる）。
    生成中は差分(``delta``)だけを ``summary-progress`` で送り、最後に全文＋トークンを
    ``summary-done`` で送る。
    """
    last = 0
    for acc, metrics in stream:
        if metrics is None:
            delta = acc[last:]
            last = len(acc)
            if delta:  # 空 delta は送らない（done 直前の重複等）
                yield {"type": "summary-progress", "delta": delta, "chars": len(acc)}
        else:
            yield {
                "type": "summary-done",
                "markdown": normalize_minutes(acc),
                "input_tokens": int(metrics.get("input_tokens", 0)),
                "output_tokens": int(metrics.get("output_tokens", 0)),
                "eval_s": round(float(metrics.get("eval_s", 0.0)), 3),
            }


def _read_transcript(source: str) -> str:
    """transcript を読み込む（``-`` なら stdin、それ以外はファイルパス）。"""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    # Windows の cp932 端末でも日本語を出力できるよう UTF-8 に再構成する。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="synchroni-note-summarize-sidecar",
        description="確定テキストを gemma で議事録Markdownに清書し JSON Lines で逐次出力する",
    )
    parser.add_argument("transcript", help="清書元テキストのパス（'-' で標準入力）")
    parser.add_argument("--model", default="gemma4:26b", help="清書(batch) Ollama モデル")
    parser.add_argument("--live-model", default="qwen3:8b", help="退避する live モデル")
    parser.add_argument("--title", default="", help="会議名（プロンプト前提に付与）")
    parser.add_argument("--agenda", default="", help="アジェンダ（プロンプト前提に付与）")
    parser.add_argument(
        "--no-switch",
        action="store_true",
        help="モデル切替をスキップ（既に batch 常駐 or 検証用）",
    )
    args = parser.parse_args(argv)

    try:
        transcript = _read_transcript(args.transcript)
        emit({"type": "summary-meta", "model": args.model, "input_chars": len(transcript)})

        # モデル切替（live退避→ps空確認→batchロード準備）。段階を summary-status で通知。
        if not args.no_switch:
            from synchroni_note.pipeline.model_switch import switch_to_batch

            switch_to_batch(
                args.live_model,
                args.model,
                on_status=lambda stage, model: emit(
                    {"type": "summary-status", "stage": stage, "model": model}
                ),
            )

        # 清書ストリーミング（最初のトークンで batch がロードされる）。
        from synchroni_note.pipeline.summarize import stream_summarize

        stream = stream_summarize(
            transcript, model=args.model, title=args.title, agenda=args.agenda
        )
        for event in stream_to_events(stream):
            emit(event)
    except Exception as e:  # noqa: BLE001  異常は error 行で通知し stderr にも残す（stdoutはJSON専用）
        emit({"type": "error", "message": str(e), "where": "summarize"})
        print(f"[summarize-sidecar] {e!r}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

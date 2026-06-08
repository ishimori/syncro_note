"""カレンダー予定コピペ取込サイドカー（DD-012-13）。

予定テキストを stdin（``-``）またはファイルから受け取り、ローカルLLM(qwen3:8b)で構造化した
draft を **1行のJSON** で stdout に返す。Rust(Tauri)側が同期(ブロッキング)実行して結果1個を拾う
（DD-012-10 の `--extract` と同じブロッキング契約。stdout はJSON専用・ログは stderr）。

契約（最終行・UTF-8）:
  done : {"v":1,"type":"calendar-parse","status":"done","draft":{...}}
  error: {"v":1,"type":"calendar-parse","status":"error","message":".."}

使い方（python/ 配下。Ollama 起動と qwen3:8b pull が前提）:
  type event.txt | uv run python -m synchroni_note.pipeline.calendar_parse_sidecar -
  uv run python -m synchroni_note.pipeline.calendar_parse_sidecar event.txt --model qwen3:8b
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def emit(obj: dict[str, object]) -> None:
    """1行=1JSON を stdout へ（日本語そのまま・flush で即時）。"""
    print(json.dumps({"v": 1, **obj}, ensure_ascii=False), flush=True)


def _read_text(source: str) -> str:
    """予定テキストを読み込む（``-`` なら stdin、それ以外はファイルパス）。"""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    # Windows の cp932 端末でも日本語を扱えるよう UTF-8 に再構成する。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="synchroni-note-calendar-parse-sidecar",
        description="カレンダー予定テキストを qwen で構造化し JSON 1行で返す（DD-012-13）",
    )
    parser.add_argument("source", help="予定テキストのパス（'-' で標準入力）")
    parser.add_argument("--model", default="qwen3:8b", help="抽出に使う Ollama モデル")
    args = parser.parse_args(argv)

    try:
        text = _read_text(args.source)
        if not text.strip():
            raise ValueError("予定テキストが空です")
        # 遅延 import（起動を軽く＆ ollama 未起動時のエラーをこの try で拾う）。
        from synchroni_note.pipeline.calendar_parse import parse_calendar_text

        draft = parse_calendar_text(text, model=args.model)
        emit({"type": "calendar-parse", "status": "done", "draft": draft})
    except Exception as e:  # noqa: BLE001  異常は error 行で返す（stdoutはJSON専用）
        emit({"type": "calendar-parse", "status": "error", "message": str(e)})
        print(f"[calendar-parse-sidecar] {e!r}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

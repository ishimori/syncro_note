"""UI皮（Tauri）への中継口: 文字起こしを JSON Lines で標準出力に逐次出す。

議事録Markdownを作る ``cli.py`` とは目的が違う。こちらは「1行=1メッセージのJSON」を
そのまま流すだけの薄い口で、Rust(Tauri)側がこの stdout を1行ずつ読み、フロントへ
Tauri イベントとして中継する（DD-011 Phase 3-B/3-C）。

契約（1行=1JSON, UTF-8, ``type`` で区別。全行に ``"v":1``）:
  {"v":1,"type":"meta","duration_s":..,"model":"..","language":".."}        # 開始直後に1回
  {"v":1,"type":"segment","seq":0,"text":"..","t_start_ms":..,"t_end_ms":..} # 1件ごと
  {"v":1,"type":"done","count":N,"elapsed_s":..}                            # 全完了で1回
  {"v":1,"type":"error","message":"..","where":".."}                        # 異常時のみ

stdout は JSON 専用に保つ（Rust側パースの汚染防止）。警告・ログ・トレースは stderr へ。
詳細設計: doc/DD/DD-011/Phase3_実装前詳細化.md §3（契約）・§4（本実行口）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def emit(obj: dict[str, object]) -> None:
    """1行=1JSON を stdout へ書き出す。

    ``ensure_ascii=False`` で日本語をそのまま、各行 ``flush`` で逐次性を担保する（溜め込み防止）。
    全行に契約版 ``"v":1`` を付与する。
    """
    print(json.dumps({"v": 1, **obj}, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    # Windows の cp932 端末でも日本語を出力できるよう UTF-8 に再構成する（cli.py と同じ手当て）。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="synchroni-note-sidecar",
        description="文字起こしを JSON Lines で逐次出力する UI 中継口",
    )
    parser.add_argument("audio", type=Path, help="入力音声ファイル(.wav)")
    parser.add_argument("--model", default="medium", help="faster-whisper モデル")
    parser.add_argument("--language", default="ja", help="言語コード")
    args = parser.parse_args(argv)

    try:
        from synchroni_note.pipeline.transcribe import stream_transcribe

        stream = stream_transcribe(args.audio, model_size=args.model, language=args.language)
        # duration_s は文字起こし開始前に判明する（UIの「準備中」解除・進捗の分母に使う）。
        emit(
            {
                "type": "meta",
                "duration_s": round(stream.duration_s, 3),
                "model": args.model,
                "language": args.language,
            }
        )
        t0 = time.perf_counter()
        count = 0
        for seg in stream.segments:  # 既存の逐次ジェネレータをそのまま流す（新規ロジックなし）
            emit(
                {
                    "type": "segment",
                    "seq": count,
                    "text": seg.text,
                    "t_start_ms": seg.t_start_ms,
                    "t_end_ms": seg.t_end_ms,
                }
            )
            count += 1
        emit({"type": "done", "count": count, "elapsed_s": round(time.perf_counter() - t0, 3)})
    except Exception as e:  # noqa: BLE001  異常は error 行で通知し stderr にも残す（stdoutはJSON専用）
        emit({"type": "error", "message": str(e), "where": "transcribe"})
        print(f"[sidecar] {e!r}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

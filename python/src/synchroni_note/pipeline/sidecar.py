"""UI皮（Tauri）への中継口: 文字起こしを JSON Lines で標準出力に逐次出す。

議事録Markdownを作る ``cli.py`` とは目的が違う。こちらは「1行=1メッセージのJSON」を
そのまま流すだけの薄い口で、Rust(Tauri)側がこの stdout を1行ずつ読み、フロントへ
Tauri イベントとして中継する（DD-011 Phase 3-B/3-C, DD-012-1）。

入力は3モード（いずれも同じ JSON Lines 契約で出力）:
  - ファイル（positional ``audio``）: 既存の一括ストリーム（DD-011 3-C）。``stream_transcribe``。
  - ``--mic``: 実マイクからライブ収音（DD-010 realtime 経路）。stdin から ``pause``/``resume``/
    ``stop`` を1行ずつ受けて制御する（stdin が閉じても停止）。
  - ``--simulate PATH``: ファイルを mic 代替で realtime 経路へ流す（実マイク不要の確定的テスト）。

契約（1行=1JSON, UTF-8, ``type`` で区別。全行に ``"v":1``）:
  {"v":1,"type":"meta","duration_s":..,"model":"..","language":".."}  # 開始時1回(micはmode:mic)
  {"v":1,"type":"segment","seq":0,"text":"..","t_start_ms":..,"t_end_ms":..}  # 1件ごと
  {"v":1,"type":"done","count":N,"elapsed_s":..}  # 全完了/停止で1回
  {"v":1,"type":"error","message":"..","where":".."}  # 異常時のみ

stdout は JSON 専用に保つ（Rust側パースの汚染防止）。警告・ログ・トレースは stderr へ。
詳細設計: doc/DD/DD-011/Phase3_実装前詳細化.md §3（契約）・§4（本実行口）/ doc/DD/DD-012-1_*.md。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path


def emit(obj: dict[str, object]) -> None:
    """1行=1JSON を stdout へ書き出す。

    ``ensure_ascii=False`` で日本語をそのまま、各行 ``flush`` で逐次性を担保する（溜め込み防止）。
    全行に契約版 ``"v":1`` を付与する。
    """
    print(json.dumps({"v": 1, **obj}, ensure_ascii=False), flush=True)


def _run_file(args: argparse.Namespace) -> int:
    """ファイル一括ストリーム（DD-011 3-C）。``stream_transcribe`` の逐次出力を流す。"""
    from synchroni_note.pipeline.transcribe import stream_transcribe

    stream = stream_transcribe(
        args.audio, model_size=args.model, threads=args.threads, language=args.language
    )
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
    return 0


def _start_stdin_control(stop_event: threading.Event, paused: threading.Event) -> None:
    """stdin を1行ずつ読み、``pause``/``resume``/``stop`` を制御に反映する（mic 用）。

    ``stop`` 行、または stdin の EOF（Rust 側がパイプを閉じる）で停止する。daemon スレッド。
    """

    def _loop() -> None:
        for line in sys.stdin:
            cmd = line.strip().lower()
            if cmd == "pause":
                paused.set()
            elif cmd == "resume":
                paused.clear()
            elif cmd == "stop":
                break
        stop_event.set()  # 明示 stop または EOF（stdin クローズ）で停止

    threading.Thread(target=_loop, daemon=True, name="stdin-control").start()


def _run_realtime(args: argparse.Namespace) -> int:
    """realtime 経路（DD-010）を JSON Lines で流す。``--mic`` か ``--simulate`` で起動。"""
    from synchroni_note.bench.stt_bench import _load_model, _transcribe
    from synchroni_note.realtime.capture import (
        SAMPLE_RATE,
        VadChunker,
        capture_mic,
        feed_samples,
    )

    try:
        wm = _load_model(args.model, args.threads)
    except Exception as e:  # noqa: BLE001
        emit({"type": "error", "message": f"モデル読込失敗: {e}", "where": "load"})
        print(f"[sidecar] {e!r}", file=sys.stderr, flush=True)
        return 1

    t0 = time.perf_counter()
    count = 0

    def sink(ch) -> None:  # noqa: ANN001  Chunk（capture.Chunk）
        nonlocal count
        text = _transcribe(wm, ch.samples).strip()
        emit(
            {
                "type": "segment",
                "seq": ch.seq,
                "text": text,
                "t_start_ms": ch.t_start_ms,
                "t_end_ms": ch.t_end_ms,
            }
        )
        count += 1

    try:
        if args.simulate is not None:
            # ファイルを mic 代替で realtime 経路に流す（実マイク不要・確定的）。
            from faster_whisper.audio import decode_audio

            audio = decode_audio(str(args.simulate), sampling_rate=SAMPLE_RATE)
            emit(
                {
                    "type": "meta",
                    "mode": "mic",
                    "duration_s": round(len(audio) / SAMPLE_RATE, 3),
                    "model": args.model,
                    "language": args.language,
                }
            )
            feed_samples(audio, VadChunker(max_seg_s=args.max_seg), sink=sink)
        else:
            # 実マイク。ライブなので duration_s は出さない。
            emit({"type": "meta", "mode": "mic", "model": args.model, "language": args.language})
            stop_event = threading.Event()
            paused = threading.Event()
            _start_stdin_control(stop_event, paused)
            capture_mic(
                VadChunker(max_seg_s=args.max_seg),
                sink,
                device=args.device,
                stop_event=stop_event,
                paused=paused,
            )
        emit({"type": "done", "count": count, "elapsed_s": round(time.perf_counter() - t0, 3)})
    except Exception as e:  # noqa: BLE001
        emit({"type": "error", "message": str(e), "where": "mic"})
        print(f"[sidecar] {e!r}", file=sys.stderr, flush=True)
        return 1
    return 0


def _run_level(args: argparse.Namespace) -> int:
    """入力レベル(RMS)のみを ~100ms ごとに emit する（S-04 プリフライト・whisper 不使用）。

    ``--simulate`` 指定時はファイルを実時間ペースで給電（実マイク不要の検証）。stdin で stop 可。
    """
    import numpy as np

    from synchroni_note.realtime.capture import SAMPLE_RATE

    block = max(1, int(0.1 * SAMPLE_RATE))

    def rms(buf: "np.ndarray") -> float:
        return float(np.sqrt(np.mean(buf.astype(np.float64) ** 2))) if buf.size else 0.0

    emit({"type": "meta", "mode": "level"})
    stop_event = threading.Event()
    _start_stdin_control(stop_event, threading.Event())
    try:
        if args.simulate is not None:
            from faster_whisper.audio import decode_audio

            audio = decode_audio(str(args.simulate), sampling_rate=SAMPLE_RATE)
            for i in range(0, len(audio), block):
                if stop_event.is_set():
                    break
                emit({"type": "level", "rms": round(rms(audio[i : i + block]), 4)})
                time.sleep(0.1)  # 実時間ペースで流す
        else:
            import queue

            import sounddevice as sd

            q: queue.Queue = queue.Queue()

            def _cb(indata, _frames, _time, status) -> None:  # noqa: ANN001  sd 既定シグネチャ
                if status:
                    print(f"[level] {status}", file=sys.stderr, flush=True)
                q.put(indata[:, 0].copy())

            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=block,
                device=args.device,
                callback=_cb,
            ):
                while not stop_event.is_set():
                    try:
                        buf = q.get(timeout=0.3)
                    except queue.Empty:
                        continue
                    emit({"type": "level", "rms": round(rms(buf), 4)})
        emit({"type": "done", "count": 0, "elapsed_s": 0.0})
    except Exception as e:  # noqa: BLE001
        emit({"type": "error", "message": str(e), "where": "level"})
        print(f"[sidecar] {e!r}", file=sys.stderr, flush=True)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows の cp932 端末でも日本語を出力できるよう UTF-8 に再構成する（cli.py と同じ手当て）。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="synchroni-note-sidecar",
        description="文字起こしを JSON Lines で逐次出力する UI 中継口",
    )
    parser.add_argument(
        "audio", type=Path, nargs="?", default=None, help="入力音声(.wav)・ファイル一括"
    )
    parser.add_argument("--mic", action="store_true", help="実マイクからライブ収音")
    parser.add_argument("--level", action="store_true", help="入力レベル(RMS)のみemit(S-04)")
    parser.add_argument(
        "--simulate", type=Path, default=None, help="ファイルをmic代替で流す(テスト)"
    )
    parser.add_argument("--model", default="medium", help="faster-whisper モデル")
    parser.add_argument("--language", default="ja", help="言語コード")
    parser.add_argument("--threads", type=int, default=4, help="cpu_threads(realtime)")
    parser.add_argument("--max-seg", type=float, default=10.0, help="VADチャンク最大秒")
    parser.add_argument("--device", type=int, default=None, help="入力デバイス番号(既定=None)")
    args = parser.parse_args(argv)

    try:
        if args.level:
            return _run_level(args)
        if args.mic or args.simulate is not None:
            return _run_realtime(args)
        if args.audio is not None:
            return _run_file(args)
        emit({"type": "error", "message": "入力なし(audio/--mic/--simulate)", "where": "args"})
        return 2
    except Exception as e:  # noqa: BLE001  最終防衛: どのモードでも error 行を1本は出す
        emit({"type": "error", "message": str(e), "where": "main"})
        print(f"[sidecar] {e!r}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

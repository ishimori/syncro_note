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

# ライブ追い上げ整形（DD-012-4）の調整値。
REFINE_QUEUE_MAX = 3  # 未処理バックログ上限。超えたら整形を捨てる（バイパス＝主役を止めない）
REFINE_DRAIN_TIMEOUT_S = 20.0  # 停止時に整形ワーカーの残りを掃き出す最大待ち秒

# ローリング再分離（DD-017-2・テレビモード）の調整値。
DIARIZE_INTERVAL_S = 8.0  # 録音中に再分離する間隔（秒）。テレビモードの既定
DIARIZE_DRAIN_TIMEOUT_S = 20.0  # 停止時に再分離ワーカーの終了を待つ最大秒


def emit(obj: dict[str, object]) -> None:
    """1行=1JSON を stdout へ書き出す。

    ``ensure_ascii=False`` で日本語をそのまま、各行 ``flush`` で逐次性を担保する（溜め込み防止）。
    全行に契約版 ``"v":1`` を付与する。
    """
    print(json.dumps({"v": 1, **obj}, ensure_ascii=False), flush=True)


def _diarize_file(args: argparse.Namespace):  # noqa: ANN201  list[Turn]（遅延importのため無注記）
    """ファイル全体を一度だけ話者分離して Turn 列を返す（会議後一括ラベリング・DD-012-5）。

    失敗（モデル未配置・デコード不可など）は stderr に出して空リストを返し、文字起こしは止めない。
    """
    if not args.diarize:
        return []
    try:
        from faster_whisper.audio import decode_audio

        from synchroni_note.diarization.labeling import SAMPLE_RATE, diarize_for_labeling

        audio = decode_audio(str(args.audio), sampling_rate=SAMPLE_RATE)
        return diarize_for_labeling(audio, SAMPLE_RATE, k=args.speakers)
    except Exception as e:  # noqa: BLE001  話者分離が失敗しても文字起こしは続行（speaker は spk0 既定）
        print(f"[sidecar] diarize skipped: {e!r}", file=sys.stderr, flush=True)
        return []


def _run_file(args: argparse.Namespace) -> int:
    """ファイル一括ストリーム（DD-011 3-C）。``stream_transcribe`` の逐次出力を流す。"""
    from synchroni_note.diarization.labeling import speaker_for_span
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
    # 会議後一括ラベリング（DD-012-5）: 全体音声を一度だけ話者分離し、各セグメントへ
    # 時間の重なりで話者ラベルを付ける。ファイルは全体が手元にあるので inline で付与できる。
    turns = _diarize_file(args)
    t0 = time.perf_counter()
    count = 0
    for seg in stream.segments:  # 既存の逐次ジェネレータをそのまま流す
        spk = speaker_for_span(turns, seg.t_start_ms, seg.t_end_ms) if turns else "spk0"
        emit(
            {
                "type": "segment",
                "seq": count,
                "text": seg.text,
                "t_start_ms": seg.t_start_ms,
                "t_end_ms": seg.t_end_ms,
                "speaker": spk,
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


def _emit_speaker_map(audio_parts: list, spans: list[tuple[int, int, int]], k: int) -> None:
    """貯めた録音音声を1回だけ話者分離し、seq→話者ラベルの対応を1行 emit する（DD-012-5）。

    会議後一括ラベリング（mic 経路）。失敗しても文字起こし結果は保たれる（emit しないだけ）。
    """
    try:
        import numpy as np

        from synchroni_note.diarization.labeling import (
            SAMPLE_RATE,
            diarize_for_labeling,
            speaker_for_span,
        )

        audio = np.concatenate([a.reshape(-1) for a in audio_parts])
        turns = diarize_for_labeling(audio, SAMPLE_RATE, k=k)
        if not turns:
            return  # 単一話者扱い（live の暫定 spk0 のまま）→ 置換不要
        mp = {str(seq): speaker_for_span(turns, s, e) for seq, s, e in spans}
        emit({"type": "speakers", "map": mp})
    except Exception as e:  # noqa: BLE001  ラベリング失敗で文字起こしを巻き添えにしない
        print(f"[sidecar] speaker map skipped: {e!r}", file=sys.stderr, flush=True)


def _diarize_and_emit(
    audio_parts: list, spans: list[tuple[int, int, int]], k: int, prev_map: dict[str, str]
) -> dict[str, str]:
    """累積音声を再分離し、前回マップと整合させた ``speakers`` を emit（ローリング・DD-017-2）。

    返り値は今回 emit した安定化済みマップ（次回 ``prev_map`` に渡す）。失敗・空・分離なしの
    場合は emit せず ``prev_map`` をそのまま返す（文字起こしは決して止めない）。
    """
    try:
        import numpy as np

        from synchroni_note.diarization.labeling import (
            SAMPLE_RATE,
            diarize_for_labeling,
            speaker_for_span,
            stabilize_labels,
        )

        if not spans:
            return prev_map
        audio = np.concatenate([a.reshape(-1) for a in audio_parts])
        turns = diarize_for_labeling(audio, SAMPLE_RATE, k=k)
        if not turns:
            return prev_map  # 単一話者扱い（live の暫定 spk0 のまま）
        raw = {str(seq): speaker_for_span(turns, s, e) for seq, s, e in spans}
        stable = stabilize_labels(prev_map, raw)
        emit({"type": "speakers", "map": stable})
        return stable
    except Exception as e:  # noqa: BLE001  再分離失敗で STT を巻き添えにしない
        print(f"[sidecar] live diarize skipped: {e!r}", file=sys.stderr, flush=True)
        return prev_map


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

    # 会議後一括ラベリング（DD-012-5）用に、録音音声と各セグメントの時間範囲を貯める。
    # ライブ逐次の話者割当は作り込みが要る（DD-004-1 待ち）ため、停止後に1回だけ分離する。
    # 長時間録音ではメモリを食う点に注意（16k/mono/f32 ≒ 230MB/時）。
    diar_audio: list = []  # list[np.ndarray]（録音チャンクの生音声）
    diar_spans: list[tuple[int, int, int]] = []  # (seq, t_start_ms, t_end_ms)

    # ライブ追い上げ整形（DD-012-4）。確定セグメントを別スレッドで qwen 整形し refined を emit。
    # STT を詰まらせないため非ブロッキング: 小さな bounded queue、満杯ならバイパス（整形を捨てる）。
    import queue

    refine_q: queue.Queue | None = None
    refine_worker: threading.Thread | None = None
    bypass = {"on": False}
    if args.refine:
        refine_q = queue.Queue(maxsize=REFINE_QUEUE_MAX)

        def _refine_loop(q: queue.Queue) -> None:
            from synchroni_note.pipeline.refine import refine_text

            while True:
                item = q.get()
                if item is None:  # 停止センチネル
                    break
                seq, raw = item
                try:
                    r = refine_text(raw, model=args.live_model)
                except Exception as e:  # noqa: BLE001  整形失敗で STT を止めない
                    print(f"[refine] {e!r}", file=sys.stderr, flush=True)
                    continue
                if r:
                    emit({"type": "refined", "seq": seq, "text": r})

        refine_worker = threading.Thread(
            target=_refine_loop, args=(refine_q,), daemon=True, name="refine"
        )
        refine_worker.start()

    # ローリング再分離（DD-017-2・テレビモード）。録音中 N 秒ごとに累積音声を再分離し、
    # 前回マップと整合させた話者ラベルを emit する。STT を止めないよう別スレッドで実行し、
    # worker は単一なので多重起動しない（前回が長引けば自然に間引かれる）。opt-in。
    diar_stop = threading.Event()
    diar_worker: threading.Thread | None = None
    live_state = {"map": {}}  # 最後に emit した安定化済みマップ（最終 emit にも引き継ぐ）
    if args.diarize and args.live_diarize:

        def _diar_loop() -> None:
            while not diar_stop.wait(args.diarize_interval):
                n = len(diar_spans)  # spans は audio の後に append → len(spans)<=len(audio)
                if n == 0:
                    continue
                live_state["map"] = _diarize_and_emit(
                    diar_audio[:n], diar_spans[:n], args.speakers, live_state["map"]
                )

        diar_worker = threading.Thread(target=_diar_loop, daemon=True, name="live-diarize")
        diar_worker.start()

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
                "speaker": "spk0",  # 暫定。停止後の一括ラベリング(speakers)で置換（DD-012-5）
            }
        )
        count += 1
        # 会議後一括ラベリング用に生音声と時間範囲を貯める（停止後に1回だけ分離）。
        if args.diarize:
            diar_audio.append(ch.samples)
            diar_spans.append((ch.seq, ch.t_start_ms, ch.t_end_ms))
        # 追い上げ整形へ回す（非ブロッキング）。満杯なら捨ててバイパス表示（主役は止めない）。
        if refine_q is not None and text:
            try:
                refine_q.put_nowait((ch.seq, text))
                if bypass["on"]:
                    bypass["on"] = False
                    emit({"type": "bypass", "on": False})
            except queue.Full:
                if not bypass["on"]:
                    bypass["on"] = True
                    emit({"type": "bypass", "on": True})

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
                    "refine": args.refine,  # 追い上げ整形が動いているか（S-05 のバッジ表示判定）
                }
            )
            feed_samples(audio, VadChunker(max_seg_s=args.max_seg), sink=sink)
        else:
            # 実マイク。ライブなので duration_s は出さない。
            emit(
                {
                    "type": "meta",
                    "mode": "mic",
                    "model": args.model,
                    "language": args.language,
                    "refine": args.refine,  # 追い上げ整形が動いているか（S-05 のバッジ表示判定）
                }
            )
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
        # 停止後の最終ラベリング: done の前に最新の話者ラベルを送る（UIが完了表示前に反映できる）。
        if args.diarize and diar_audio:
            if args.live_diarize:
                # worker を止め、全音声で最終1回（前回マップへ整列）→ 末尾も反映（DD-017-2）。
                diar_stop.set()
                if diar_worker is not None:
                    diar_worker.join(timeout=DIARIZE_DRAIN_TIMEOUT_S)
                _diarize_and_emit(diar_audio, diar_spans, args.speakers, live_state["map"])
            else:
                _emit_speaker_map(diar_audio, diar_spans, args.speakers)  # 会議後一括（DD-012-5）
        emit({"type": "done", "count": count, "elapsed_s": round(time.perf_counter() - t0, 3)})
        # 整形ワーカーの残りを掃き出してから終了（trailing refined を落とさない）。
        if refine_q is not None and refine_worker is not None:
            refine_q.put(None)
            refine_worker.join(timeout=REFINE_DRAIN_TIMEOUT_S)
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

    from synchroni_note.realtime.capture import SAMPLE_RATE, plan_capture

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

            # RMS はレート非依存なので、開けるレートで開く（16k 無理なら既定レート）。変換は不要。
            plan = plan_capture(args.device)
            with sd.InputStream(
                samplerate=plan.open_rate,
                channels=1,
                dtype="float32",
                blocksize=max(1, int(0.1 * plan.open_rate)),
                device=args.device,
                callback=_cb,
                extra_settings=plan.extra_settings,
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


def _run_list_devices(_args: argparse.Namespace) -> int:
    """入力デバイス一覧を1行 emit する（S-04/S-08 のデバイス選択・DD-012-14）。

    成功: ``{"type":"devices","status":"done","items":[{index,name,hostapi,...,default}]}``
    失敗: ``{"type":"devices","status":"error","message":..,"where":"devices"}``
    sounddevice の device index（`query_devices` の位置）がそのまま ``--device`` に渡せる ID。
    入力ch>0 のものだけを返す。既定入力は ``sd.default.device[0]`` で判定。
    """
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        hostapis = sd.query_hostapis()

        # 既定入力デバイス名（プリセレクト判定用）。MMEは名前を31字に切る癖があり前方一致で照合。
        default_name = ""
        try:
            default_name = str(devices[sd.default.device[0]].get("name", ""))
        except Exception:  # noqa: BLE001  既定未設定環境
            default_name = ""

        def hostapi_name(d: dict) -> str:
            try:
                return str(hostapis[d["hostapi"]]["name"])
            except Exception:  # noqa: BLE001
                return ""

        # 入力ch>0 のデバイス。Windowsは同じ物理マイクがMME/DirectSound/WASAPI/WDM-KSで重複し、
        # 「サウンドマッパー」等の擬似デバイスも混じる。WASAPIは実エンドポイントが綺麗に並ぶので、
        # WASAPI入力があればそれだけ採用しUIを分かりやすくする（無ければ全入力にフォールバック）。
        inputs = [
            (idx, d) for idx, d in enumerate(devices) if int(d.get("max_input_channels", 0)) > 0
        ]
        wasapi = [(idx, d) for idx, d in inputs if hostapi_name(d) == "Windows WASAPI"]
        chosen = wasapi or inputs

        def is_default(name: str) -> bool:
            if not default_name or not name:
                return False
            return name.startswith(default_name) or default_name.startswith(name)

        items: list[dict[str, object]] = []
        for idx, d in chosen:
            name = str(d.get("name", f"device {idx}"))
            items.append(
                {
                    "index": idx,
                    "name": name,
                    "hostapi": hostapi_name(d),
                    "max_input_channels": int(d.get("max_input_channels", 0)),
                    "default": is_default(name),
                }
            )
        # 既定が一覧で1つも当たらなければ先頭を既定扱い（UIのプリセレクトが必ず1件決まる）。
        if items and not any(it["default"] for it in items):
            items[0]["default"] = True
        emit({"type": "devices", "status": "done", "items": items})
        return 0
    except Exception as e:  # noqa: BLE001  列挙不能でも error 行を1本返す（UIは既定にフォールバック）
        emit({"type": "devices", "status": "error", "message": str(e), "where": "devices"})
        print(f"[sidecar] list-devices {e!r}", file=sys.stderr, flush=True)
        return 1


def _run_extract(args: argparse.Namespace) -> int:
    """事前資料（xlsx/pdf）の本文抽出を1行 emit する（DD-012-10）。

    成功: ``{"type":"extract","status":"done","text":..,"chars":N,"truncated":..,"empty":..}``
    失敗: ``{"type":"extract","status":"error","message":..,"where":"extract"}``
    （破損/暗号化/未対応拡張子はここで error に倒す。会議作成自体は妨げない方針）。
    """
    from synchroni_note.pipeline.extract import extract_text

    try:
        r = extract_text(args.extract, file_type=args.type)
        emit(
            {
                "type": "extract",
                "status": "done",
                "text": r.text,
                "chars": r.chars,
                "truncated": r.truncated,
                "empty": r.empty,
            }
        )
        return 0
    except Exception as e:  # noqa: BLE001  破損/暗号化/未対応など全て error 行に倒す
        emit({"type": "extract", "status": "error", "message": str(e), "where": "extract"})
        print(f"[sidecar] extract {e!r}", file=sys.stderr, flush=True)
        return 1


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
        "--list-devices", dest="list_devices", action="store_true",
        help="入力デバイス一覧をemit(S-04/S-08・DD-012-14)",
    )
    parser.add_argument(
        "--simulate", type=Path, default=None, help="ファイルをmic代替で流す(テスト)"
    )
    parser.add_argument("--model", default="medium", help="faster-whisper モデル")
    parser.add_argument("--language", default="ja", help="言語コード")
    parser.add_argument("--threads", type=int, default=4, help="cpu_threads(realtime)")
    parser.add_argument("--max-seg", type=float, default=10.0, help="VADチャンク最大秒")
    parser.add_argument("--device", type=int, default=None, help="入力デバイス番号(既定=None)")
    parser.add_argument(
        "--speakers", type=int, default=2, help="想定話者数k(会議後ラベリング・DD-012-5)"
    )
    parser.add_argument(
        "--no-diarize", dest="diarize", action="store_false", help="会議後の話者ラベリングを無効化"
    )
    parser.set_defaults(diarize=True)
    parser.add_argument(
        "--live-diarize",
        action="store_true",
        help="録音中に定期再分離して話者ラベルをライブ更新(テレビモード・DD-017-2)",
    )
    parser.add_argument(
        "--diarize-interval",
        type=float,
        default=DIARIZE_INTERVAL_S,
        help=f"ライブ再分離の間隔秒(既定{DIARIZE_INTERVAL_S}・--live-diarize時)",
    )
    parser.add_argument(
        "--refine", action="store_true", help="確定セグメントをlive LLMで追い上げ整形(DD-012-4)"
    )
    parser.add_argument("--live-model", default="qwen3:8b", help="追い上げ整形のOllamaモデル")
    parser.add_argument(
        "--extract", type=Path, default=None, help="事前資料(xlsx/pdf)の本文抽出(DD-012-10)"
    )
    parser.add_argument(
        "--type", choices=("xlsx", "pdf"), default=None, help="--extract の種別(省略時は拡張子推定)"
    )
    args = parser.parse_args(argv)

    try:
        if args.list_devices:
            return _run_list_devices(args)
        if args.extract is not None:
            return _run_extract(args)
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

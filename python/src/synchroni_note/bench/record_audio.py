"""マイクから日本語音声を録音し、STTベンチ用の 16kHz モノラル WAV を保存する。

評価期の収音スタック（開発ロードマップ §7）である `sounddevice` を使う。
DD-003 の CER 計測では、付属の読み上げ原稿を**そのまま音読**して録音し、
原稿を正解（reference）として使う。

使い方（python/ 配下で実行。マイク権限が必要）:

    uv run python -m synchroni_note.bench.record_audio --seconds 60 --out audio/sample01.wav

録音は --countdown 秒のカウントダウン後に開始し、--seconds 秒で自動停止する。
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

SAMPLE_RATE = 16000


def to_int16_pcm(samples) -> bytes:
    """float32 [-1,1] の配列を 16bit PCM バイト列へ変換する。"""
    import numpy as np

    clipped = np.clip(samples.reshape(-1), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def write_wav(path: Path, samples, samplerate: int = SAMPLE_RATE) -> None:
    """モノラル 16bit PCM の WAV を書き出す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(to_int16_pcm(samples))


def record(seconds: float, *, samplerate: int = SAMPLE_RATE, device: int | None = None):
    """マイクから seconds 秒録音し float32 モノラル配列を返す。"""
    import sounddevice as sd

    frames = int(seconds * samplerate)
    audio = sd.rec(frames, samplerate=samplerate, channels=1, dtype="float32", device=device)
    sd.wait()
    return audio


def _countdown(n: int) -> None:
    for i in range(n, 0, -1):
        print(f"  録音開始まで {i} ...", flush=True)
        time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="マイク録音（STTベンチ用 16kHz mono WAV）")
    parser.add_argument("--seconds", type=float, default=60.0, help="録音秒数")
    parser.add_argument("--out", type=Path, default=None, help="出力WAVパス")
    parser.add_argument("--countdown", type=int, default=3, help="開始前カウントダウン秒")
    parser.add_argument("--device", type=int, default=None, help="入力デバイス番号(任意)")
    parser.add_argument("--list-devices", action="store_true", help="入力デバイス一覧表示で終了")
    args = parser.parse_args(argv)

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return 0

    if args.out is None:
        parser.error("--out は必須です（--list-devices 時を除く）")

    print(f"これから {args.seconds:.0f} 秒間録音します。原稿を音読してください。", flush=True)
    _countdown(args.countdown)
    print("● 録音中 ... 話してください", flush=True)
    audio = record(args.seconds, device=args.device)
    write_wav(args.out, audio)
    dur = len(audio) / SAMPLE_RATE
    print(f"✓ 録音終了。保存: {args.out}（{dur:.1f}秒 / 16kHz mono）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

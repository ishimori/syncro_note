"""簡易エネルギーVADで有声区間を検出し、無音を除いたセグメントを作る（DD-005 Phase 2）。

目的: whisper に**無音を渡さない**ことで、無音/低レベルノイズでの**幻覚を抑制**し、
無音込みでは不当に悪化する CER を**公平に**測り直す。製品(Rust)は Silero 等を使うが、
評価期は依存を増やさず numpy のエネルギー閾値で効果を実証する。
区間のマージ/フィルタは純関数に切り出し pytest で検証する。
"""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000


def frame_rms(audio: np.ndarray, frame_len: int) -> np.ndarray:
    """フレーム長ごとの RMS 配列を返す（末尾の半端フレームは捨てる）。"""
    if frame_len <= 0:
        raise ValueError("frame_len は正の整数")
    n = len(audio) // frame_len
    if n == 0:
        return np.empty(0, dtype=np.float64)
    framed = audio[: n * frame_len].astype(np.float64).reshape(n, frame_len)
    return np.sqrt((framed**2).mean(axis=1))


def _runs_of_true(flags: list[bool]) -> list[tuple[int, int]]:
    """True が連続する区間を [start, end)（フレーム index）のリストで返す。"""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def merge_runs(
    runs: list[tuple[int, int]], *, max_gap: int, min_len: int
) -> list[tuple[int, int]]:
    """隣接区間を gap<=max_gap でマージし、長さ<min_len の区間を捨てる（純関数）。"""
    if not runs:
        return []
    merged = [list(runs[0])]
    for s, e in runs[1:]:
        if s - merged[-1][1] <= max_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged if e - s >= min_len]


def split_long(runs: list[tuple[int, int]], *, max_len: int) -> list[tuple[int, int]]:
    """max_len を超える区間を max_len 以下に分割する（純関数）。"""
    if max_len <= 0:
        return list(runs)
    out: list[tuple[int, int]] = []
    for s, e in runs:
        cur = s
        while e - cur > max_len:
            out.append((cur, cur + max_len))
            cur += max_len
        out.append((cur, e))
    return out


def detect_voiced_spans(
    audio: np.ndarray,
    *,
    sr: int = SAMPLE_RATE,
    frame_ms: int = 30,
    abs_floor: float = 0.004,
    rel: float = 0.5,
    max_gap_ms: int = 300,
    min_speech_ms: int = 200,
    pad_ms: int = 100,
    max_seg_s: float = 10.0,
) -> list[tuple[int, int]]:
    """エネルギー閾値で有声区間（サンプル単位の [start, end)）を検出する。

    閾値 = max(abs_floor, rel × 有声候補フレームRMSの中央値)。隣接を max_gap_ms でマージ、
    min_speech_ms 未満を除去、pad_ms パディング、max_seg_s で分割。
    """
    frame_len = int(frame_ms * sr / 1000)
    rms = frame_rms(audio, frame_len)
    if rms.size == 0:
        return []
    above = rms[rms > abs_floor]
    thr = max(abs_floor, rel * float(np.median(above))) if above.size else abs_floor
    flags = [bool(v >= thr) for v in rms]

    max_gap = int(max_gap_ms / frame_ms)
    min_len = max(1, int(min_speech_ms / frame_ms))
    runs = merge_runs(_runs_of_true(flags), max_gap=max_gap, min_len=min_len)

    pad = int(pad_ms * sr / 1000)
    total = len(audio)
    spans = [
        (max(0, s * frame_len - pad), min(total, e * frame_len + pad)) for s, e in runs
    ]
    return split_long(spans, max_len=int(max_seg_s * sr))


def concat_voiced(audio: np.ndarray, spans: list[tuple[int, int]]) -> np.ndarray:
    """有声区間のみを連結した音声を返す（無音除去）。"""
    if not spans:
        return audio[:0]
    return np.concatenate([audio[s:e] for s, e in spans])


def voiced_seconds(spans: list[tuple[int, int]], *, sr: int = SAMPLE_RATE) -> float:
    """有声区間の合計秒数。"""
    return sum(e - s for s, e in spans) / sr

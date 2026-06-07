"""音声ファイルを faster-whisper(VADフィルタ付き)で文字起こしする。

VADフィルタ（Silero, faster-whisper内蔵）で無音を除き、whisper の無音幻覚（DD-005で確認）を
抑制する。日本語精度のため既定モデルは medium（DD-003/005）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    """文字起こしの1セグメント（テキストと開始/終了ミリ秒）。"""

    text: str
    t_start_ms: int
    t_end_ms: int


def transcribe(
    audio_path: Path,
    *,
    model_size: str = "medium",
    threads: int = 8,
    language: str = "ja",
    vad: bool = True,
) -> list[Segment]:
    """音声ファイルを文字起こししセグメント列を返す（CPU/int8）。"""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=threads)
    segments, _info = model.transcribe(
        str(audio_path), language=language, beam_size=1, vad_filter=vad
    )
    return [
        Segment(
            text=seg.text.strip(),
            t_start_ms=int(seg.start * 1000),
            t_end_ms=int(seg.end * 1000),
        )
        for seg in segments
    ]


def transcript_text(segments: list[Segment]) -> str:
    """セグメント列を1本の本文テキストに連結する。"""
    return "".join(seg.text for seg in segments)

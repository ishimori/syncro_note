"""音声ファイルを faster-whisper(VADフィルタ付き)で文字起こしする。

VADフィルタ（Silero, faster-whisper内蔵）で無音を除き、whisper の無音幻覚（DD-005で確認）を
抑制する。日本語精度のため既定モデルは medium（DD-003/005）。

UIの進捗表示用に、音声長と「セグメントを逐次返す」ストリームAPI（stream_transcribe）も提供する。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    """文字起こしの1セグメント（テキストと開始/終了ミリ秒）。"""

    text: str
    t_start_ms: int
    t_end_ms: int


@dataclass
class TranscriptionStream:
    """音声長（即時に判明）と、セグメントを逐次返すジェネレータ。"""

    duration_s: float
    segments: Iterator[Segment]


def stream_transcribe(
    audio_path: Path,
    *,
    model_size: str = "medium",
    threads: int = 8,
    language: str = "ja",
    vad: bool = True,
) -> TranscriptionStream:
    """音声長を即時に返しつつ、セグメントを逐次生成するストリームを返す。

    `duration_s` は文字起こし開始前に判明する（進捗UIの「音声長」表示用）。
    `segments` を反復すると実際の文字起こしが進む。
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=threads)
    raw, info = model.transcribe(
        str(audio_path), language=language, beam_size=1, vad_filter=vad
    )

    def _gen() -> Iterator[Segment]:
        for seg in raw:
            yield Segment(
                text=seg.text.strip(),
                t_start_ms=int(seg.start * 1000),
                t_end_ms=int(seg.end * 1000),
            )

    return TranscriptionStream(duration_s=float(info.duration), segments=_gen())


def transcribe(
    audio_path: Path,
    *,
    model_size: str = "medium",
    threads: int = 8,
    language: str = "ja",
    vad: bool = True,
) -> list[Segment]:
    """音声ファイルを文字起こしし、セグメント列を返す（一括・CLI用）。"""
    stream = stream_transcribe(
        audio_path, model_size=model_size, threads=threads, language=language, vad=vad
    )
    return list(stream.segments)


def transcript_text(segments: list[Segment]) -> str:
    """セグメント列を1本の本文テキストに連結する。"""
    return "".join(seg.text for seg in segments)

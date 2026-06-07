"""話者分離の手法共通インターフェースと疎通用 dummy 実装（DD-004 Phase 1）。

実手法（pyannote / sherpa-onnx / 簡易クラスタリング）は Phase 2 で同じ `diarize` シグネチャの
アダプタとして追加する。Phase 1 はハーネス（参照RTTM生成・DER計測）の疎通確認だけを行うため、
依存ゼロの `dummy_single_speaker` のみを置く。
"""

from __future__ import annotations

import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from synchroni_note.bench.vad_segment import detect_voiced_spans

SAMPLE_RATE = 16000


def load_wav_mono16k(path: Path) -> np.ndarray:
    """16kHz/mono/PCM16 wav を float32([-1,1]) で読み込む（依存なし）。"""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1:
            raise ValueError(
                f"想定は 16kHz/mono。実際: {w.getframerate()}Hz/{w.getnchannels()}ch"
            )
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


@dataclass(frozen=True)
class Turn:
    """話者区間。onset/offset は秒、speaker は話者ラベル。

    正解では speaker は人名（鈴木/佐藤）、推定では任意ラベル（spk0 等）。
    DER 計測時に推定ラベルと正解ラベルは最適対応付けされるため、ラベル名の一致は不要。
    """

    onset_s: float
    offset_s: float
    speaker: str

    @property
    def duration_s(self) -> float:
        return max(0.0, self.offset_s - self.onset_s)


# 手法は「音声(np.float32, 16k mono)・サンプリングレート・想定話者数 k」を受け取り Turn 列を返す。
DiarizeFn = Callable[[np.ndarray, int, int], list[Turn]]


def dummy_single_speaker(audio: np.ndarray, sr: int = SAMPLE_RATE, k: int = 2) -> list[Turn]:
    """全有声区間を 1 話者として返す疎通用ベースライン（k は無視）。

    話者分離を一切しない最弱ベースライン。多話者音声では他話者の発話がすべて confusion になる。
    """
    spans = detect_voiced_spans(audio, sr=sr)
    return [Turn(onset_s=s / sr, offset_s=e / sr, speaker="spk0") for s, e in spans]


def dummy_alternating(audio: np.ndarray, sr: int = SAMPLE_RATE, k: int = 2) -> list[Turn]:
    """有声区間を spk0..spk{k-1} と循環で振る疎通用ベースライン。

    実発話が概ね順番なら VAD区切りと一致して高精度に、ずれれば崩れる。
    dummy_single_speaker と対で「DERが手法で動く」ことを示す。
    """
    spans = detect_voiced_spans(audio, sr=sr)
    return [
        Turn(onset_s=s / sr, offset_s=e / sr, speaker=f"spk{i % max(1, k)}")
        for i, (s, e) in enumerate(spans)
    ]


def _simple_cluster(audio: np.ndarray, sr: int = SAMPLE_RATE, k: int = 2) -> list[Turn]:
    # 遅延 import で循環依存を避ける（simple_cluster は base.Turn を参照）
    from synchroni_note.diarization.simple_cluster import simple_cluster

    return simple_cluster(audio, sr, k=k)


def _onnx_embed(audio: np.ndarray, sr: int = SAMPLE_RATE, k: int = 2) -> list[Turn]:
    # 遅延 import（onnxruntime/knf を使う手法時のみロード）
    from synchroni_note.diarization.embedding_onnx import embedding_onnx

    return embedding_onnx(audio, sr, k=k)


METHODS: dict[str, DiarizeFn] = {
    "dummy": dummy_single_speaker,
    "dummy-alt": dummy_alternating,
    "simple-cluster": _simple_cluster,
    "onnx-embed": _onnx_embed,
}

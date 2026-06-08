"""DD-012-5 会議後一括ラベリングの純ロジック（モデル不要・決定的）。

話者分離アルゴリズム自体は DD-004 のテストで担保。ここでは「Turn→セグメントへの
時間重なり割当」と「手法の差し替え/フォールバック選択」だけを検証する。
"""

from __future__ import annotations

import numpy as np

from synchroni_note.diarization import labeling
from synchroni_note.diarization.base import Turn
from synchroni_note.diarization.labeling import (
    assign_speakers,
    diarize_for_labeling,
    speaker_for_span,
)

# 0-2秒=spk0 / 2-5秒=spk1 の2話者
_TURNS = [Turn(0.0, 2.0, "spk0"), Turn(2.0, 5.0, "spk1")]


def test_speaker_for_span_picks_overlapping_speaker():
    assert speaker_for_span(_TURNS, 0, 1500) == "spk0"
    assert speaker_for_span(_TURNS, 2200, 4000) == "spk1"


def test_speaker_for_span_picks_majority_overlap():
    # 1000-2800ms: spk0 と 1000ms(1000-2000)・spk1 と 800ms(2000-2800) 重なる → 長い spk0
    assert speaker_for_span(_TURNS, 1000, 2800) == "spk0"


def test_speaker_for_span_sums_same_speaker_over_multiple_turns():
    # 同一話者が複数 Turn に分かれていても合算で勝てる
    turns = [Turn(0.0, 1.0, "spk0"), Turn(1.0, 2.0, "spk1"), Turn(2.0, 3.0, "spk0")]
    # 0-3秒: spk0=2秒(0-1,2-3) / spk1=1秒(1-2) → spk0
    assert speaker_for_span(turns, 0, 3000) == "spk0"


def test_speaker_for_span_defaults_spk0_without_overlap():
    assert speaker_for_span(_TURNS, 9000, 9500) == "spk0"  # どの Turn とも重ならない
    assert speaker_for_span([], 0, 1000) == "spk0"  # 分離なし（空）


def test_assign_speakers_maps_each_span():
    spans = [(0, 1500), (2200, 4000), (9000, 9500)]
    assert assign_speakers(_TURNS, spans) == ["spk0", "spk1", "spk0"]


def test_diarize_uses_selected_method(monkeypatch):
    marker = [Turn(0.0, 1.0, "chosen")]
    monkeypatch.setitem(labeling.METHODS, "onnx-embed", lambda a, sr, k: marker)
    out = diarize_for_labeling(np.zeros(16000, dtype=np.float32), 16000, k=2)
    assert out == marker


def test_diarize_falls_back_when_primary_fails(monkeypatch):
    def boom(a, sr, k):
        raise RuntimeError("model missing")

    fallback = [Turn(0.0, 1.0, "fallback")]
    monkeypatch.setitem(labeling.METHODS, "onnx-embed", boom)
    monkeypatch.setitem(labeling.METHODS, "simple-cluster", lambda a, sr, k: fallback)
    out = diarize_for_labeling(np.zeros(16000, dtype=np.float32), 16000, k=2)
    assert out == fallback  # 本採用が落ちても無モデル手法へ退避


def test_diarize_returns_empty_when_all_fail(monkeypatch):
    def boom(a, sr, k):
        raise RuntimeError("nope")

    monkeypatch.setitem(labeling.METHODS, "onnx-embed", boom)
    monkeypatch.setitem(labeling.METHODS, "simple-cluster", boom)
    assert diarize_for_labeling(np.zeros(16000, dtype=np.float32), 16000, k=2) == []

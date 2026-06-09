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
    stabilize_labels,
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


# --- stabilize_labels（ローリング再分離のラベル安定化・DD-017-2） ---


def test_stabilize_empty_prev_returns_new_as_is():
    # 初回（前回マップ無し）は生結果をそのまま使う
    new = {"0": "spk0", "1": "spk1"}
    assert stabilize_labels({}, new) == new


def test_stabilize_identical_is_unchanged():
    prev = {"0": "spk0", "1": "spk1", "2": "spk0"}
    assert stabilize_labels(prev, dict(prev)) == prev


def test_stabilize_realigns_fully_swapped_labels():
    # 同じ話者構成だがクラスタ順が反転（spk0↔spk1）→ 前回の色へ戻す
    prev = {"0": "spk0", "1": "spk1", "2": "spk0", "3": "spk1"}
    swapped = {"0": "spk1", "1": "spk0", "2": "spk1", "3": "spk0"}
    assert stabilize_labels(prev, swapped) == prev


def test_stabilize_assigns_new_label_to_new_speaker():
    # 既存話者(spk0)は維持しつつ、新規話者には未使用番号を採番
    prev = {"0": "spk0", "1": "spk0"}
    new = {"0": "spk0", "1": "spk0", "2": "spk1"}  # seq2 に新話者
    out = stabilize_labels(prev, new)
    assert out["0"] == "spk0" and out["1"] == "spk0"
    assert out["2"] == "spk1"  # 未使用の最小番号


def test_stabilize_relabels_segments_absent_in_prev():
    # 前回に無い最新 seq(2,3) にも置換が適用される（反転を補正）
    prev = {"0": "spk0", "1": "spk1"}
    new = {"0": "spk1", "1": "spk0", "2": "spk1", "3": "spk0"}
    out = stabilize_labels(prev, new)
    # 生 spk1→spk0, 生 spk0→spk1 の置換が全 seq に効く
    assert out == {"0": "spk0", "1": "spk1", "2": "spk0", "3": "spk1"}


def test_stabilize_new_label_avoids_reused_existing_colors():
    # 3話者: 2つは既存へ整列、1つは新規。新規番号は既存(spk0/spk1)を避ける
    prev = {"0": "spk0", "1": "spk1"}
    new = {"0": "spk1", "1": "spk0", "2": "spk2"}  # spk2 が新規話者
    out = stabilize_labels(prev, new)
    assert out["0"] == "spk0" and out["1"] == "spk1"
    assert out["2"] not in ("spk0", "spk1")  # 既存色と衝突しない採番
    assert out["2"] == "spk2"

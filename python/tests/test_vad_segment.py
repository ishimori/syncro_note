"""vad_segment の純関数（フレームRMS・区間グルーピング/マージ/分割）の単体テスト。"""

from __future__ import annotations

import numpy as np
import pytest

from synchroni_note.bench.vad_segment import (
    _runs_of_true,
    concat_voiced,
    frame_rms,
    merge_runs,
    split_long,
    voiced_seconds,
)


def test_frame_rms_basic() -> None:
    audio = np.array([0.0, 0.0, 1.0, 1.0], dtype=np.float32)
    rms = frame_rms(audio, 2)
    assert rms.tolist() == [0.0, 1.0]


def test_frame_rms_drops_remainder() -> None:
    audio = np.ones(5, dtype=np.float32)
    assert frame_rms(audio, 2).shape == (2,)  # 末尾1サンプルは捨てる


def test_frame_rms_zero_guard() -> None:
    assert frame_rms(np.ones(1, dtype=np.float32), 2).size == 0
    with pytest.raises(ValueError):
        frame_rms(np.ones(4, dtype=np.float32), 0)


def test_runs_of_true() -> None:
    assert _runs_of_true([False, True, True, False, True]) == [(1, 3), (4, 5)]
    assert _runs_of_true([True, True]) == [(0, 2)]
    assert _runs_of_true([False, False]) == []


def test_merge_runs_merges_small_gap() -> None:
    # gap = 3-2 = 1 <= max_gap → マージ
    assert merge_runs([(0, 2), (3, 5)], max_gap=1, min_len=1) == [(0, 5)]


def test_merge_runs_keeps_large_gap() -> None:
    assert merge_runs([(0, 2), (5, 7)], max_gap=1, min_len=1) == [(0, 2), (5, 7)]


def test_merge_runs_drops_short() -> None:
    # マージ後 長さ<min_len は除去
    assert merge_runs([(0, 1), (10, 14)], max_gap=1, min_len=3) == [(10, 14)]


def test_split_long() -> None:
    assert split_long([(0, 25)], max_len=10) == [(0, 10), (10, 20), (20, 25)]
    assert split_long([(0, 8)], max_len=10) == [(0, 8)]


def test_voiced_seconds() -> None:
    assert voiced_seconds([(0, 16000), (16000, 32000)], sr=16000) == pytest.approx(2.0)


def test_concat_voiced() -> None:
    audio = np.arange(10, dtype=np.float32)
    out = concat_voiced(audio, [(0, 2), (5, 7)])
    assert out.tolist() == [0.0, 1.0, 5.0, 6.0]
    assert concat_voiced(audio, []).size == 0

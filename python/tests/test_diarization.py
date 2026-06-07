"""DD-004 話者分離ハーネスのユニットテスト（whisperモデル不要の純ロジック）。"""

from __future__ import annotations

from pathlib import Path

from synchroni_note.diarization.base import Turn
from synchroni_note.diarization.reference import (
    _map_ref_to_hyp,
    intersect_with_voiced,
    normalize,
)
from synchroni_note.diarization.rttm import der, read_rttm, write_rttm


def test_normalize_strips_punct_and_space():
    assert normalize("お疲れ様です。 今日は、") == "お疲れ様です今日は"


def test_map_ref_to_hyp_identity():
    s = "あいうえお"
    assert _map_ref_to_hyp(s, s) == [0, 1, 2, 3, 4]


def test_map_ref_to_hyp_with_noise():
    # hyp に余分な文字が入っても ref 各文字が単調に対応付く
    ref = "あいうえお"
    hyp = "あいXうえYお"
    m = _map_ref_to_hyp(ref, hyp)
    assert len(m) == len(ref)
    assert m == sorted(m)  # 単調非減少
    assert m[0] == 0 and m[-1] == len(hyp) - 1


def test_rttm_roundtrip(tmp_path: Path):
    turns = [
        Turn(0.0, 2.0, "鈴木"),
        Turn(2.0, 5.0, "佐藤"),
    ]
    p = tmp_path / "x.rttm"
    write_rttm(p, "x", turns)
    back = read_rttm(p)
    assert [(round(t.onset_s, 3), round(t.offset_s, 3), t.speaker) for t in back] == [
        (0.0, 2.0, "鈴木"),
        (2.0, 5.0, "佐藤"),
    ]


def test_der_perfect_match_is_zero():
    ref = [Turn(0.0, 5.0, "A"), Turn(5.0, 10.0, "B")]
    hyp = [Turn(0.0, 5.0, "spk0"), Turn(5.0, 10.0, "spk1")]
    # ラベル名が違っても最適対応付けで DER=0
    assert der(ref, hyp, collar=0.0).der == 0.0


def test_der_single_speaker_confusion():
    # 全区間を1話者にすると、もう一方(5s/10s=50%)が confusion になる
    ref = [Turn(0.0, 5.0, "A"), Turn(5.0, 10.0, "B")]
    hyp = [Turn(0.0, 10.0, "spk0")]
    r = der(ref, hyp, collar=0.0)
    assert abs(r.der - 0.5) < 0.02
    assert r.n_hyp_speakers == 1


def test_der_miss_and_false_alarm():
    ref = [Turn(0.0, 5.0, "A")]
    hyp = [Turn(2.0, 7.0, "spk0")]  # 0-2 が miss, 5-7 が FA, 2-5 一致
    r = der(ref, hyp, collar=0.0)
    # ref発話=5s。miss=2s, FA=2s -> DER=(2+2)/5=0.8
    assert abs(r.der - 0.8) < 0.02


def test_intersect_with_voiced_removes_silence():
    # 0-10s を1ターン、有声は 0-3s と 6-8s のみ → 無音(3-6,8-10)が落ちる
    turns = [Turn(0.0, 10.0, "鈴木")]
    out = intersect_with_voiced(turns, [(0.0, 3.0), (6.0, 8.0)])
    assert [(t.onset_s, t.offset_s, t.speaker) for t in out] == [
        (0.0, 3.0, "鈴木"),
        (6.0, 8.0, "鈴木"),
    ]


def test_intersect_preserves_speaker_at_boundary():
    # 話者交代をまたぐ有声区間でも、各ターンの所属は保たれる（交差で分割）
    turns = [Turn(0.0, 5.0, "A"), Turn(5.0, 10.0, "B")]
    out = intersect_with_voiced(turns, [(3.0, 7.0)])
    assert [(t.onset_s, t.offset_s, t.speaker) for t in out] == [
        (3.0, 5.0, "A"),
        (5.0, 7.0, "B"),
    ]

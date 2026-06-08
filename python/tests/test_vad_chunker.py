"""VadChunker（ローリングVADチャンク化）の単体テスト。合成波形で境界条件を検証する。"""

from __future__ import annotations

import numpy as np

from synchroni_note.realtime.capture import SAMPLE_RATE, VadChunker, feed_samples


def _voiced(seconds: float, amp: float = 0.1) -> np.ndarray:
    return np.full(int(seconds * SAMPLE_RATE), amp, dtype=np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def test_silence_cut_after_speech() -> None:
    # 有声2.5s → 無音0.6s(>=400ms) → 有声1.0s : 無音の中点でカットされ1チャンク確定
    chunker = VadChunker()
    audio = np.concatenate([_voiced(2.5), _silence(0.6), _voiced(1.0)])
    emitted = chunker.push(audio)
    assert len(emitted) == 1
    assert 2.5 < emitted[0].duration_s < 3.1  # 2.5s + 無音半分(0.3s)あたり
    assert emitted[0].seq == 0
    # 残り（無音後半＋有声1.0s）は flush で最終チャンクに
    assert len(chunker.flush()) == 1


def test_max_seg_force_split() -> None:
    # 無音なしの連続有声25s, max_seg=10 → 10秒ごとに強制分割
    chunker = VadChunker(max_seg_s=10.0)
    emitted = chunker.push(_voiced(25.0))
    assert len(emitted) == 2  # 10s, 10s（残り5sはバッファ）
    assert all(c.duration_s <= 10.01 for c in emitted)
    assert [c.seq for c in emitted] == [0, 1]
    assert len(chunker.flush()) == 1  # 残り5s


def test_all_silence_emits_nothing() -> None:
    chunker = VadChunker()
    assert chunker.push(_silence(3.0)) == []
    assert chunker.flush() == []


def test_short_speech_only_flushed() -> None:
    # min_speech(2s)未満・無音なし → push では確定せず flush で出る
    chunker = VadChunker()
    assert chunker.push(_voiced(1.0)) == []
    assert len(chunker.flush()) == 1


def test_feed_samples_preserves_voiced_tail() -> None:
    # 末尾が有声なら全サンプルがいずれかのチャンクに含まれる（取りこぼしゼロの不変条件）
    chunker = VadChunker()
    audio = np.concatenate([_voiced(2.5), _silence(0.6), _voiced(1.0)])
    chunks = feed_samples(audio, chunker, block_ms=100)
    assert sum(len(c.samples) for c in chunks) == len(audio)


# --- DD-010-2 Phase 1: 強制カットの最静点化（scenarios.md B群） ---


def test_force_cut_prefers_quietest_point() -> None:
    # B1: 無音(0)は無いが途中に「音の谷」(amp 0.02)。10sちょうどでなく谷の近傍(≒8.15s)で切る
    chunker = VadChunker()
    audio = np.concatenate([_voiced(8.0, 0.1), _voiced(0.3, 0.02), _voiced(8.0, 0.1)])
    emitted = chunker.push(audio)
    assert len(emitted) >= 1
    assert 7.5 < emitted[0].duration_s < 9.0  # 谷(8.0〜8.3s)近傍。10sではない


def test_force_cut_ignores_shallow_dip() -> None:
    # B3: 浅い揺らぎ(0.095 vs 0.1)は谷とみなさず従来どおり10sで切る（安全弁）
    chunker = VadChunker()
    audio = np.concatenate([_voiced(8.0, 0.1), _voiced(0.3, 0.095), _voiced(8.0, 0.1)])
    emitted = chunker.push(audio)
    assert len(emitted) >= 1
    assert 9.9 < emitted[0].duration_s <= 10.01  # フォールバック = max_seg


def test_real_silence_takes_priority_over_quiet_point() -> None:
    # B4: 本物の無音(0)区切りが谷より優先される
    chunker = VadChunker()
    audio = np.concatenate([_voiced(3.0, 0.1), _silence(0.6), _voiced(8.0, 0.1)])
    emitted = chunker.push(audio)
    assert len(emitted) >= 1
    assert 3.0 < emitted[0].duration_s < 3.7  # 無音中点 ≒3.3s

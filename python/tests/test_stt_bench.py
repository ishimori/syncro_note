"""stt_bench の純関数（RTF / CER / チャンク分割）の単体テスト。"""

from __future__ import annotations

import pytest

from synchroni_note.bench.stt_bench import (
    character_error_rate,
    chunk_samples,
    real_time_factor,
)


def test_rtf_basic() -> None:
    # 処理5秒 / 音声10秒 → 0.5（リアルタイム可）
    assert real_time_factor(5.0, 10.0) == pytest.approx(0.5)


def test_rtf_over_realtime() -> None:
    assert real_time_factor(20.0, 10.0) == pytest.approx(2.0)


def test_rtf_zero_audio_guard() -> None:
    assert real_time_factor(3.0, 0.0) == 0.0
    assert real_time_factor(3.0, -1.0) == 0.0


def test_cer_identical_is_zero() -> None:
    assert character_error_rate("次のアジェンダです", "次のアジェンダです") == 0.0


def test_cer_one_substitution() -> None:
    # 5文字中1文字置換 → 0.2
    assert character_error_rate("あいうえお", "あいうえX") == pytest.approx(0.2)


def test_cer_deletion_and_insertion() -> None:
    # 参照5文字、1文字削除 → 距離1 / 5
    assert character_error_rate("あいうえお", "あいうえ") == pytest.approx(0.2)
    # 1文字挿入 → 距離1 / 5
    assert character_error_rate("あいうえお", "あXいうえお") == pytest.approx(0.2)


def test_cer_ignores_whitespace() -> None:
    # 空白の有無はCERに影響しない（日本語STTの空白挿入差を吸収）
    assert character_error_rate("あい うえお", "あいうえお") == 0.0


def test_cer_ignores_punctuation() -> None:
    # 句読点・括弧の差はCERに影響しない（音認誤りに集中）
    assert character_error_rate("始めます。次に、佐藤さん", "始めます 次に佐藤さん") == 0.0


def test_cer_empty_reference_guard() -> None:
    assert character_error_rate("", "なにか") == 0.0
    assert character_error_rate("   ", "なにか") == 0.0


def test_chunk_samples_even_split() -> None:
    assert chunk_samples(10, 5) == [(0, 5), (5, 10)]


def test_chunk_samples_remainder() -> None:
    assert chunk_samples(12, 5) == [(0, 5), (5, 10), (10, 12)]


def test_chunk_samples_guards() -> None:
    assert chunk_samples(0, 5) == []
    assert chunk_samples(10, 0) == [(0, 10)]  # 分割長0なら全体1チャンク

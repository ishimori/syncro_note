"""model_switch_bench の純ロジック（二重常駐判定・外挿）の単体テスト。

実 LLM／プロセス計測（run_switch_cycle 等）は Ollama 依存のため手動実行（DD-006 Phase 2）。
"""

from __future__ import annotations

from synchroni_note.bench.model_switch_bench import (
    PsSnapshot,
    detect_double_resident,
    extrapolate_cleanup,
)


def test_detect_double_resident_true() -> None:
    """8b と 26b が同時に載る瞬間があれば True。"""
    timeline = [
        PsSnapshot(0.0, ["qwen3:8b"], 5.0),
        PsSnapshot(0.2, ["qwen3:8b", "gemma4:26b"], 21.0),  # 二重常駐窓
        PsSnapshot(0.4, ["gemma4:26b"], 17.0),
    ]
    assert detect_double_resident(timeline, "qwen3:8b", "gemma4:26b") is True


def test_detect_double_resident_false() -> None:
    """退避→空→ロードと順序が守られていれば False。"""
    timeline = [
        PsSnapshot(0.0, ["qwen3:8b"], 5.0),
        PsSnapshot(0.2, [], 0.1),  # ps 空（直列が守られた）
        PsSnapshot(0.4, ["gemma4:26b"], 17.0),
    ]
    assert detect_double_resident(timeline, "qwen3:8b", "gemma4:26b") is False


def test_detect_double_resident_empty() -> None:
    assert detect_double_resident([], "qwen3:8b", "gemma4:26b") is False


def test_extrapolate_cleanup_basic() -> None:
    """所要秒 = 出力tok / tok/s。"""
    assert extrapolate_cleanup(10.0, [100, 1000]) == [(100, 10.0), (1000, 100.0)]


def test_extrapolate_cleanup_zero_tps() -> None:
    """tok/s が 0 でも 0除算せず 0.0 を返す。"""
    assert extrapolate_cleanup(0.0, [100]) == [(100, 0.0)]

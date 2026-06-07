"""清書サイドカー（DD-012-2）のストリーム→契約イベント変換を Ollama 非依存で検証する。"""

from __future__ import annotations

from synchroni_note.pipeline.summarize_sidecar import stream_to_events


def test_progress_sends_only_delta_then_done_full() -> None:
    # (累積text, metrics) の偽ストリーム。最後だけ metrics 付き = done。
    stream = [
        ("こん", None),
        ("こんにちは", None),
        ("こんにちは\n# 議事録", {"input_tokens": 5, "output_tokens": 7, "eval_s": 2.0}),
    ]
    events = list(stream_to_events(stream))
    assert events == [
        {"type": "summary-progress", "delta": "こん", "chars": 2},
        {"type": "summary-progress", "delta": "にちは", "chars": 5},
        {
            "type": "summary-done",
            "markdown": "こんにちは\n# 議事録",
            "input_tokens": 5,
            "output_tokens": 7,
            "eval_s": 2.0,
        },
    ]


def test_done_rounds_eval_seconds() -> None:
    stream = [("x", {"input_tokens": 1, "output_tokens": 1, "eval_s": 1.23456})]
    (done,) = list(stream_to_events(stream))
    assert done["eval_s"] == 1.235


def test_empty_delta_is_skipped() -> None:
    # 同じ累積が連続しても（delta 空）progress は送らない。
    stream = [("a", None), ("a", None), ("ab", None)]
    events = list(stream_to_events(stream))
    assert events == [
        {"type": "summary-progress", "delta": "a", "chars": 1},
        {"type": "summary-progress", "delta": "b", "chars": 2},
    ]

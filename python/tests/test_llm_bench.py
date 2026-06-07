import pytest

from synchroni_note.bench.llm_bench import (
    BenchResult,
    average,
    build_prompt,
    format_markdown,
    tokens_per_second,
)


def test_tokens_per_second_basic() -> None:
    # 100トークンを2秒(2e9ns)で処理 → 50 tok/s
    assert tokens_per_second(100, 2_000_000_000) == pytest.approx(50.0)


def test_tokens_per_second_zero_guard() -> None:
    assert tokens_per_second(100, 0) == 0.0
    assert tokens_per_second(0, 1_000_000_000) == 0.0
    assert tokens_per_second(100, -5) == 0.0


def test_build_prompt_includes_transcript() -> None:
    prompt = build_prompt("テスト書き起こし")
    assert "テスト書き起こし" in prompt
    assert "議事録" in prompt


def test_average() -> None:
    a = BenchResult("m", 10.0, 100.0, 0.5, 2.0, 100, 500)
    b = BenchResult("m", 20.0, 200.0, 1.5, 4.0, 200, 700)
    avg = average([a, b])
    assert avg.model == "m"
    assert avg.gen_tps == pytest.approx(15.0)
    assert avg.prompt_tps == pytest.approx(150.0)
    assert avg.ttft_s == pytest.approx(1.0)
    assert avg.total_s == pytest.approx(3.0)
    assert avg.eval_count == 150
    assert avg.prompt_eval_count == 600


def test_average_empty_raises() -> None:
    with pytest.raises(ValueError):
        average([])


def test_format_markdown() -> None:
    r = BenchResult("qwen3:8b", 12.3, 200.0, 0.8, 5.0, 123, 456)
    md = format_markdown([r], think=False)
    assert "qwen3:8b" in md
    assert "12.3" in md
    assert "thinking=OFF" in md

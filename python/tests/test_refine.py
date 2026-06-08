"""ライブ追い上げ整形（DD-012-4）の純粋部分を Ollama 非依存で検証する。"""

from __future__ import annotations

from synchroni_note.pipeline import refine
from synchroni_note.pipeline.refine import build_refine_prompt, refine_text


def test_build_refine_prompt_includes_text_and_instruction() -> None:
    p = build_refine_prompt("えーと、まあ、そうですね")
    assert "えーと、まあ、そうですね" in p
    assert "発話" in p  # 指示文の枠が付く


def test_refine_text_strips_think_and_whitespace(monkeypatch) -> None:
    class _Resp:
        response = "  <think>どう整えるか</think>認証フローを見直します。  "

    monkeypatch.setattr(refine.ollama, "generate", lambda **_: _Resp())
    out = refine_text("にんしょうフローを、えー、見直します", model="qwen3:8b")
    assert out == "認証フローを見直します。"


def test_refine_text_empty_input_returns_empty_without_calling_ollama(monkeypatch) -> None:
    def _boom(**_):  # 呼ばれたら失敗（空入力ではモデルを叩かない）
        raise AssertionError("ollama should not be called for empty input")

    monkeypatch.setattr(refine.ollama, "generate", _boom)
    assert refine_text("   ") == ""

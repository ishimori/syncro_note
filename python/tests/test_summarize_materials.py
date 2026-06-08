"""事前資料(DD-012-10)が清書プロンプトへ統合されることを Ollama 非依存で検証する。

DD-012-10 Phase 4 の機械検証「資料あり/なしで清書プロンプトに資料節が入る/入らない」を固定する。
"""

from __future__ import annotations

from synchroni_note.pipeline.summarize import build_minutes_prompt


def test_materials_section_appears_before_transcript() -> None:
    prompt = build_minutes_prompt(
        "田中: 予算を確認します。",
        title="予算会議",
        materials="# 予算案\n人件費 1200万円",
    )
    assert "--- 事前資料 ---" in prompt
    assert "人件費 1200万円" in prompt
    # 事前資料は書き起こしの「前」に置く（文脈→本文の順）。
    assert prompt.index("--- 事前資料 ---") < prompt.index("--- 書き起こし ---")


def test_no_materials_section_when_absent_or_blank() -> None:
    base = build_minutes_prompt("発話のみ。", title="会議")
    assert "--- 事前資料 ---" not in base
    # 空白だけの資料も節を出さない（空PDF=本文なしのとき余計な節を足さない）。
    blank = build_minutes_prompt("発話のみ。", materials="   \n  ")
    assert "--- 事前資料 ---" not in blank


def test_vocab_appears_in_prompt() -> None:
    # DD-012-12 Bug#7: 専門用語が清書プロンプトの前提に入る（STT/清書の固有名詞精度向上）。
    prompt = build_minutes_prompt("本文", vocab=["Qwen", "SynchroniNote"])
    assert "専門用語: Qwen, SynchroniNote" in prompt
    # 空なら専門用語行は出ない。
    assert "専門用語:" not in build_minutes_prompt("本文")


def test_materials_coexist_with_title_and_agenda() -> None:
    prompt = build_minutes_prompt(
        "本文",
        title="設計会議",
        agenda="DBレビュー",
        materials="設計メモ本文",
    )
    # 前提(会議名/アジェンダ) と 事前資料 が両方入り、ともに書き起こしの前にある。
    assert "- 会議名: 設計会議" in prompt
    assert "- アジェンダ: DBレビュー" in prompt
    assert "設計メモ本文" in prompt
    assert prompt.index("設計メモ本文") < prompt.index("--- 書き起こし ---")

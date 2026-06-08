"""ライブ追い上げ整形（DD-012-4）: 確定セグメントを live `qwen3:8b` でケバ取り/語尾整え。

基本設計の原則＝「確定テキストが主役・LLM整形は遅れてよい追い上げレイヤ」。本モジュールは
1セグメント分の整形を担う純粋な口で、非ブロッキング実行（ワーカースレッドで回す）は呼び出し側
（`pipeline/sidecar.py`）の責務。Ollama を叩く部分と、プロンプト組み立て・後処理を分けてある。
"""

from __future__ import annotations

import re

import ollama

REFINE_INSTRUCTION = (
    "次の会議発話を、意味を変えずに自然な書き言葉へ整えてください。"
    "言い淀み・フィラー（えー/あの/まあ/その 等）・言い直し・重複を取り除き、"
    "簡潔な1〜数文にします。情報を足したり要約・解説したりせず、"
    "前置き（「整えた文章：」等）は一切出力しないでください。\n発話: "
)

# qwen3 等が think=False でも稀に混ぜる <think>…</think> を保険で除去する。
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def build_refine_prompt(text: str) -> str:
    """整形プロンプトを組み立てる（純関数）。"""
    return f"{REFINE_INSTRUCTION}{text}"


def refine_text(text: str, *, model: str = "qwen3:8b") -> str:
    """確定セグメント1件を整形して返す。空入力は空を返す。

    think=False で思考トークンを抑止（追い上げなので低レイテンシ優先）。失敗は呼び出し側で
    握って STT を止めない方針のため、本関数は例外をそのまま投げる。
    """
    src = text.strip()
    if not src:
        return ""
    resp = ollama.generate(model=model, prompt=build_refine_prompt(src), think=False)
    return _THINK.sub("", resp.response or "").strip()

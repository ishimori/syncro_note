"""ケバ取り済みテキストを Ollama(バッチLLM)で議事録Markdownに要約する。

設計SSOT: 深い構造化は終了後バッチ。既定モデルは gemma4:26b（DD-002で本機最速のMoE）。
出力は「## 要約 / ## 決定事項 / ## TODO」の3セクションに強制する。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import ollama

MINUTES_INSTRUCTION = (
    "あなたは優秀な会議の書記です。以下の会議の書き起こしテキストから、日本語の議事録を"
    "Markdownで作成してください。必ず次の3つの見出しを作り、それぞれ箇条書きでまとめます。\n"
    "「## 要約」: 会議全体の要点。\n"
    "「## 決定事項」: 確定した事項（可能なら 誰が・何を）。\n"
    "「## TODO」: 今後のアクション（可能なら 担当者・期限）。\n"
    "言い淀みや重複は除き、書き起こしの事実だけに基づいて簡潔に書きます。"
    "前置きや解説（「以下が議事録です」等）は一切出力しないでください。\n"
)


def build_minutes_prompt(
    transcript: str,
    *,
    title: str = "",
    agenda: str = "",
    vocab: Iterable[str] | None = None,
) -> str:
    """議事録生成用のプロンプトを組み立てる（純関数）。"""
    ctx_lines: list[str] = []
    if title:
        ctx_lines.append(f"- 会議名: {title}")
    if agenda:
        ctx_lines.append(f"- アジェンダ: {agenda}")
    if vocab:
        terms = ", ".join(vocab)
        if terms:
            ctx_lines.append(f"- 専門用語: {terms}")
    context = ("# 前提\n" + "\n".join(ctx_lines) + "\n\n") if ctx_lines else ""
    return f"{MINUTES_INSTRUCTION}\n{context}--- 書き起こし ---\n{transcript}\n"


def summarize(
    transcript: str,
    *,
    model: str = "gemma4:26b",
    title: str = "",
    agenda: str = "",
    vocab: Iterable[str] | None = None,
    think: bool = False,
) -> str:
    """書き起こしから議事録Markdownを生成して返す。"""
    prompt = build_minutes_prompt(transcript, title=title, agenda=agenda, vocab=vocab)
    response = ollama.generate(model=model, prompt=prompt, think=think)
    return response.response.strip()


def stream_summarize(
    transcript: str,
    *,
    model: str = "gemma4:26b",
    title: str = "",
    agenda: str = "",
    vocab: Iterable[str] | None = None,
    think: bool = False,
) -> Iterator[tuple[str, dict | None]]:
    """議事録をストリーミング生成する。

    生成中は (これまでの累積テキスト, None) を逐次返し、最後のチャンクで
    (全文, メトリクス辞書) を返す。メトリクス: input_tokens / output_tokens / eval_s。
    """
    prompt = build_minutes_prompt(transcript, title=title, agenda=agenda, vocab=vocab)
    acc = ""
    for chunk in ollama.generate(model=model, prompt=prompt, stream=True, think=think):
        acc += chunk.response or ""
        if chunk.done:
            yield acc, {
                "input_tokens": int(chunk.prompt_eval_count or 0),
                "output_tokens": int(chunk.eval_count or 0),
                "eval_s": float(chunk.eval_duration or 0) / 1e9,
            }
        else:
            yield acc, None

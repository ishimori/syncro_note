"""文字起こし生テキストの機械ケバ取り（フィラー除去＋専門用語の辞書置換）。

設計SSOT: 会議中のケバ取りは LLM でなく辞書＋正規表現で行う（幻覚ゼロ・即時）。
すべて純関数で、pytest で検証する。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# 明確なフィラー（言い淀み）。長音付き・単独で安全に消せるものに限定し、誤爆を避ける。
# 「あの」「その」「まあ」「なんか」など多義で文意を壊しうる語は意図的に含めない。
DEFAULT_FILLERS: tuple[str, ...] = (
    "えーっと",
    "えーと",
    "ええと",
    "えっと",
    "あのー",
    "そのー",
    "えー",
    "あー",
    "うーん",
    "んー",
)


def remove_fillers(text: str, fillers: Iterable[str] = DEFAULT_FILLERS) -> str:
    """フィラー語を除去する（長い順に削除し、部分一致の取りこぼしを防ぐ）。"""
    for filler in sorted(set(fillers), key=len, reverse=True):
        if filler:
            text = text.replace(filler, "")
    return text


def apply_vocab(text: str, vocab: Mapping[str, str]) -> str:
    """誤認識語を正しい用語へ置換する。

    全キーを長い順の正規表現で**単一パス**置換する。逐次 str.replace だと
    置換後テキストに短いキーが再マッチして壊れる（例: 要約モデル→…の中の「要約」が再置換）。
    単一パスなら各位置は一度だけ・最長一致で置換され、誤爆しない。
    """
    if not vocab:
        return text
    keys = sorted(vocab, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    return pattern.sub(lambda m: vocab[m.group(0)], text)


def clean_text(
    text: str,
    *,
    fillers: Iterable[str] = DEFAULT_FILLERS,
    vocab: Mapping[str, str] | None = None,
) -> str:
    """フィラー除去 → 用語置換 → 余分な空白整理 をまとめて適用する。"""
    text = remove_fillers(text, fillers)
    if vocab:
        text = apply_vocab(text, vocab)
    return re.sub(r"[ \t　]+", " ", text).strip()

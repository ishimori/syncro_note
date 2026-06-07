"""pipeline/cleaning（フィラー除去・用語置換・整形）の単体テスト。"""

from __future__ import annotations

from synchroni_note.pipeline.cleaning import (
    apply_vocab,
    clean_text,
    remove_fillers,
)


def test_remove_fillers_basic() -> None:
    assert remove_fillers("えーっとそれでは始めます") == "それでは始めます"


def test_remove_fillers_multiple() -> None:
    assert remove_fillers("あー、えーと次の議題は") == "、次の議題は"


def test_remove_fillers_longest_first() -> None:
    # 「えーっと」を「えー」より先に消す（部分一致で「っと」が残らない）
    assert remove_fillers("えーっと") == ""


def test_remove_fillers_keeps_meaningful_words() -> None:
    # フィラー辞書に無い多義語（あの/その/まあ）は壊さない
    assert remove_fillers("あの人がその件で") == "あの人がその件で"


def test_apply_vocab_replaces_terms() -> None:
    vocab = {"ハウリ": "Tauri", "スキューライト": "SQLite"}
    assert apply_vocab("ハウリとスキューライト", vocab) == "TauriとSQLite"


def test_apply_vocab_longest_key_first() -> None:
    # 長いキーを優先（部分一致の取りこぼし回避）
    vocab = {"要約": "サマリ", "要約モデル": "要約モデル(正)"}
    assert apply_vocab("要約モデルの話", vocab) == "要約モデル(正)の話"


def test_clean_text_combines_and_trims() -> None:
    out = clean_text("えーっと  ハウリの話", vocab={"ハウリ": "Tauri"})
    assert out == "Tauriの話"


def test_clean_text_without_vocab() -> None:
    assert clean_text("あー、了解です") == "、了解です"

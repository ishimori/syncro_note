"""カレンダー予定コピペ取込（DD-012-13）の構造化を Ollama 非依存で検証する。

LLM を呼ぶ ``parse_calendar_text`` は ``generate`` 注入で偽応答を流し、決定論部分
（年補完・24h時刻・ISO組み立て・participants正規化）を固定する。
"""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

from synchroni_note.pipeline.calendar_parse import (
    _pad_time,
    assemble_draft,
    parse_calendar_text,
)

# 実サンプル（ユーザーが貼り付けた予定テキストから LLM が抽出するはずの素のdict）。
# 年は書かれていない（year=None）→ システム年で補完されることを検証する。
SAMPLE_RAW = {
    "title": "SendaiM様案件事前Webミーティング",
    "year": None,
    "month": 6,
    "day": 9,
    "start_time": "16:30",
    "end_time": "17:00",
    "place": "meet.google.com/irt-xqsn-nzo",
    "agenda": "電話で参加 (JP) +81 3-4545-0450 PIN: 110 895 575 6627#",
    "participants": [
        {"name": "中嶋竜大", "role": "主催者"},
        {"name": "石森譲", "role": ""},
        {"name": "hiromi.sakurai@crossroute.co.jp", "role": ""},
        {"name": "miura b.mode", "role": ""},
    ],
}


def test_pad_time_normalizes_and_rejects() -> None:
    assert _pad_time("16:30") == "16:30"
    assert _pad_time("9:5") == "09:05"
    assert _pad_time("25:00") is None  # 範囲外
    assert _pad_time("夕方") is None
    assert _pad_time(None) is None


def test_assemble_completes_missing_year_with_system_year() -> None:
    draft = assemble_draft(SAMPLE_RAW, current_year=2026)
    assert draft["title"] == "SendaiM様案件事前Webミーティング"
    # 年欠落 → 2026 で補完し、要確認フラグが立つ（「6/9」→ 2026/6/9）。
    assert draft["scheduled_start"] == "2026-06-09T16:30:00"
    assert draft["scheduled_end"] == "2026-06-09T17:00:00"
    assert draft["year_inferred"] is True
    assert draft["place"] == "meet.google.com/irt-xqsn-nzo"


def test_assemble_keeps_explicit_year_without_flag() -> None:
    raw = {**SAMPLE_RAW, "year": 2027}
    draft = assemble_draft(raw, current_year=2026)
    assert draft["scheduled_start"] == "2027-06-09T16:30:00"
    assert draft["year_inferred"] is False  # 年が書かれていたので補完していない


def test_participants_drop_empty_and_keep_email_only() -> None:
    draft = assemble_draft(SAMPLE_RAW, current_year=2026)
    names = [p["name"] for p in draft["participants"]]
    assert names == [
        "中嶋竜大",
        "石森譲",
        "hiromi.sakurai@crossroute.co.jp",  # メールのみでも保持
        "miura b.mode",
    ]
    assert draft["participants"][0]["role"] == "主催者"


def test_assemble_no_date_yields_null_start() -> None:
    raw = {"title": "雑談", "month": None, "day": None}
    draft = assemble_draft(raw, current_year=2026)
    assert draft["scheduled_start"] is None
    assert draft["scheduled_end"] is None
    assert draft["year_inferred"] is False


def test_assemble_start_only_no_end() -> None:
    raw = {"title": "朝会", "month": 6, "day": 10, "start_time": "9:00", "end_time": None}
    draft = assemble_draft(raw, current_year=2026)
    assert draft["scheduled_start"] == "2026-06-10T09:00:00"
    assert draft["scheduled_end"] is None


def test_parse_calendar_text_uses_injected_generate_and_system_year() -> None:
    # 偽 generate: ollama.generate と同じく resp.response に JSON 文字列を返す。
    captured: dict[str, object] = {}

    def fake_generate(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(response=json.dumps(SAMPLE_RAW))

    draft = parse_calendar_text("（貼り付けテキスト）", generate=fake_generate)
    # format="json" と think=False で呼んでいること（JSON強制・思考トークン抑止）。
    assert captured["format"] == "json"
    assert captured["think"] is False
    # current_year 省略 → システム年で補完される。
    this_year = datetime.date.today().year
    assert draft["scheduled_start"] == f"{this_year:04d}-06-09T16:30:00"
    assert draft["year_inferred"] is True

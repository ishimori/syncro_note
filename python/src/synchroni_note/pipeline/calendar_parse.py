"""カレンダー予定テキストの構造化（完全オフライン・DD-012-13）。

Googleカレンダー等からコピペした「予定の詳細テキスト」を、ローカルLLM（qwen3:8b）で
件名・日時・場所・出席者に構造化し、S-02 会議作成フォームへ流し込める dict に畳む。
外部送信は一切しない（ollama はローカルのみで完結）。

設計の正: doc/DD/DD-012-13_*.md。
  - LLM には「抽出」だけ任せる（year/month/day・24h時刻・participants を素の値で出させる）。
  - **年の補完と ISO 組み立ては Python 側の決定論**で行う（テスト可能・LLM非依存）:
      年が無ければ実行時のシステム年で補完し ``year_inferred=True`` を立てる（UIが「要確認」表示）。
  - ``assemble_draft`` は純関数。``parse_calendar_text`` のみ ollama を呼ぶ（注入で差し替え可）。
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Any

import ollama

# LLM への抽出指示。出力は JSON 1個のみ（format="json" と併用）。日時は素の数値＋24h時刻で出させ、
# 年の補完や ISO 化は Python 側（assemble_draft）が決定論で行う＝LLM の自由度を最小化する。
PARSE_INSTRUCTION = (
    "あなたはカレンダーの予定テキストを構造化する抽出器です。"
    "入力された予定テキストから次のJSONを**1つだけ**出力してください。説明文は一切出力しないこと。\n"
    "{\n"
    '  "title": 件名(文字列),\n'
    '  "year": 年(整数。テキストに年が書かれていなければ null。推測しないこと),\n'
    '  "month": 月(整数 1-12),\n'
    '  "day": 日(整数 1-31),\n'
    '  "start_time": 開始時刻("HH:MM" の24時間表記。午後4:30なら "16:30"。不明なら null),\n'
    '  "end_time": 終了時刻("HH:MM" の24時間表記。不明なら null),\n'
    '  "place": 場所やURL(文字列。会議URLや会議室名。無ければ ""),\n'
    '  "agenda": 議題やメモ(文字列。電話番号/PIN等の補足を含めてよい。無ければ ""),\n'
    '  "participants": 出席者の配列。各要素は {"name": 氏名またはメール, "role": 役割}。\n'
    '      主催者には role に "主催者" を入れる。役割が無ければ role は ""。\n'
    "      名前が無くメールのみなら name にメールを入れる。\n"
    "}\n"
    "午前/午後は必ず24時間表記へ変換すること（午前9時→\"09:00\"、午後5時→\"17:00\"）。\n"
)


def build_parse_prompt(text: str) -> str:
    """予定テキストから抽出JSONを得るプロンプトを組み立てる（純関数）。"""
    return f"{PARSE_INSTRUCTION}\n--- 予定テキスト ---\n{text.strip()}\n"


def _pad_time(t: Any) -> str | None:
    """``"16:30"`` / ``"9:5"`` を ``"HH:MM"`` に正規化。範囲外・形式不一致は None。"""
    if not isinstance(t, str):
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{1,2})\s*$", t)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def _participants(raw: Any) -> list[dict[str, str]]:
    """LLM出力の participants を ``[{"name","role"}]`` に正規化（空名は除外・メールのみ許容）。"""
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for p in raw:
        if isinstance(p, dict):
            name = str(p.get("name") or "").strip()
            role = str(p.get("role") or "").strip()
        else:
            name, role = str(p).strip(), ""
        if name:
            out.append({"name": name, "role": role})
    return out


def assemble_draft(raw: dict[str, Any], *, current_year: int) -> dict[str, Any]:
    """LLMの素の抽出dictを、S-02フォーム用の確定draftに畳む（純関数・決定論）。

    年が無ければ ``current_year`` で補完し ``year_inferred=True`` を立てる（UIが要確認表示）。
    月日が揃わなければ日時は組み立てず ``scheduled_start=None``（UIは日付欄を既定のまま）。
    """
    month, day, year = raw.get("month"), raw.get("day"), raw.get("year")
    year_inferred = False
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    if isinstance(month, int) and isinstance(day, int) and 1 <= month <= 12 and 1 <= day <= 31:
        if not isinstance(year, int):
            year, year_inferred = current_year, True
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        start = _pad_time(raw.get("start_time")) or "00:00"
        scheduled_start = f"{date_str}T{start}:00"
        end = _pad_time(raw.get("end_time"))
        if end:
            scheduled_end = f"{date_str}T{end}:00"
    return {
        "title": str(raw.get("title") or "").strip(),
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "place": str(raw.get("place") or "").strip(),
        "agenda": str(raw.get("agenda") or "").strip(),
        "participants": _participants(raw.get("participants")),
        "year_inferred": year_inferred,
    }


def parse_calendar_text(
    text: str,
    *,
    model: str = "qwen3:8b",
    current_year: int | None = None,
    generate: Any = None,
) -> dict[str, Any]:
    """予定テキストを構造化draftに変換する（ollama 呼び出しは ``generate`` 注入で差替可）。

    ``current_year`` 省略時は実行時のシステム年（年欠落の補完に使う）。
    """
    gen = generate or ollama.generate
    year = current_year if current_year is not None else datetime.date.today().year
    prompt = build_parse_prompt(text)
    resp = gen(model=model, prompt=prompt, format="json", think=False)
    content = resp.response if hasattr(resp, "response") else resp["response"]
    raw = json.loads(content)
    if not isinstance(raw, dict):
        raise ValueError(f"LLM出力がオブジェクトではありません: {type(raw).__name__}")
    return assemble_draft(raw, current_year=year)

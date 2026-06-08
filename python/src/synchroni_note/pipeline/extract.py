"""事前資料（Excel/PDF）の本文抽出（完全オフライン・DD-012-10）。

会議に添付した .xlsx / .pdf からテキストレイヤを抜き出し、清書バッチの入力
（前提資料セクション）に統合するための薄い抽出口。外部送信は一切しない
（openpyxl / pymupdf はローカルのみで完結）。

生のタブ羅列ではなく、**LLM が文脈として使いやすい構造化テキスト**を返す:
xlsx＝「（Excel・Nシート: …）」概要＋シートごとに「行×列」見出し＋Markdownテーブル、
pdf＝「（PDF・Nページ）」概要＋``## p.N`` ページ見出し＋本文。

設計の正: doc/DD/DD-012-10_*.md の「Phase 0 設計判断」。
  - ``extract_text(path, file_type=None) -> ExtractResult``
  - 未対応拡張子は ``ValueError``、破損/暗号化はライブラリ例外を送出（呼び元が error に変換）。
  - 上限 ``EXTRACT_MAX_CHARS`` を超える本文は先頭優先でトリム（清書プロンプト膨張対策, DA#2）。
  - テキストゼロ（画像PDF等）は例外にせず ``empty=True`` で返す（UI 注意表示用, DA#1）。

対象外（将来・別DD）: 画像PDFのOCR、.docx/.pptx、パスワード解除。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 清書プロンプト膨張を防ぐ本文上限（先頭優先でトリム）。
# 1万字 ≒ 日本語で原稿用紙25枚相当。前提資料としては十分で、文脈を圧迫しない目安。
EXTRACT_MAX_CHARS = 10_000

# トリム時に末尾へ付す注記（清書側が「以降省略」と分かるように）。
_TRUNCATE_NOTE = "\n…（以降は文字数上限により省略）"


@dataclass(frozen=True)
class ExtractResult:
    """抽出結果。``text`` は上限トリム済み・正規化済みの本文。"""

    text: str
    chars: int  # トリム後の文字数
    truncated: bool  # 上限超過でトリムしたか
    empty: bool  # 抽出本文が実質ゼロ（空白のみ）か＝画像PDF等の注意表示用


def _trim(text: str) -> tuple[str, bool]:
    """先頭優先で ``EXTRACT_MAX_CHARS`` までに収める。超えたら注記を付す。"""
    if len(text) <= EXTRACT_MAX_CHARS:
        return text, False
    return text[:EXTRACT_MAX_CHARS] + _TRUNCATE_NOTE, True


def _cell(v: object) -> str:
    """セル値を1行のテキストへ正規化（改行/タブ→空白、表を壊す ``|`` をエスケープ）。"""
    s = "" if v is None else str(v)
    return s.replace("\r", " ").replace("\n", " ").replace("\t", " ").replace("|", "\\|").strip()


def _md_table(rows: list[list[str]]) -> str:
    """非空セル行の集合を Markdown テーブルにする（1行目をヘッダ扱い）。LLM が解釈しやすい形。"""
    width = max((len(r) for r in rows), default=0)
    if width == 0:
        return "（空）"
    norm = [[r[i] if i < len(r) else "" for i in range(width)] for r in rows]
    out = ["| " + " | ".join(norm[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(out)


def _extract_xlsx(path: Path) -> tuple[str, bool]:
    """xlsx を**構造化テキスト**にする（概要＋シートごとに「行×列」＋Markdownテーブル）。

    生のタブ羅列ではなく、ファイル概要・シート名・寸法・整形テーブルを与えて LLM が
    文脈として使いやすい形にする（DD-012-10 改善）。``data_only=True``＝数式は計算値、
    ``read_only=True`` で省メモリ走査。戻り値の2要素目は「実データがあったか」。
    """
    import openpyxl  # 遅延 import（抽出時のみロード）

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        names = [ws.title for ws in wb.worksheets]
        parts = [f"（Excel・{len(names)}シート: {', '.join(names)}）"]
        has_content = False
        for ws in wb.worksheets:
            rows: list[list[str]] = []
            for row in ws.iter_rows(values_only=True):
                cells = [_cell(c) for c in row]
                while cells and cells[-1] == "":  # 右端の空セルを落とす
                    cells.pop()
                if any(cells):  # 全空行はスキップ
                    rows.append(cells)
            ncols = max((len(r) for r in rows), default=0)
            parts.append(f"\n## シート「{ws.title}」（{len(rows)}行 × {ncols}列）")
            if rows:
                has_content = True
                parts.append(_md_table(rows))
            else:
                parts.append("（空）")
        return "\n".join(parts), has_content
    finally:
        wb.close()


def _extract_pdf(path: Path) -> tuple[str, bool]:
    """pdf をページ見出し付きで構造化（概要＋ページ本文）。画像PDFは本文なし（OCR対象外）。"""
    import fitz  # pymupdf。遅延 import

    doc = fitz.open(path)
    try:
        parts = [f"（PDF・{doc.page_count}ページ）"]
        has_content = False
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            parts.append(f"\n## p.{i}")
            if text:
                has_content = True
                parts.append(text)
            else:
                parts.append("（テキストなし）")
        return "\n".join(parts), has_content
    finally:
        doc.close()


def _infer_type(path: Path) -> str:
    """拡張子から種別を推定。未対応は ``ValueError``。"""
    suffix = path.suffix.lower().lstrip(".")
    if suffix in ("xlsx", "pdf"):
        return suffix
    raise ValueError(f"未対応の拡張子: {path.suffix!r}（対応は xlsx / pdf）")


def extract_text(path: Path | str, file_type: str | None = None) -> ExtractResult:
    """添付ファイルから本文を抽出する（オフライン）。

    ``file_type`` 省略時は拡張子から推定。破損/暗号化ファイルは各ライブラリの例外を
    そのまま送出する（呼び元の sidecar が ``status="error"`` に変換する契約）。
    """
    path = Path(path)
    ftype = (file_type or _infer_type(path)).lower()
    if ftype == "xlsx":
        raw, has_content = _extract_xlsx(path)
    elif ftype == "pdf":
        raw, has_content = _extract_pdf(path)
    else:
        raise ValueError(f"未対応のtype: {ftype!r}（対応は xlsx / pdf）")

    # 実データが無い（画像PDF等）なら構造の骨組みも保存しない（＝本文なし扱い）。
    if not has_content:
        return ExtractResult(text="", chars=0, truncated=False, empty=True)

    text, truncated = _trim(raw)
    return ExtractResult(text=text, chars=len(text), truncated=truncated, empty=False)
